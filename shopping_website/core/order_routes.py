# core/order_routes.py
# 負責「我要下單」與「製程規劃」頁面

from flask import Blueprint, render_template, request, redirect, url_for, session

from . import login_required
from .db import get_product_db

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

