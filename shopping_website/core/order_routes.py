# core/order_routes.py
# 負責「我要下單」與「製程規劃」頁面

from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime
import time
from . import login_required
from .db import get_product_db, get_order_mgmt_db

order_bp = Blueprint("order", __name__)


# -----------------------------
# ✅ 自動補欄位：避免 no such column: status
# -----------------------------
def ensure_order_list_schema(conn):
    """
    確保 order_list 有 status / rejected_at 欄位（沒有就自動補上）
    """
    cur = conn.cursor()
    try:
        cols = [r[1] for r in cur.execute("PRAGMA table_info(order_list)").fetchall()]
        changed = False

        if "status" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN status TEXT DEFAULT 'active'")
            changed = True

        if "rejected_at" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN rejected_at TEXT")
            changed = True

        if changed:
            conn.commit()
    except Exception:
        pass


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
    """
    now = datetime.now()
    time_prefix = now.strftime("%Y%m%d%H%M")

    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT order_id FROM order_list WHERE order_id LIKE ? ORDER BY order_id DESC LIMIT 1",
            (f"{time_prefix}%",),
        )
        row = cur.fetchone()

        if row:
            last_id = row["order_id"]
            try:
                last_seq = int(last_id[-3:])
                new_seq = last_seq + 1
            except Exception:
                new_seq = 1
        else:
            new_seq = 1
    except Exception:
        new_seq = 1

    return f"{time_prefix}{str(new_seq).zfill(3)}"


# -----------------------------------------------------------
#  4. API：送出訂單 (寫入資料庫)
# -----------------------------------------------------------
@order_bp.route("/api/submit_order", methods=["POST"])
@login_required
def submit_order_api():
    conn_order = None
    conn_prod = None

    try:
        data = request.get_json()
        selected_steps_ids = data.get("selected_steps", [])

        cart_items = session.get("current_order_items")
        if not cart_items:
            return jsonify({"success": False, "message": "購物車逾時，請重新下單"}), 400

        customer_name = session.get("account", "Guest")

        conn_prod = get_product_db()
        conn_order = get_order_mgmt_db()
        ensure_order_list_schema(conn_order)  # ✅ 先補欄位（status/rejected_at）

        cur_prod = conn_prod.cursor()
        cur_order = conn_order.cursor()

        total_price = 0
        product_names = []

        for item in cart_items:
            cur_prod.execute("SELECT name, base_price, stock FROM products WHERE id = ?", (item["id"],))
            prod_row = cur_prod.fetchone()

            if not prod_row:
                raise Exception(f"找不到產品 ID: {item['id']}")

            current_stock = prod_row["stock"]
            if current_stock < item["quantity"]:
                raise Exception(f"產品 {prod_row['name']} 庫存不足 (剩餘 {current_stock})，下單失敗")

            price = prod_row["base_price"] if prod_row["base_price"] is not None else 0
            total_price += price * item["quantity"]

            product_names.append(f"{prod_row['name']} x {item['quantity']}")

            cur_prod.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (item["quantity"], item["id"]),
            )

        product_str = ", ".join(product_names)
        total_amount = sum(item["quantity"] for item in cart_items)

        # 只存步驟 ID 串接（依你原本要求）
        step_name_str = " -> ".join(map(str, selected_steps_ids))

        order_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note = "無備註"
        custom_order_id = generate_order_id(conn_order)

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

        cur_order.execute(
            sql_order,
            (
                custom_order_id,
                order_date,
                customer_name,
                product_str,
                total_amount,
                total_price,
                step_name_str,
                note,
            ),
        )

        conn_prod.commit()
        conn_order.commit()

        session.pop("current_order_items", None)

        return jsonify(
            {
                "success": True,
                "message": "下單成功！",
                "redirect_url": url_for("factory.simulate", order_id=custom_order_id),
            }
        )

    except Exception as e:
        if conn_prod:
            conn_prod.rollback()
        if conn_order:
            conn_order.rollback()
        print(f"Error during submit_order: {str(e)}")
        return jsonify({"success": False, "message": f"下單失敗: {str(e)}"}), 500
    finally:
        if conn_prod:
            conn_prod.close()
        if conn_order:
            conn_order.close()


# -----------------------------------------------------------
#  5. 使用者：訂單紀錄
# -----------------------------------------------------------
@order_bp.route("/orders", methods=["GET"])
@login_required
def order_history():
    customer_name = session.get("account", "Guest")

    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)  # ✅ 先補欄位再查
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            order_id, date, customer_name, product, amount, total_price,
            step_name, note, status, rejected_at
        FROM order_list
        WHERE customer_name = ?
        ORDER BY date DESC
        """,
        (customer_name,),
    )
    orders = cur.fetchall()
    conn.close()

    return render_template("order/orders_history.html", orders=orders)
