# core/order_routes.py
# 負責「我要下單」與「製程規劃」頁面

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime
import time
from . import login_required
from .db import get_product_db, get_order_mgmt_db

order_bp = Blueprint("order", __name__)


@order_bp.route("/order", methods=["GET", "POST"])
@login_required
def order_page():
    """
    下單頁：
    - GET:顯示產品列表 + 數量輸入格
    - POST:檢查每個產品的數量，存到 session["current_order_items"]，然後導到製程規劃頁
    """

    # 先把產品列表抓出來（不管 GET / POST 都會用到）
    conn = get_product_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id,
            name,
            description,
            base_price,
            stock
        FROM products
        ORDER BY id
        """
    )
    rows = cur.fetchall()
    conn.close()

    # 把資料整理成給模板用的格式
    # 注意：雖然 DB 欄位是 TOTAL，我們在 Python 裡統一叫做 p["stock"]
    products = [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "base_price": row["base_price"],
            "stock": row["stock"],
        }
        for row in rows
    ]

    error_message = None

    if request.method == "POST":
        selected_items = []

        for p in products:
            field_name = f"qty_{p['id']}"
            qty_str = request.form.get(field_name, "").strip()
            if qty_str == "" or qty_str == "0":
                continue

            # 檢查數量是否為整數
            try:
                qty = int(qty_str)
            except ValueError:
                error_message = f"{p['name']} 的數量請輸入整數。"
                break

            if qty < 0:
                error_message = f"{p['name']} 的數量不可為負。"
                break

            if qty > p["stock"]:
                error_message = f"{p['name']} 的數量超過庫存（最多 {p['stock']} 件）。"
                break

            if qty > 0:
                selected_items.append(
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "quantity": qty,
                    }
                )

        if not error_message:
            if not selected_items:
                error_message = "請至少選擇一項產品。"
            else:
                # 將本次選的產品與數量暫存在 session，給製程規劃頁使用
                session["current_order_items"] = selected_items
                return redirect(url_for("order.process_plan"))

    return render_template(
        "order/order_page.html",
        products=products,
        error_message=error_message,
    )


@order_bp.route("/process-plan", methods=["GET", "POST"])
@login_required
def process_plan():
    """
    製程規劃頁：
    - 從 session["current_order_items"] 讀取本次訂單摘要
    - 若 session 沒東西，退回 demo 資料（避免直接輸入網址爆掉）
    """
    # 1. 從資料庫讀取製程步驟
    conn = get_product_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 
            step_order, 
            step_name, 
            station, 
            description, 
            estimated_time_sec 
        FROM standard_process 
        ORDER BY step_order ASC
        """
    )
    rows = cur.fetchall()
    conn.close()

    # 將資料庫 Row 物件轉為字典列表，傳給前端
    standard_steps = [
        {
            "step_order": row["step_order"],
            "step_name": row["step_name"],
            "station": row["station"],
            "description": row["description"],
            "estimated_time_sec": row["estimated_time_sec"],
        }
        for row in rows
    ]

    # 2. 讀取 Session 中的訂單摘要 (如果沒有則給個預設顯示)
    order_items_summary = session.get("current_order_items")
    if not order_items_summary:
        order_items_summary = [
            {"name": "(無訂單資料 - 僅供預覽)", "quantity": 0},
        ]

    return render_template(
        "order/process_plan.html",
        standard_steps=standard_steps,
        order_items_summary=order_items_summary,
    )

def generate_order_id(conn):
    """
    產生格式如 202512170105001 的訂單 ID
    格式邏輯: YYYYMMDDHHMM (24小時制) + 3位流水號
    功能說明：確保產生的 ID 是唯一的，以分鐘為單位，同分鐘內若有訂單則流水號遞增。
    """
    now = datetime.now()
    # 格式化為 YYYYMMDDHHMM，例如 202512170105
    time_prefix = now.strftime("%Y%m%d%H%M")
    
    cur = conn.cursor()
    # 查詢資料庫中，該分鐘是否已經有訂單 (搜尋 ID 開頭符合的)
    try:
        cur.execute("SELECT order_id FROM order_list WHERE order_id LIKE ? ORDER BY order_id DESC LIMIT 1", (f"{time_prefix}%",))
        row = cur.fetchone()
        
        if row:
            # 如果該分鐘已經有單，取最後一筆的後3碼 + 1
            last_id = row['order_id'] # e.g., 202512170105001
            try:
                last_seq = int(last_id[-3:]) # 取出 001
                new_seq = last_seq + 1
            except:
                new_seq = 1
        else:
            # 該分鐘第一筆
            new_seq = 1
    except Exception:
        # 如果表還不存在或查詢失敗，預設從 1 開始
        new_seq = 1
        
    # 補零至3位數 (e.g., 1 -> 001)
    return f"{time_prefix}{str(new_seq).zfill(3)}"


