# =============================================================
# core/order_routes.py
# 訂單相關路由模組
# ----------------------------------------------------------
# Blueprint 名稱：order
# 路由清單：
#   GET/POST /order                    → 下單頁（選產品數量）
#   GET/POST /process-plan             → 製程規劃頁（選製程步驟）
#   POST     /api/submit_order         → 送出訂單 API（寫入 DB + 扣原料庫存）
#   POST     /api/pay_order/<order_id> → 結帳付款 API（改訂單狀態為 active）
#   GET      /orders                   → 使用者訂單紀錄頁
#   POST     /orders/<order_id>/cancel → 取消自己的訂單
#   GET      /trace/<order_id>         → 生產履歷與產品追溯頁
# =============================================================

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    jsonify,
    flash,
    abort,
)
from datetime import datetime, timedelta
import time
import sqlite3

from . import login_required
from .db import get_product_db, get_order_mgmt_db

order_bp = Blueprint("order", __name__)


# =============================================================
# 資料庫 Schema 自動遷移
# =============================================================

def ensure_order_list_schema(conn):
    """
    確保 order_list 資料表有所有必要欄位。
    若欄位不存在則自動新增（ALTER TABLE）。
    這樣舊資料庫不需要手動補欄位，程式啟動時自動處理。

    檢查欄位：
      - status           : 訂單狀態（active/pending_payment/cancelled/rejected/completed）
      - rejected_at      : 被拒絕的時間戳
      - cancelled_at     : 被取消的時間戳
      - estimated_delivery: 預估交期
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

        if "estimated_delivery" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN estimated_delivery TEXT")
            changed = True

        if changed:
            conn.commit()
    except Exception:
        # 不讓 migration 錯誤影響頁面（例如資料表不存在的狀況）
        pass


# =============================================================
# 下單頁
# =============================================================

@order_bp.route("/order", methods=["GET", "POST"])
@login_required
def order_page():
    """
    下單頁。
    - GET : 顯示產品清單與數量輸入欄
    - POST: 驗證數量後，將選購商品暫存到 session，導向製程規劃頁

    庫存驗證流程：
      1. 數量必須是正整數
      2. 數量不可超過庫存
      3. 至少要選一樣產品
    """
    # 不管 GET/POST 都先把產品列表抓出來
    conn = get_product_db()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT id, name, description, base_price, stock
        FROM products
        ORDER BY id
        """
    )
    rows = cur.fetchall()
    conn.close()

    # 轉成字典列表，給模板使用
    products = [
        {
            "id":          row["id"],
            "name":        row["name"],
            "description": row["description"],
            "base_price":  row["base_price"],
            "stock":       row["stock"],
        }
        for row in rows
    ]

    error_message = None

    if request.method == "POST":
        selected_items = []

        for p in products:
            field_name = f"qty_{p['id']}"
            qty_str    = request.form.get(field_name, "").strip()

            # 略過空欄位和數量為 0 的產品
            if qty_str == "" or qty_str == "0":
                continue

            # 驗證數量格式
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
                        "id":       p["id"],
                        "name":     p["name"],
                        "quantity": qty,
                    }
                )

        if not error_message:
            if not selected_items:
                error_message = "請至少選擇一項產品。"
            else:
                # 將本次選購的商品暫存到 session，供製程規劃頁使用
                session["current_order_items"] = selected_items
                return redirect(url_for("order.process_plan"))

    return render_template(
        "order/order_page.html",
        products=products,
        error_message=error_message,
    )


# =============================================================
# 製程規劃頁
# =============================================================

