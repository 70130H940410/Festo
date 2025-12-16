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
    1. 計算總價
    2. 產生訂單 ID
    3. 寫入訂單紀錄 (order_management.db)
    4. [新增] 扣除產品庫存 (product.db)
    """
    conn_order = None # 訂單資料庫連線
    conn_prod = None  # 產品資料庫連線 (用於查價、查步驟、扣庫存)

    try:
        # --- 1. 獲取資料 ---
        data = request.get_json()
        selected_steps_ids = data.get("selected_steps", [])
        
        cart_items = session.get("current_order_items")
        if not cart_items:
            return jsonify({"success": False, "message": "購物車逾時，請重新下單"}), 400

        customer_name = session.get("account", "Guest")
        
        # 開啟兩邊的資料庫連線
        conn_prod = get_product_db()
        conn_order = get_order_mgmt_db()
        
        cur_prod = conn_prod.cursor()
        cur_order = conn_order.cursor()
        
        # --- 2. 資料準備與計算 ---
        
        # (A) 重新計算總價並確認庫存充足
        total_price = 0
        product_names = []
        
        for item in cart_items:
            # 查詢最新價格與庫存
            cur_prod.execute("SELECT name, base_price, stock FROM products WHERE id = ?", (item['id'],))
            prod_row = cur_prod.fetchone()
            
            if not prod_row:
                raise Exception(f"找不到產品 ID: {item['id']}")
            
            # 安全性檢查：下單前再次確認庫存
            current_stock = prod_row['stock']
            if current_stock < item['quantity']:
                raise Exception(f"產品 {prod_row['name']} 庫存不足 (剩餘 {current_stock})，下單失敗")
                
            # 計算價格
            price = prod_row['base_price'] if prod_row['base_price'] is not None else 0
            total_price += price * item['quantity']
            
            # 串接名稱 (例如 "黑色保險絲盒 x 2")
            product_names.append(f"{prod_row['name']} x {item['quantity']}")
            
            # [新增] 執行扣庫存 SQL (還沒 commit 之前不會真的生效)
            # stock = stock - quantity
            cur_prod.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?", 
                (item['quantity'], item['id'])
            )

        product_str = ", ".join(product_names)
        total_amount = sum(item['quantity'] for item in cart_items)
        
        # (B) 處理製程步驟名稱
        cur_prod.execute("SELECT step_order, step_name FROM standard_process")
        step_map = {str(row["step_order"]): row["step_name"] for row in cur_prod.fetchall()}
        
        # 這裡改成只存 ID 串接，如您要求
        step_name_str = " -> ".join(map(str, selected_steps_ids))
        
        # (C) 準備訂單欄位
        order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note = "無備註"
        custom_order_id = generate_order_id(conn_order)
        
        # --- 3. 寫入訂單資料庫 ---
        sql_order = """
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
        
        cur_order.execute(sql_order, (
            custom_order_id,
            order_date,
            customer_name,
            product_str,
            total_amount,
            total_price,
            step_name_str,
            note
        ))
        
        # --- 4. 提交交易 (Commit) ---
        # 兩個資料庫都沒報錯才儲存
        conn_prod.commit()  # 提交庫存扣除
        conn_order.commit() # 提交訂單建立
        
        # 5. 清除購物車
        session.pop("current_order_items", None)

        return jsonify({
            "success": True, 
            "message": "下單成功！",
            "redirect_url": url_for('factory.simulate', order_id=custom_order_id)
        })

    except Exception as e:
        # 若發生任何錯誤，復原變更
        if conn_prod: conn_prod.rollback()
        if conn_order: conn_order.rollback()
        print(f"Error during submit_order: {str(e)}")
        return jsonify({"success": False, "message": f"下單失敗: {str(e)}"}), 500
    finally:
        # 關閉連線
        if conn_prod: conn_prod.close()
        if conn_order: conn_order.close()