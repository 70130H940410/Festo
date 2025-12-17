# shopping_website/core/manager_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from . import manager_required
from .db import get_product_db, get_order_mgmt_db

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")


# -----------------------------
# 庫存管理（新版：直接讀寫 products.stock）
# -----------------------------
@manager_bp.route("/inventory", methods=["GET", "POST"])
@manager_required
def manager_inventory():
    error_message = None
    success_message = None

    conn = get_product_db()
    cur = conn.cursor()

    if request.method == "POST":
        try:
            product_id = int(request.form.get("product_id", "0"))
            new_stock = int(request.form.get("new_stock", "0"))
            if new_stock < 0:
                new_stock = 0

            cur.execute("UPDATE products SET stock = ? WHERE id = ?", (new_stock, product_id))
            conn.commit()
            success_message = "✅ 庫存已更新"
        except Exception as e:
            conn.rollback()
            error_message = f"❌ 更新失敗：{e}"

    cur.execute("SELECT id, name, base_price, stock FROM products ORDER BY id ASC")
    products = cur.fetchall()
    conn.close()

    return render_template(
        "manager/inventory.html",
        products=products,
        error_message=error_message,
        success_message=success_message,
    )


# -----------------------------
# 製程模板管理（standard_process）
# -----------------------------
@manager_bp.route("/process-templates", methods=["GET", "POST"])
@manager_required
def manager_process_templates():
    error_message = None
    success_message = None

    conn = get_product_db()
    cur = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add_step":
            try:
                step_order = int(request.form.get("step_order", "").strip())
                step_name = request.form.get("step_name", "").strip()
                station = request.form.get("station", "").strip()
                description = request.form.get("description", "").strip()
                estimated_time_sec = int((request.form.get("estimated_time_sec", "0") or "0").strip())

                if step_order <= 0:
                    raise ValueError("step_order 必須為正整數")
                if not step_name:
                    raise ValueError("step_name 不可為空")
                if estimated_time_sec < 0:
                    raise ValueError("estimated_time_sec 不可為負數")

                cur.execute("SELECT 1 FROM standard_process WHERE step_order = ?", (step_order,))
                if cur.fetchone():
                    raise ValueError(f"step_order={step_order} 已存在，請換一個順序")

                cur.execute(
                    """
                    INSERT INTO standard_process (step_order, step_name, station, description, estimated_time_sec)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (step_order, step_name, station, description, estimated_time_sec),
                )
                conn.commit()
                success_message = "✅ 已新增製程步驟"
            except Exception as e:
                conn.rollback()
                error_message = f"❌ 新增失敗：{e}"

        elif action == "bulk_update_time":
            try:
                cur.execute("SELECT id, estimated_time_sec FROM standard_process")
                old_map = {str(r["id"]): int(r["estimated_time_sec"] or 0) for r in cur.fetchall()}

                changed = 0
                for k, v in request.form.items():
                    if not k.startswith("time_"):
                        continue

                    row_id = k.split("_", 1)[1]
                    if row_id not in old_map:
                        continue

                    new_sec = int((v or "0").strip() or 0)
                    if new_sec < 0:
                        new_sec = 0

                    if new_sec != old_map[row_id]:
                        cur.execute(
                            "UPDATE standard_process SET estimated_time_sec = ? WHERE id = ?",
                            (new_sec, row_id),
                        )
                        changed += 1

                conn.commit()
                success_message = f"✅ 已更新 {changed} 筆秒數"
            except Exception as e:
                conn.rollback()
                error_message = f"❌ 更新失敗：{e}"

    cur.execute(
        """
        SELECT id, step_order, step_name, station, description, estimated_time_sec
        FROM standard_process
        ORDER BY step_order ASC, id ASC
        """
    )
    steps = cur.fetchall()
    conn.close()

    return render_template(
        "manager/process_templates.html",
        steps=steps,
        error_message=error_message,
        success_message=success_message,
    )


# -----------------------------
# 訂單總覽（支援用 rowid 當作 id 搜尋）
# -----------------------------
@manager_bp.route("/orders", methods=["GET"])
@manager_required
def manager_orders():
    q = request.args.get("q", "").strip()
    step = request.args.get("step", "").strip()

    conn = get_order_mgmt_db()
    cur = conn.cursor()

    base_sql = """
        SELECT rowid AS id, order_id, date, customer_name, product, amount, total_price, step_name, note
        FROM order_list
        WHERE 1=1
    """
    params = []

    if q:
        like = f"%{q}%"
        if q.isdigit():
            base_sql += """
              AND (
                rowid = ?
                OR order_id LIKE ?
                OR customer_name LIKE ?
                OR product LIKE ?
                OR note LIKE ?
              )
            """
            params += [int(q), like, like, like, like]
        else:
            base_sql += """
              AND (
                order_id LIKE ?
                OR customer_name LIKE ?
                OR product LIKE ?
                OR note LIKE ?
              )
            """
            params += [like, like, like, like]

    if step:
        base_sql += " AND step_name = ?"
        params.append(step)

    base_sql += " ORDER BY date DESC"

    cur.execute(base_sql, params)
    orders = cur.fetchall()

    cur.execute("""
        SELECT DISTINCT step_name
        FROM order_list
        WHERE step_name IS NOT NULL AND step_name != ''
        ORDER BY step_name
    """)
    steps = [r["step_name"] for r in cur.fetchall()]

    conn.close()

    return render_template("manager/orders.html", orders=orders, q=q, step=step, steps=steps)


@manager_bp.route("/orders/<order_id>", methods=["GET"])
@manager_required
def manager_order_detail(order_id):
    conn = get_order_mgmt_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT rowid AS id, order_id, date, customer_name, product, amount, total_price, step_name, note
        FROM order_list
        WHERE order_id = ?
        """,
        (order_id,),
    )
    order = cur.fetchone()
    conn.close()
    return render_template("manager/order_detail.html", order=order)


# ✅ 刪單
@manager_bp.route("/orders/<order_id>/delete", methods=["POST"])
@manager_required
def manager_order_delete(order_id):
    conn = get_order_mgmt_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM order_list WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()

    flash("✅ 已刪除訂單", "success")
    return redirect(url_for("manager.manager_orders"))