@order_bp.route("/process-plan", methods=["GET", "POST"])
@login_required
def process_plan():
    """
    製程規劃頁。
    顯示可選的製程步驟，讓使用者決定此訂單要走哪些製程。
    - 從 product.db 的 standard_process 讀取所有製程步驟
    - 從 session["current_order_items"] 讀取本次訂單商品摘要
    - 若 session 沒資料（直接輸入網址），顯示 demo 訊息
    """
    # 從資料庫讀取製程步驟定義
    conn = get_product_db()
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT step_order, step_name, station, description, estimated_time_sec
        FROM standard_process
        ORDER BY step_order ASC
        """
    )
    rows = cur.fetchall()
    conn.close()

    # 轉成字典列表
    standard_steps = [
        {
            "step_order":         row["step_order"],
            "step_name":          row["step_name"],
            "station":            row["station"],
            "description":        row["description"],
            "estimated_time_sec": row["estimated_time_sec"],
        }
        for row in rows
    ]

    # 讀取 Session 中的訂單摘要（供頁面右側顯示）
    order_items_summary = session.get("current_order_items")
    if not order_items_summary:
        order_items_summary = [{"name": "(無訂單資料 - 僅供預覽)", "quantity": 0}]

    return render_template(
        "order/process_plan.html",
        standard_steps=standard_steps,
        order_items_summary=order_items_summary,
    )


# =============================================================
# 訂單 ID 產生器
# =============================================================

def generate_order_id(conn) -> str:
    """
    產生唯一的訂單 ID。
    格式：YYYYMMDDHHMM + 3 位流水號（24小時制）
    範例：202512170105001

    邏輯：
      1. 取得當前時間前綴（YYYYMMDDHHmm）
      2. 查詢資料庫中同前綴的最大流水號
      3. 新流水號 = 最大流水號 + 1（從 001 開始）
    """
    now         = datetime.now()
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
                new_seq  = last_seq + 1
            except Exception:
                new_seq = 1
        else:
            new_seq = 1
    except Exception:
        new_seq = 1

    return f"{time_prefix}{str(new_seq).zfill(3)}"


# =============================================================
# API：送出訂單（寫入資料庫）
# =============================================================

@order_bp.route("/api/submit_order", methods=["POST"])
@login_required
def submit_order_api():
    """
    送出訂單的 API。
    流程：
      1. 從 session 取得購物車商品
      2. 從 product.db 讀取 BOM，驗證原物料庫存是否足夠
      3. 扣除原物料庫存（原子操作，失敗就 rollback）
      4. 計算總價與預估交期（依製程秒數推算）
      5. 寫入 order_management.db 的 order_list（狀態：pending_payment）
      6. 嘗試同步寫入 FestoMES.accdb（失敗不影響主流程）
      7. 清空 session 購物車

    回傳 JSON：{ success: bool, message: str, redirect_url: str }
    """
    conn_order = None
    conn_prod  = None

    try:
        data               = request.get_json()
        selected_steps_ids = data.get("selected_steps", [])  # 使用者選的製程步驟 ID 列表

        # 確認購物車不為空
        cart_items = session.get("current_order_items")
        if not cart_items:
            return jsonify({"success": False, "message": "購物車逾時，請重新下單"}), 400

        customer_name = session.get("account", "Guest")

        conn_prod  = get_product_db()
        conn_order = get_order_mgmt_db()
        ensure_order_list_schema(conn_order)  # 自動補欄位

        cur_prod  = conn_prod.cursor()
        cur_order = conn_order.cursor()

        # ------
        # 步驟 1：計算總價 + 驗證/扣除 BOM 原物料庫存
        # ------
        total_price   = 0
        product_names = []

        for item in cart_items:
            # 確認產品存在
            cur_prod.execute(
                "SELECT name, base_price, stock FROM products WHERE id = ?",
                (item["id"],),
            )
            prod_row = cur_prod.fetchone()

            if not prod_row:
                raise Exception(f"找不到產品 ID: {item['id']}")

            # 查詢 BOM（物料清單），驗證每個原料庫存是否足夠
            cur_prod.execute(
                """
                SELECT rm.id, rm.name, rm.stock, b.quantity_required
                FROM bom b
                JOIN raw_materials rm ON b.material_id = rm.id
                WHERE b.product_id = ?
                """,
                (item["id"],),
            )
            bom_rows = cur_prod.fetchall()

            for rm in bom_rows:
                required = rm["quantity_required"] * item["quantity"]
                if rm["stock"] < required:
                    raise Exception(
                        f"原料 [{rm['name']}] 庫存不足 "
                        f"(需 {required}，剩餘 {rm['stock']})，"
                        f"無法生產產品 [{prod_row['name']}]"
                    )
                # 扣除原料庫存（尚未 commit，失敗可 rollback）
                cur_prod.execute(
                    "UPDATE raw_materials SET stock = stock - ? WHERE id = ?",
                    (required, rm["id"]),
                )

            price        = prod_row["base_price"] if prod_row["base_price"] is not None else 0
            total_price += price * item["quantity"]
            product_names.append(f"{prod_row['name']} x {item['quantity']}")

        product_str  = ", ".join(product_names)
        total_amount = sum(item["quantity"] for item in cart_items)

        # ------
        # 步驟 2：把製程步驟 ID 串接成字串（格式：1 -> 2 -> 3）
        # ------
        step_name_str = " -> ".join(map(str, selected_steps_ids))

        # ------
        # 步驟 3：計算預估交期（製程總秒數 × 總件數）
        # ------
        total_estimated_sec = 0
        for step_id in selected_steps_ids:
            cur_prod.execute(
                "SELECT estimated_time_sec FROM standard_process WHERE step_order=?",
                (step_id,),
            )
            r = cur_prod.fetchone()
            if r and r["estimated_time_sec"]:
                total_estimated_sec += int(r["estimated_time_sec"])

        total_manufacturing_sec  = total_estimated_sec * total_amount
        estimated_delivery_dt    = datetime.now() + timedelta(seconds=total_manufacturing_sec)
        estimated_delivery_str   = estimated_delivery_dt.strftime("%Y-%m-%d %H:%M:%S")

        # ------
        # 步驟 4：寫入訂單（狀態：pending_payment，等待付款）
        # ------
        order_date      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note            = "無備註"
        custom_order_id = generate_order_id(conn_order)

        cur_order.execute(
            """
            INSERT INTO order_list (
                order_id, date, customer_name, product,
                amount, total_price, step_name, note,
                status, estimated_delivery
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                custom_order_id,
                order_date,
                customer_name,
                product_str,
                total_amount,
                total_price,
                step_name_str,
                note,
                "pending_payment",    # 下單後需等待付款才進入工廠排程
                estimated_delivery_str,
            ),
        )

        conn_prod.commit()
        conn_order.commit()

        # ------
        # 步驟 5：同步寫入 FestoMES.accdb（失敗不中斷主流程）
        # ------
        try:
            from core.db import get_festo_db
            conn_festo  = get_festo_db()
            cur_festo   = conn_festo.cursor()

            # 取得目前 MAX ONo，新 ONo = MAX + 1
            cur_festo.execute("SELECT MAX(ONo) FROM tblOrder")
            max_row   = cur_festo.fetchone()
            max_ono   = max_row[0] if max_row and max_row[0] is not None else 0
            new_ono   = max_ono + 1

            # 寫入 tblOrder（State=1, Enabled=True）
            cur_festo.execute(
                """
                INSERT INTO tblOrder (ONo, PlanedStart, PlanedEnd, Start, End, CNo, State, Enabled, Release)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_ono, datetime.now(), estimated_delivery_dt, None, None, 1, 1, True, datetime.now()),
            )
            conn_festo.commit()
            conn_festo.close()
        except Exception as e:
            # Festo MES 連線失敗只印警告，不中斷下單流程
            print(f"Warning: Failed to sync order to FestoMES.accdb: {e}")

        # 清空購物車 session
        session.pop("current_order_items", None)

        return jsonify(
            {
                "success":      True,
                "message":      "下單成功，請進行付款！",
                "redirect_url": url_for("order.order_history", tab="pending_payment"),
            }
        )

    except Exception as e:
        # 任何錯誤都回滾，確保資料庫一致性
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


# =============================================================
# API：結帳付款（模擬付款）
# =============================================================

@order_bp.route("/api/pay_order/<order_id>", methods=["POST"])
@login_required
def pay_order_api(order_id):
    """
    模擬結帳付款。
    將訂單狀態從 pending_payment 改為 active，
    active 狀態的訂單才會進入工廠排程系統開始生產。
    
    條件：
      - 只能付款自己的訂單
      - 訂單狀態必須是 pending_payment
    """
    customer_name = session.get("account", "Guest")
    conn          = get_order_mgmt_db()
    cur           = conn.cursor()
    try:
        cur.execute(
            "UPDATE order_list SET status = 'active' "
            "WHERE order_id = ? AND customer_name = ? AND status = 'pending_payment'",
            (order_id, customer_name),
        )
        if cur.rowcount == 0:
            return jsonify({"success": False, "message": "訂單無法付款或不存在"}), 400
        conn.commit()
        return jsonify({"success": True, "message": "付款成功，訂單已送入工廠排程！"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()


# =============================================================
# 使用者訂單紀錄頁
# =============================================================

@order_bp.route("/orders", methods=["GET"])
@login_required
def order_history():
    """
    使用者查看自己的訂單紀錄。
    依照 session["account"] 篩選，只顯示自己的訂單，按時間倒序排列。
    """
    customer_name = session.get("account", "Guest")

    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)  # 確保欄位存在再查詢
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT
            order_id, date, customer_name, product, amount, total_price,
            step_name, note, status, rejected_at, cancelled_at, estimated_delivery
        FROM order_list
        WHERE customer_name = ?
        ORDER BY date DESC
        """,
        (customer_name,),
    )
    orders = cur.fetchall()
    conn.close()

    return render_template("order/orders_history.html", orders=orders)


