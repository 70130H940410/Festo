# shopping_website/core/manager_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from . import manager_required
from .db import get_product_db, get_order_mgmt_db

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")


# -----------------------------
# ✅ 自動補欄位：避免 no such column: status / cancelled_at / rejected_at
# -----------------------------
def ensure_order_list_schema(conn):
    """
    確保 order_list 有 status / rejected_at / cancelled_at 欄位（沒有就自動補上）
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

        if "cancelled_at" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN cancelled_at TEXT")
            changed = True

        if changed:
            conn.commit()
    except Exception:
        # 不要讓 migration 影響頁面（表不存在等狀況）
        pass


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

        # ✅ 新增步驟
        if action == "add_step":
            try:
                step_order = int((request.form.get("step_order") or "").strip())
                step_name = (request.form.get("step_name") or "").strip()
                station = (request.form.get("station") or "").strip()
                description = (request.form.get("description") or "").strip()
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

        # ✅ 批次更新秒數
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
# ✅ 訂單總覽（支援 rowid 搜尋 + step 篩選 + 勾選顯示 rejected/cancelled/completed）
# 預設只顯示 active
# -----------------------------
@manager_bp.route("/orders", methods=["GET"])
@manager_required
def manager_orders():
    q = request.args.get("q", "").strip()
    step = request.args.get("step", "").strip()

    # ✅ 三個勾選：顯示 rejected / cancelled / completed
    show_rejected = request.args.get("show_rejected") == "1"
    show_cancelled = request.args.get("show_cancelled") == "1"
    show_completed = request.args.get("show_completed") == "1"

    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)
    cur = conn.cursor()

    base_sql = """
        SELECT
            rowid AS id,
            order_id, date, customer_name, product, amount, total_price,
            step_name, note, status, rejected_at, cancelled_at
        FROM order_list
        WHERE 1=1
    """
    params = []

    # ✅ status：預設只 active，勾選才加入 rejected/cancelled/completed
    allowed_status = ["active"]
    if show_rejected:
        allowed_status.append("rejected")
    if show_cancelled:
        allowed_status.append("cancelled")
    if show_completed:
        allowed_status.append("completed")

    base_sql += f" AND status IN ({','.join(['?'] * len(allowed_status))}) "
    params.extend(allowed_status)

    # ✅ 搜尋（訂單ID / 客戶 / 產品 / 備註 / ID(rowid)）
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

    # ✅ step 篩選
    if step:
        base_sql += " AND step_name = ?"
        params.append(step)

    base_sql += " ORDER BY date DESC"

    cur.execute(base_sql, params)
    orders = cur.fetchall()

    # step 下拉選單（抓所有不同 step_name）
    cur.execute(
        """
        SELECT DISTINCT step_name
        FROM order_list
        WHERE step_name IS NOT NULL AND step_name != ''
        ORDER BY step_name
        """
    )
    steps = [r["step_name"] for r in cur.fetchall()]

    conn.close()

    return render_template(
        "manager/orders.html",
        orders=orders,
        q=q,
        step=step,
        steps=steps,
        show_rejected=show_rejected,
        show_cancelled=show_cancelled,
        show_completed=show_completed,  # ✅ 一定要傳給前端
    )


@manager_bp.route("/orders/<order_id>", methods=["GET"])
@manager_required
def manager_order_detail(order_id):
    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            rowid AS id,
            order_id, date, customer_name, product, amount, total_price,
            step_name, note, status, rejected_at, cancelled_at
        FROM order_list
        WHERE order_id = ?
        """,
        (order_id,),
    )
    order = cur.fetchone()
    conn.close()
    return render_template("manager/order_detail.html", order=order)


# ✅ 管理者：拒絕訂單（保留紀錄）
# ✅ 重點：cancelled / completed 的單不能再拒絕
@manager_bp.route("/orders/<order_id>/delete", methods=["POST"])
@manager_required
def manager_order_delete(order_id):
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("❌ 請選擇拒絕原因", "danger")
        return redirect(url_for("manager.manager_orders"))

    # ✅ 保留原查詢條件 + 勾選狀態
    q = (request.form.get("q") or "").strip()
    step = (request.form.get("step") or "").strip()
    show_rejected = (request.form.get("show_rejected") or "") == "1"
    show_cancelled = (request.form.get("show_cancelled") or "") == "1"
    show_completed = (request.form.get("show_completed") or "") == "1"

    kwargs = {}
    if q:
        kwargs["q"] = q
    if step:
        kwargs["step"] = step
    if show_rejected:
        kwargs["show_rejected"] = "1"
    if show_cancelled:
        kwargs["show_cancelled"] = "1"
    if show_completed:
        kwargs["show_completed"] = "1"

    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)
    cur = conn.cursor()

    cur.execute("SELECT status FROM order_list WHERE order_id = ?", (order_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        flash("找不到該訂單", "danger")
        return redirect(url_for("manager.manager_orders", **kwargs))

    status = (row["status"] or "active")

    if status == "cancelled":
        conn.close()
        flash("此訂單已被客戶取消，無法再拒絕。", "warning")
        return redirect(url_for("manager.manager_orders", **kwargs))

    if status == "completed":
        conn.close()
        flash("此訂單已完成，無法再拒絕。", "warning")
        return redirect(url_for("manager.manager_orders", **kwargs))

    if status == "rejected":
        conn.close()
        flash("此訂單已拒絕，無法重複拒絕。", "warning")
        return redirect(url_for("manager.manager_orders", **kwargs))

    note_text = f"你的訂單已被工廠拒絕：{reason}"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        UPDATE order_list
        SET status = 'rejected',
            note = ?,
            rejected_at = ?
        WHERE order_id = ?
        """,
        (note_text, now_str, order_id),
    )
    conn.commit()
    conn.close()

    flash("✅ 已拒絕訂單（保留紀錄）", "success")
    return redirect(url_for("manager.manager_orders", **kwargs))
