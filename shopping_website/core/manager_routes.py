# =============================================================
# core/manager_routes.py
# 工廠管理者（admin 角色）路由模組
# ----------------------------------------------------------
# Blueprint 名稱：manager（前綴 /manager）
# 需要 @manager_required（角色必須是 admin）
#
# 路由清單：
#   GET/POST /manager/inventory          → 庫存管理（查看/更新產品庫存）
#   GET/POST /manager/process-templates  → 製程步驟模板管理
#   GET      /manager/orders             → 訂單總覽（搜尋/篩選/分頁）
#   GET      /manager/orders/<order_id>  → 單筆訂單詳細資料
#   POST     /manager/orders/<order_id>/delete → 拒絕訂單（保留紀錄）
# =============================================================

from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
from . import manager_required
from .db import get_product_db, get_order_mgmt_db

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")


# =============================================================
# 資料庫 Schema 自動遷移（與 order_routes.py 共用邏輯）
# =============================================================

def ensure_order_list_schema(conn):
    """
    確保 order_list 資料表有所有必要欄位（沒有就自動補上）。
    """
    cur = conn.cursor()
    try:
        cols    = [r[1] for r in cur.execute("PRAGMA table_info(order_list)").fetchall()]
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

        if "contact_name" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN contact_name TEXT")
            changed = True

        if "contact_phone" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN contact_phone TEXT")
            changed = True

        if "company" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN company TEXT")
            changed = True

        if "address" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN address TEXT")
            changed = True

        if "source" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN source TEXT DEFAULT 'web'")
            changed = True

        if "mes_ono" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN mes_ono INTEGER")
            changed = True

        if "supabase_order_id" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN supabase_order_id INTEGER")
            changed = True

        if changed:
            conn.commit()
    except Exception:
        pass


# =============================================================
# 庫存管理
# =============================================================

@manager_bp.route("/inventory", methods=["GET", "POST"])
@manager_required
def manager_inventory():
    """
    庫存管理頁面（以工廠 ASRS 倉儲 32 格為單一事實來源 SSOT）。
    """
    error_message   = None
    success_message = None

    from .mes_data_service import MesDataService
    
    # 庫存以工廠 ASRS 倉儲為單一事實來源 (SSOT)
    products = MesDataService.get_unified_products()
    warehouse = MesDataService.get_warehouse_inventory()
    buffer_positions = MesDataService.get_buffer_positions()

    return render_template(
        "manager/inventory.html",
        products=products,
        warehouse=warehouse,
        buffer_positions=buffer_positions,
        error_message=error_message,
        success_message=success_message,
    )


# =============================================================
# 製程步驟模板管理
# =============================================================