# -----------------------------------------------------------
#  4. API：送出訂單 (寫入資料庫)
# -----------------------------------------------------------
@order_bp.route("/api/submit_order", methods=["POST"])
@login_required
def submit_order_api():
    """
    接收 JSON 資料，依照您的自訂格式寫入 order_management.db
    功能說明：
    1. 接收前端勾選的製程步驟 ID。
    2. 從 Session 讀取購物車內容、使用者帳號。
    3. 計算總價、串接產品名稱字串、串接製程步驟名稱字串。
    4. 生成自訂訂單 ID。
    5. 將所有資料 INSERT 到 orders 表格中。
    """
    conn_order = None
    try:
        # 1. 獲取前端傳來的資料
        data = request.get_json()
        selected_steps_ids = data.get("selected_steps", []) # 這是步驟 ID 的列表，如 ['1', '2']
        
        # 2. 獲取 Session 中的購物車與使用者資料
        cart_items = session.get("current_order_items")
        if not cart_items:
            return jsonify({"success": False, "message": "購物車逾時，請重新下單"}), 400

        customer_name = session.get("account", "Guest")
        
        # 3. 資料準備與計算
        
        # (A) 處理產品字串 (product) 與 總數量 (amount)
        # 將產品名稱串接，例如 "黑色保險絲盒 x 2, 白色上蓋 x 1"
        product_list = [f"{item['name']} x {item['quantity']}" for item in cart_items]
        product_str = ", ".join(product_list)
        
        total_amount = sum(item['quantity'] for item in cart_items)
        
        # (B) 計算總價 (total_price)
        # [修改] 為了避免 session 中的 base_price 遺失或為 0，這裡重新查詢資料庫計算價格
        total_price = 0
        conn_prod = get_product_db()
        cur_prod = conn_prod.cursor()
        
        for item in cart_items:
            # 查詢每個商品的最新單價
            cur_prod.execute("SELECT base_price FROM products WHERE id = ?", (item['id'],))
            row = cur_prod.fetchone()
            if row:
                price = row['base_price']
                # 如果資料庫是 NULL，預設為 0
                if price is None: 
                    price = 0
                total_price += price * item['quantity']
        
        # (C) 處理製程步驟名稱 (step_name)
        # 修改為只儲存 step_order，例如 "1 -> 2 -> 3"
        step_name_str = " -> ".join(map(str, selected_steps_ids))

        # 關閉產品資料庫連線
        conn_prod.close()

        # (D) 準備其他欄位
        order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note = "無備註" # 您可以預留未來讓前端傳 note 進來: data.get("note", "無備註")

        # 4. 寫入資料庫
        conn_order = get_order_mgmt_db()
        
        # 生成自訂 ID (如 0001217001)
        custom_order_id = generate_order_id(conn_order)
        
        cur = conn_order.cursor()
        
        sql = """
            INSERT INTO order_list (
                order_id, 
                date, 
                customer_name, 
                product, 
                amount, 
                total_price, 
                step_name, 
                note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        cur.execute(sql, (
            custom_order_id,
            order_date,
            customer_name,
            product_str,
            total_amount,
            total_price,
            step_name_str,
            note
        ))
        
        conn_order.commit()
        
        # 5. 清除購物車
        session.pop("current_order_items", None)

        return jsonify({
            "success": True, 
            "message": "下單成功！",
            # 跳轉到模擬頁面，並帶上剛產生的 ID
            "redirect_url": url_for('factory.simulate', order_id=custom_order_id)
        })

    except Exception as e:
        if conn_order: conn_order.rollback()
        print(f"Error: {str(e)}") # 印出錯誤方便除錯
        return jsonify({"success": False, "message": f"資料庫錯誤: {str(e)}"}), 500
    finally:
        if conn_order: conn_order.close()