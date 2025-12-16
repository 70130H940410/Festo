# core/manager_routes.py
# 負責管理者後台：庫存管理 & 製程模板管理 & 訂單總覽

from flask import Blueprint, render_template, request
from . import manager_required
from .db import get_order_mgmt_db

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")


@manager_bp.route("/inventory")
@manager_required
def manager_inventory():
    """
    庫存管理頁：
    目前先純顯示 HTML，之後再接 inventory 表。
    """
    return render_template("manager/inventory.html")


@manager_bp.route("/process-templates")
@manager_required
def manager_process_templates():
    """
    製程模板管理頁：
    先用 demo 資料顯示表格。
    之後可以改成從資料庫讀 process_templates / process_template_steps。
    """
    templates = [
        {
            "id": 1,
            "name": "標準保險絲盒組裝流程",
            "steps": [
                "揀料（上蓋 / 下蓋 / 保險絲 / 電路板）",
                "組裝",
                "電性測試",
                "包裝",
            ],
        },
        {
            "id": 2,
            "name": "高溫壽命測試流程",
            "steps": [
                "揀料",
                "組裝",
                "高溫燒機測試",
                "電性測試",
                "包裝",
            ],
        },
    ]

    return render_template("manager/process_templates.html", templates=templates)


# ✅ 新增：訂單總覽
@manager_bp.route("/orders")
@manager_required
def manager_orders():
    q = request.args.get("q", "").strip()
    step = request.args.get("step", "").strip()

    conn = get_order_mgmt_db()
    cur = conn.cursor()

    sql = """
        SELECT order_id, date, customer_name, product, amount, total_price, step_name, note
        FROM order_list
        WHERE 1=1
    """
    params = []

    if q:
        like = f"%{q}%"
        sql += " AND (order_id LIKE ? OR customer_name LIKE ? OR product LIKE ? OR note LIKE ?)"
        params += [like, like, like, like]

    if step:
        sql += " AND step_name = ?"
        params.append(step)

    sql += " ORDER BY date DESC"

    cur.execute(sql, params)
    orders = cur.fetchall()

    # step 下拉選單
    cur.execute("""
        SELECT DISTINCT step_name
        FROM order_list
        WHERE step_name IS NOT NULL AND step_name != ''
        ORDER BY step_name
    """)
    steps = [r["step_name"] for r in cur.fetchall()]

    conn.close()

    return render_template("manager/orders.html", orders=orders, q=q, step=step, steps=steps)


# ✅ 新增：訂單明細
@manager_bp.route("/orders/<order_id>")
@manager_required
def manager_order_detail(order_id):
    conn = get_order_mgmt_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT order_id, date, customer_name, product, amount, total_price, step_name, note
        FROM order_list
        WHERE order_id = ?
    """, (order_id,))
    order = cur.fetchone()

    conn.close()
    return render_template("manager/order_detail.html", order=order)