@manager_bp.route("/process-templates", methods=["GET", "POST"])
@manager_required
def manager_process_templates():
    """
    製程步驟模板管理頁面（操作 product.db 的 standard_process 資料表）。
    - GET : 顯示所有製程步驟
    - POST: 依 action 欄位執行操作：
        action = "add_step"         → 新增一個製程步驟
        action = "bulk_update_time" → 批次更新所有步驟的預計加工秒數
    
    standard_process 欄位說明：
      step_order        : 步驟順序（正整數，用於決定製程順序）
      step_name         : 步驟名稱（如：組裝、品檢）
      station           : 對應機台名稱（如：StationA）
      description       : 步驟描述
      estimated_time_sec: 預計加工時間（秒）
    """
    error_message   = None
    success_message = None

    conn = get_product_db()
    cur  = conn.cursor()

    if request.method == "POST":
        action = request.form.get("action", "")

        # ---------- 新增製程步驟 ----------
        if action == "add_step":
            try:
                step_order         = int((request.form.get("step_order") or "").strip())
                step_name          = (request.form.get("step_name") or "").strip()
                station            = (request.form.get("station") or "").strip()
                description        = (request.form.get("description") or "").strip()
                estimated_time_sec = int((request.form.get("estimated_time_sec", "0") or "0").strip())

                # 驗證輸入
                if step_order <= 0:
                    raise ValueError("step_order 必須為正整數")
                if not step_name:
                    raise ValueError("step_name 不可為空")
                if estimated_time_sec < 0:
                    raise ValueError("estimated_time_sec 不可為負數")

                # 確認 step_order 不重複
                cur.execute(
                    "SELECT 1 FROM standard_process WHERE step_order = ?",
                    (step_order,),
                )
                if cur.fetchone():
                    raise ValueError(f"step_order={step_order} 已存在，請換一個順序")

                cur.execute(
                    """
                    INSERT INTO standard_process
                    (step_order, step_name, station, description, estimated_time_sec)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (step_order, step_name, station, description, estimated_time_sec),
                )
                conn.commit()
                success_message = "✅ 已新增製程步驟"
            except Exception as e:
                conn.rollback()
                error_message = f"❌ 新增失敗：{e}"

        # ---------- 批次更新所有步驟的預計加工秒數 ----------
        elif action == "bulk_update_time":
            try:
                # 先讀取所有步驟的現有秒數（以 id 為 key）
                cur.execute("SELECT id, estimated_time_sec FROM standard_process")
                old_map = {str(r["id"]): int(r["estimated_time_sec"] or 0) for r in cur.fetchall()}

                changed = 0
                # 遍歷表單，找出所有 time_{id} 欄位
                for k, v in request.form.items():
                    if not k.startswith("time_"):
                        continue

                    row_id  = k.split("_", 1)[1]
                    if row_id not in old_map:
                        continue

                    new_sec = int((v or "0").strip() or 0)
                    if new_sec < 0:
                        new_sec = 0

                    # 只更新有變動的欄位
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

    # 讀取所有製程步驟（按 step_order 排序）
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


# =============================================================
# 訂單總覽（搜尋 + 分頁 + 狀態篩選）
# =============================================================

@manager_bp.route("/orders", methods=["GET"])
@manager_required
def manager_orders():
    """
    管理者訂單總覽頁面，支援：
      - tab 篩選（active/completed/cancelled/pending_payment/all）
      - q 關鍵字搜尋（訂單ID、客戶、產品、備註）
      - step 篩選（依製程路徑篩選）
    
    狀態說明：
      active          → 生產中（已付款，工廠正在生產）
      pending_payment → 待付款
      completed       → 已完成
      cancelled       → 客戶取消
      rejected        → 管理者拒絕
    """
    q      = request.args.get("q", "").strip()
    step   = request.args.get("step", "").strip()
    tab    = request.args.get("tab", "all")  # 預設顯示全部訂單以利查看所有來源
    source = request.args.get("source", "").strip()

    # 自動同步 Supabase line_orders，確保來自 LineTalker 的訂單即時顯示在網站上
    try:
        from .order_sync import sync_line_orders_to_order_list
        sync_line_orders_to_order_list()
    except Exception as e:
        print(f"⚠️ [manager_orders] 同步 LineTalker 訂單異常: {e}")

    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)
    cur  = conn.cursor()

    # 基礎查詢 SQL
    base_sql = """
        SELECT
            rowid AS id,
            order_id, date, customer_name, product, amount, total_price,
            step_name, note, status, rejected_at, cancelled_at,
            contact_name, contact_phone, company, address, source, mes_ono
        FROM order_list
        WHERE 1=1
    """
    params = []

    # 來源篩選 (line / web)
    if source in ("line", "web"):
        base_sql += " AND source = ? "
        params.append(source)

    # 依 tab 篩選狀態
    if tab == "active":
        base_sql += " AND status NOT IN ('completed', 'cancelled', 'rejected', 'pending_payment') "
    elif tab == "completed":
        base_sql += " AND status = 'completed' "
    elif tab == "cancelled":
        base_sql += " AND status IN ('cancelled', 'rejected') "
    elif tab == "pending_payment":
        base_sql += " AND status = 'pending_payment' "
    # tab == "all" 時不加狀態過濾

    # 關鍵字搜尋（數字時也搜 rowid）
    if q:
        like = f"%{q}%"
        if q.isdigit():
            base_sql += """
              AND (
                rowid = ?
                OR order_id LIKE ?
                OR customer_name LIKE ?
                OR contact_name LIKE ?
                OR contact_phone LIKE ?
                OR company LIKE ?
                OR product LIKE ?
                OR note LIKE ?
              )
            """
            params += [int(q), like, like, like, like, like, like, like]
        else:
            base_sql += """
              AND (
                order_id LIKE ?
                OR customer_name LIKE ?
                OR contact_name LIKE ?
                OR contact_phone LIKE ?
                OR company LIKE ?
                OR product LIKE ?
                OR note LIKE ?
              )
            """
            params += [like, like, like, like, like, like, like]

    # 製程步驟篩選
    if step:
        base_sql += " AND step_name = ?"
        params.append(step)

    base_sql += " ORDER BY date DESC"

    cur.execute(base_sql, params)
    orders = cur.fetchall()

    # 下拉選單用：取得所有不同的製程路徑
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
        tab=tab,
        source=source,
        steps=steps,
    )


# =============================================================
# 單筆訂單詳細資料
# =============================================================

@manager_bp.route("/orders/<order_id>", methods=["GET"])
@manager_required
def manager_order_detail(order_id):
    """
    顯示單筆訂單的詳細資訊頁面。
    """
    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)
    cur  = conn.cursor()

    cur.execute(
        """
        SELECT
            rowid AS id,
            order_id, date, customer_name, product, amount, total_price,
            step_name, note, status, rejected_at, cancelled_at,
            contact_name, contact_phone, company, address, source, mes_ono
        FROM order_list
        WHERE order_id = ?
        """,
        (order_id,),
    )
    order = cur.fetchone()
    conn.close()

    return render_template("manager/order_detail.html", order=order)


# =============================================================
# 拒絕訂單（保留紀錄）
# =============================================================

@manager_bp.route("/orders/<order_id>/delete", methods=["POST"])
@manager_required
def manager_order_delete(order_id):
    """
    管理者拒絕訂單（非物理刪除，保留紀錄）。
    拒絕後 status 改為 rejected，rejected_at 記錄時間。
    
    限制：
      - 必須填寫拒絕原因
      - 已取消（cancelled）的訂單不能再拒絕
      - 已完成（completed）的訂單不能再拒絕
      - 已拒絕（rejected）的訂單不能重複拒絕
    """
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("❌ 請選擇拒絕原因", "danger")
        return redirect(url_for("manager.manager_orders"))

    # 保留搜尋條件（讓拒絕後回到同一個篩選狀態）
    q             = (request.form.get("q") or "").strip()
    step          = (request.form.get("step") or "").strip()
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
    cur  = conn.cursor()

    # 查詢訂單目前狀態
    cur.execute("SELECT status FROM order_list WHERE order_id = ?", (order_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        flash("找不到該訂單", "danger")
        return redirect(url_for("manager.manager_orders", **kwargs))

    status = row["status"] or "active"

    # 狀態驗證
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

    # 更新訂單狀態為 rejected
    note_text = f"你的訂單已被工廠拒絕：{reason}"
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