# =============================================================
# 使用者取消訂單
# =============================================================

@order_bp.route("/orders/<order_id>/cancel", methods=["POST"])
@login_required
def cancel_my_order(order_id):
    """
    使用者取消自己的訂單。
    保留紀錄（不物理刪除），只改 status 為 cancelled。

    限制：
      - 只能取消自己的訂單（驗證 customer_name）
      - 已拒絕（rejected）或已取消（cancelled）的訂單不可再取消
      - 必須選擇取消原因（reason）

    取消原因會寫入 note 欄位，cancelled_at 記錄取消時間。
    """
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("請選擇取消原因", "danger")
        return redirect(url_for("order.order_history"))

    customer_name = session.get("account", "Guest")

    conn = get_order_mgmt_db()
    ensure_order_list_schema(conn)
    cur  = conn.cursor()

    # 查詢訂單是否存在
    cur.execute(
        "SELECT customer_name, status FROM order_list WHERE order_id = ?",
        (order_id,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        flash("找不到該訂單", "danger")
        return redirect(url_for("order.order_history"))

    # 權限驗證：只能取消自己的訂單
    if row["customer_name"] != customer_name:
        conn.close()
        abort(403)

    status = row["status"] or "active"

    # 狀態驗證：已拒絕/已取消的訂單不能再取消
    if status in ("rejected", "cancelled"):
        conn.close()
        flash("此訂單目前無法取消（可能已被拒絕或已取消）", "warning")
        return redirect(url_for("order.order_history"))

    note_text = f"客戶取消：{reason}"
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        UPDATE order_list
        SET status = 'cancelled',
            note = ?,
            cancelled_at = ?
        WHERE order_id = ? AND customer_name = ?
        """,
        (note_text, now_str, order_id, customer_name),
    )

    conn.commit()
    conn.close()

    flash("已取消訂單（已保留紀錄）", "success")
    return redirect(url_for("order.order_history"))


# =============================================================
# 生產履歷與產品追溯
# =============================================================

@order_bp.route("/trace/<order_id>", methods=["GET"])
@login_required
def order_trace(order_id):
    """
    生產履歷查詢（產品追溯）。
    顯示某訂單中每一件商品（piece）在每個製程步驟的
    開始時間、完成時間與加工機台。
    
    資料來源：
      - order_management.db：order_list、piece_step_progress
      - product.db：standard_process（取得步驟名稱和機台）
    
    只能查看自己的訂單（除非是 admin）。
    """
    customer_name = session.get("account", "Guest")
    conn_order    = get_order_mgmt_db()
    conn_prod     = get_product_db()

    try:
        cur = conn_order.cursor()
        cur.row_factory = sqlite3.Row

        # 驗證訂單存在且屬於自己
        order = cur.execute(
            "SELECT * FROM order_list WHERE order_id = ? AND customer_name = ?",
            (order_id, customer_name),
        ).fetchone()

        if not order:
            flash("找不到該訂單或無權限查看", "danger")
            return redirect(url_for("order.order_history"))

        # 解析製程步驟鏈（格式：1 -> 2 -> 3 → [1,2,3]）
        chain_strs = [x.strip() for x in (order["step_name"] or "").split("->") if x.strip()]
        steps_info = {}
        for s in chain_strs:
            try:
                sid = int(s)
                c   = conn_prod.cursor()
                c.row_factory = sqlite3.Row
                r = c.execute(
                    "SELECT step_name, station FROM standard_process WHERE step_order=?",
                    (sid,),
                ).fetchone()
                if r:
                    steps_info[sid] = dict(r)
            except Exception:
                pass

        # 讀取每件商品的製程進度（只取已完成的步驟）
        records = cur.execute(
            """
            SELECT piece_no, step_order, started_at, finished_at
            FROM piece_step_progress
            WHERE order_id = ? AND state = 'finished'
            ORDER BY piece_no ASC, step_order ASC
            """,
            (order_id,),
        ).fetchall()

        # 依件號（piece_no）分組整理
        pieces: dict = {}
        for row in records:
            pno = row["piece_no"]
            if pno not in pieces:
                pieces[pno] = []

            step_id = row["step_order"]
            info    = steps_info.get(step_id, {"step_name": f"Step {step_id}", "station": "未知機台"})

            pieces[pno].append(
                {
                    "step_order":  step_id,
                    "step_name":   info["step_name"],
                    "station":     info["station"],
                    "started_at":  row["started_at"],
                    "finished_at": row["finished_at"],
                }
            )

        return render_template("order/trace.html", order=order, pieces=pieces)

    finally:
        conn_order.close()
        conn_prod.close()
