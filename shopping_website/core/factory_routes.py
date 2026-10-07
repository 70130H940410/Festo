# =============================================================
# core/factory_routes.py
# 工廠模擬排程引擎路由模組
# ----------------------------------------------------------
# Blueprint 名稱：factory（前綴 /factory）
#
# 核心概念：
#   - 每張「訂單」有多個「件（piece）」，每件要依序通過多個「製程步驟（step）」
#   - 每個製程步驟綁定一個「機台（station）」
#   - 同一機台同時只能處理一件商品（並行：不同機台可同時工作）
#   - 背景執行緒每秒 tick 一次，推進所有 active 訂單的進度
#
# 路由清單：
#   GET  /factory/simulate           → 工廠模擬頁面（視覺化進度）
#   GET  /factory/api/order_status/<order_id> → 取得訂單製程進度（JSON）
#   GET/POST /factory/api/init/<order_id>     → 初始化訂單件數進度紀錄
#   GET/POST /factory/api/reset/<order_id>    → 重置訂單進度（開發用）
#   GET/POST /factory/api/tick                → 手動觸發一次排程推進
#   GET  /factory/api/debug/state             → 查看站點佔用狀態（開發用）
#   GET  /factory/mes_dashboard               → Festo MES 真實工廠戰情室
#   GET  /factory/api/mes_status              → 取得 MES 機台/訂單狀態
#   GET  /factory/api/mes_analytics           → 取得 MES 能源分析資料
#   GET  /factory/api/mes_alerts              → 取得 MES 機台警報
#   POST /factory/api/trigger_mes_error       → 觸發 MES 機台錯誤（測試用）
#   GET  /factory/api/buffer_status           → 取得倉儲 Buffer Pose 1~32 狀態
# =============================================================

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from flask import Blueprint, render_template, session, current_app, request, abort, jsonify

from . import login_required

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")

# -------------------------
# 常數設定
# -------------------------
_ORDER_DB_FILENAME  = "order_management.db"  # 訂單/站點資料庫
_PRODUCT_DB_FILENAME = "product.db"          # 製程步驟資料庫
_COMPLETE_STATUS    = "completed"             # 訂單完成狀態字串


# =============================================================
# 內部 Helper 函式
# =============================================================

def _db_path(filename: str) -> str:
    """回傳 database/ 目錄下指定檔名的絕對路徑（依賴 Flask app context）"""
    return os.path.join(current_app.root_path, "database", filename)


def _conn(path: str) -> sqlite3.Connection:
    """建立 SQLite 連線，啟用 Row 工廠"""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _now() -> datetime:
    """取得當前時間（封裝方便單元測試時 mock）"""
    return datetime.now()


def _fmt(dt: datetime) -> str:
    """將 datetime 物件格式化為 SQLite 儲存格式"""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_step_chain(s: str) -> List[int]:
    """
    解析製程步驟鏈字串為整數列表。
    輸入格式：'1 -> 2 -> 3'
    輸出：[1, 2, 3]
    """
    if not s:
        return []
    out: List[int] = []
    for part in s.split("->"):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


# =============================================================
# 資料庫初始化與 Schema 遷移
# =============================================================

def _ensure_tables(order_db: sqlite3.Connection) -> None:
    """
    確保 order_management.db 有必要的資料表和欄位。
    
    建立資料表（若不存在）：
      - piece_step_progress：記錄每件商品在每個製程步驟的狀態
          欄位：order_id, piece_no, step_order, state(pending/running/finished/error),
                started_at, finished_at
          主鍵：(order_id, piece_no, step_order)
      - station_state：記錄每個機台的當前佔用狀態
          欄位：station, current_order_id, current_step_order,
                busy_until, updated_at
    
    自動補齊缺失欄位（舊資料庫相容）：
      - current_piece_no、current_step_order、busy_until、updated_at
    """
    # 建立 piece_step_progress 資料表
    order_db.execute("""
        CREATE TABLE IF NOT EXISTS piece_step_progress (
          order_id TEXT NOT NULL,
          piece_no INTEGER NOT NULL,
          step_order INTEGER NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', -- pending/running/finished/error
          started_at TEXT,
          finished_at TEXT,
          PRIMARY KEY(order_id, piece_no, step_order)
        );
    """)

    # 建立 station_state 資料表
    order_db.execute("""
        CREATE TABLE IF NOT EXISTS station_state (
          station TEXT PRIMARY KEY,
          current_order_id TEXT,
          current_step_order INTEGER,
          busy_until TEXT,
          updated_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # 自動補齊 station_state 缺失的欄位（舊版資料庫相容）
    cols = {r["name"] for r in order_db.execute("PRAGMA table_info(station_state)").fetchall()}

    def add_col(sql: str):
        try:
            order_db.execute(sql)
        except sqlite3.OperationalError:
            pass  # 欄位已存在，忽略

    if "current_piece_no" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN current_piece_no INTEGER;")
    if "current_step_order" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN current_step_order INTEGER;")
    if "busy_until" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN busy_until TEXT;")
    if "updated_at" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN updated_at TEXT;")

    order_db.commit()


def _ensure_station_rows(order_db: sqlite3.Connection, product_db: sqlite3.Connection) -> None:
    """
    確保 station_state 資料表中有所有機台的初始列。
    從 product.db 的 standard_process 讀取不重複的 station 名稱，
    INSERT OR IGNORE 進 station_state。
    """
    rows = product_db.execute("""
        SELECT DISTINCT station
        FROM standard_process
        WHERE station IS NOT NULL AND TRIM(station) <> ''
        ORDER BY station
    """).fetchall()
    for r in rows:
        order_db.execute(
            "INSERT OR IGNORE INTO station_state(station) VALUES (?)",
            (r["station"],),
        )
    order_db.commit()


def _ensure_piece_rows(
    order_db: sqlite3.Connection, order_id: str, chain: List[int], amount: int
) -> None:
    """
    確保 piece_step_progress 有此訂單所有件數 × 步驟的初始列。
    INSERT OR IGNORE：若已存在則不覆蓋（保留現有進度）。
    """
    amount = max(1, int(amount or 1))
    for piece_no in range(1, amount + 1):
        for step_no in chain:
            order_db.execute(
                """
                INSERT OR IGNORE INTO piece_step_progress(order_id, piece_no, step_order, state)
                VALUES (?, ?, ?, 'pending')
                """,
                (order_id, piece_no, step_no),
            )
    order_db.commit()


# =============================================================
# 查詢 Helper 函式
# =============================================================

def _get_est_sec(product_db: sqlite3.Connection, step_order: int) -> int:
    """從 standard_process 讀取指定步驟的預計加工秒數，找不到時預設 5 秒"""
    r = product_db.execute(
        "SELECT estimated_time_sec FROM standard_process WHERE step_order=?",
        (step_order,),
    ).fetchone()
    if not r:
        return 5
    try:
        return int(r["estimated_time_sec"] or 5)
    except Exception:
        return 5


def _get_step_station_map(product_db: sqlite3.Connection) -> Dict[int, str]:
    """
    回傳 {step_order: station} 的映射字典。
    例：{1: 'StationA', 2: 'StationB', 3: 'StationA'}
    """
    rows = product_db.execute(
        "SELECT step_order, station FROM standard_process"
    ).fetchall()
    mp: Dict[int, str] = {}
    for r in rows:
        mp[int(r["step_order"])] = (r["station"] or "").strip()
    return mp


def _get_step_defs(product_db: sqlite3.Connection, chain: List[int]) -> List[dict]:
    """
    從 product.db 讀取指定步驟鏈的製程步驟定義。
    回傳的順序與 chain 一致（依 chain 的順序排列，非資料庫原始順序）。
    """
    placeholders = ",".join(["?"] * len(chain))
    rows = product_db.execute(
        f"""
        SELECT step_order, step_name, station, description, estimated_time_sec
        FROM standard_process
        WHERE step_order IN ({placeholders})
        """,
        chain,
    ).fetchall()

    by_no = {int(r["step_order"]): dict(r) for r in rows}
    return [by_no[n] for n in chain if n in by_no]


def _piece_is_running(order_db: sqlite3.Connection, order_id: str, piece_no: int) -> bool:
    """檢查指定件是否有任何步驟正在執行中（state='running'）"""
    r = order_db.execute(
        """
        SELECT 1 FROM piece_step_progress
        WHERE order_id=? AND piece_no=? AND state='running'
        LIMIT 1
        """,
        (order_id, piece_no),
    ).fetchone()
    return r is not None


def _prev_step(chain: List[int], step_no: int) -> Optional[int]:
    """
    回傳製程鏈中 step_no 的前一個步驟編號。
    若 step_no 是第一步，回傳 None。
    若 step_no 不在 chain 中，也回傳 None。
    """
    if step_no not in chain:
        return None
    idx = chain.index(step_no)
    if idx == 0:
        return None
    return chain[idx - 1]


def _is_order_completed(
    order_db: sqlite3.Connection, order_id: str, last_step: int, amount: int
) -> bool:
    """
    判斷整張訂單是否已完成。
    條件：最後一個步驟（last_step）的已完成件數 >= 訂單總件數（amount）
    """
    r = order_db.execute(
        """
        SELECT COUNT(*) AS c
        FROM piece_step_progress
        WHERE order_id=? AND step_order=? AND state='finished'
        """,
        (order_id, last_step),
    ).fetchone()
    return int(r["c"] or 0) >= max(1, int(amount or 1))


# =============================================================
# 排程核心：完成到點的工作 + 派工
# =============================================================

def _complete_due_jobs(order_db: sqlite3.Connection) -> int:
    """
    掃描所有佔用機台，把已到 busy_until 的工作標記為 finished。
    同時釋放機台（station_state 清空）。
    
    特殊處理：若機台 is_error=1（故障中），自動延長 busy_until +1秒，
    讓它持續被占用而無法完成，達到「凍結」效果。
    
    回傳：本次完成的工作數量。
    """
    now             = _now()
    completed_count = 0

    running_stations = order_db.execute("""
        SELECT station, current_order_id, current_piece_no, current_step_order, busy_until,
               IFNULL(is_error, 0) as is_error
        FROM station_state
        WHERE current_order_id IS NOT NULL
    """).fetchall()

    for ss in running_stations:
        if ss["is_error"] == 1:
            # 故障機台：持續延長 busy_until，使其無法觸發完成條件
            order_db.execute(
                "UPDATE station_state SET busy_until = datetime(busy_until, '+1 second') WHERE station = ?",
                (ss["station"],),
            )
            continue

        try:
            end_dt = datetime.fromisoformat(str(ss["busy_until"]))
        except Exception:
            continue

        # 時間未到，跳過
        if now < end_dt:
            continue

        order_id = str(ss["current_order_id"])
        piece_no = int(ss["current_piece_no"])
        step_no  = int(ss["current_step_order"])

        # 將 piece_step_progress 中的對應列改為 finished
        order_db.execute(
            """
            UPDATE piece_step_progress
            SET state='finished', finished_at=?
            WHERE order_id=? AND piece_no=? AND step_order=? AND state='running'
            """,
            (_fmt(now), order_id, piece_no, step_no),
        )

        # 釋放機台
        order_db.execute(
            """
            UPDATE station_state
            SET current_order_id=NULL, current_piece_no=NULL,
                current_step_order=NULL, busy_until=NULL, updated_at=?
            WHERE station=?
            """,
            (_fmt(now), ss["station"]),
        )
        completed_count += 1

    order_db.commit()
    return completed_count


def _dispatch_for_focus_order(
    order_db: sqlite3.Connection,
    product_db: sqlite3.Connection,
    focus_order_id: str,
) -> List[dict]:
    """
    針對指定訂單（focus_order_id）進行派工。
    
    派工邏輯（貪婪演算法）：
      1. 取得所有空閒且未故障的機台
      2. 對每台機台，找出該機台負責的步驟中有沒有可以開始的工作：
         - 工作狀態：pending（等待中）
         - 同一件不能同時在兩個步驟執行
         - 前一個步驟必須是 finished（流水線約束）
      3. 若找到工作：
         - 更新 piece_step_progress：pending → running
         - 更新 station_state：佔用機台 + 設定 busy_until = now + 加工秒數
    
    回傳：本次派工的工作列表（每個元素包含 station、order_id、piece_no 等）。
    """
    now          = _now()
    step_station = _get_step_station_map(product_db)

    # 建立 station → [步驟編號列表] 的映射
    station_steps: Dict[str, List[int]] = {}
    for step_no, st in step_station.items():
        if not st:
            continue
        station_steps.setdefault(st, []).append(step_no)
    for st in station_steps:
        station_steps[st].sort()

    # 讀取目標訂單（只處理 status='active' 的訂單）
    o = order_db.execute(
        """
        SELECT order_id, step_name, amount, status
        FROM order_list
        WHERE status='active' AND order_id=?
        LIMIT 1
        """,
        (focus_order_id,),
    ).fetchone()
    if not o:
        return []

    chain = _parse_step_chain(o["step_name"] or "")
    if not chain:
        return []

    try:
        amount = max(1, int(o["amount"] or 1))
    except Exception:
        amount = 1

    # 確保 piece_step_progress 有此訂單的初始列
    _ensure_piece_rows(order_db, focus_order_id, chain, amount)

    # 取得所有空閒且未故障的機台
    idle = order_db.execute(
        """
        SELECT station
        FROM station_state
        WHERE current_order_id IS NULL AND IFNULL(is_error, 0) = 0
        ORDER BY station
        """
    ).fetchall()

    dispatched: List[dict] = []

    for st_row in idle:
        station   = str(st_row["station"])
        step_list = station_steps.get(station, [])
        if not step_list:
            continue

        best_job = None  # (piece_no, step_no, est_sec)

        for step_no in step_list:
            if step_no not in chain:
                continue
            prev = _prev_step(chain, step_no)

            # 找出此步驟中還在等待的件（取 piece_no 最小的先派）
            cand = order_db.execute(
                """
                SELECT piece_no
                FROM piece_step_progress
                WHERE order_id=? AND step_order=? AND state='pending'
                ORDER BY piece_no ASC
                """,
                (focus_order_id, step_no),
            ).fetchall()

            for r in cand:
                piece_no = int(r["piece_no"])

                # 同一件不允許同時跑兩個步驟
                if _piece_is_running(order_db, focus_order_id, piece_no):
                    continue

                # 流水線約束：前一步必須已完成（第一步除外）
                if prev is None:
                    ok = True
                else:
                    pr = order_db.execute(
                        """
                        SELECT state FROM piece_step_progress
                        WHERE order_id=? AND piece_no=? AND step_order=?
                        """,
                        (focus_order_id, piece_no, prev),
                    ).fetchone()
                    ok = pr is not None and pr["state"] == "finished"

                if not ok:
                    continue

                est       = _get_est_sec(product_db, step_no)
                best_job  = (piece_no, step_no, est)
                break  # 找到第一個可派的件就停止（貪婪）

            if best_job:
                break  # 這台機台已找到工作，不再找其他步驟

        if not best_job:
            continue  # 這台機台找不到可派的工作

        piece_no, step_no, est = best_job

        # 更新進度：pending → running
        order_db.execute(
            """
            UPDATE piece_step_progress
            SET state='running', started_at=COALESCE(started_at, ?)
            WHERE order_id=? AND piece_no=? AND step_order=? AND state='pending'
            """,
            (_fmt(now), focus_order_id, piece_no, step_no),
        )

        end_time = now + timedelta(seconds=int(est))

        # 佔用機台
        order_db.execute(
            """
            UPDATE station_state
            SET current_order_id=?, current_piece_no=?, current_step_order=?,
                busy_until=?, updated_at=?
            WHERE station=?
            """,
            (focus_order_id, piece_no, step_no, end_time.isoformat(sep=" "), _fmt(now), station),
        )
        order_db.commit()

        dispatched.append(
            {
                "station":    station,
                "order_id":   focus_order_id,
                "piece_no":   piece_no,
                "step_order": step_no,
                "busy_until": end_time.isoformat(sep=" "),
            }
        )

    return dispatched


def _tick_once_for_order(
    order_db: sqlite3.Connection,
    product_db: sqlite3.Connection,
    focus_order_id: str,
) -> List[dict]:
    """
    針對指定訂單執行一次 tick（排程推進）：
      步驟 1：呼叫 _complete_due_jobs（完成所有到點的工作）
      步驟 2：呼叫 _dispatch_for_focus_order（為空閒機台派新工作）
      步驟 3：檢查訂單是否全部完成，若是則更新 status=completed
      步驟 4：若有變動，透過 SSE 廣播通知前端更新畫面
    
    回傳：本次派工的工作列表。
    """
    # 步驟 1：完成到點的工作
    completed_count = _complete_due_jobs(order_db)

    # 步驟 2：派工
    dispatched = _dispatch_for_focus_order(order_db, product_db, focus_order_id)

    # 步驟 3：檢查整張訂單是否完成
    o = order_db.execute(
        "SELECT step_name, amount, mes_ono, supabase_order_id, source FROM order_list WHERE order_id=?",
        (focus_order_id,),
    ).fetchone()
    if o:
        chain = _parse_step_chain(o["step_name"] or "")
        if chain:
            try:
                amount = max(1, int(o["amount"] or 1))
            except Exception:
                amount = 1
            if _is_order_completed(order_db, focus_order_id, chain[-1], amount):
                order_db.execute(
                    "UPDATE order_list SET status=? WHERE order_id=?",
                    (_COMPLETE_STATUS, focus_order_id),
                )
                order_db.commit()

                # 同步回寫雲端 Supabase (tbl_order 與 line_orders)
                try:
                    from core.db import get_supabase_client
                    from datetime import datetime
                    sb = get_supabase_client()
                    if sb:
                        now_iso = datetime.now().isoformat()
                        mes_ono = o["mes_ono"]
                        sb_order_id = o["supabase_order_id"]
                        if mes_ono:
                            sb.table("tbl_order").update({
                                "state": 3,
                                "end": now_iso,
                            }).eq("ono", mes_ono).execute()
                            print(f"🏁 [MES Complete] 工單 ONo: {mes_ono} (訂單: {focus_order_id}) 已在 MES 標記為完工！")

                        if sb_order_id:
                            sb.table("line_orders").update({
                                "status": "Completed"
                            }).eq("id", sb_order_id).execute()
                            print(f"🎉 [LINE Order Complete] Supabase 訂單 #{sb_order_id} 狀態已同步為 Completed！")
                except Exception as e:
                    print(f"⚠️ [Order Complete Sync Warning] {e}")

    # 步驟 4：SSE 廣播（有變動才廣播）
    if completed_count > 0 or len(dispatched) > 0:
        from core.sse import sse_manager
        import json
        sse_manager.announce(json.dumps({"order_id": focus_order_id}))

    return dispatched


# =============================================================
# 頁面路由：工廠模擬視覺化
# =============================================================

@factory_bp.route("/simulate")
@login_required
def simulate():
    """
    工廠模擬頁面。
    URL 參數：?order_id=訂單ID
    
    功能：
      1. 讀取訂單資料（步驟鏈、件數、狀態）
      2. 確保資料表和機台列存在
      3. 確保件數進度初始化
      4. 自動執行一次 tick（讓頁面載入時就能看到進度）
      5. 讀取每個步驟的完成件數/執行中件數，計算顯示狀態
    
    非 admin 使用者只能看自己的訂單。
    """
    order_id = request.args.get("order_id")
    if not order_id:
        abort(400, "need ?order_id=...")

    order_db   = _conn(_db_path(_ORDER_DB_FILENAME))
    product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        _ensure_station_rows(order_db, product_db)

        o = order_db.execute(
            """
            SELECT order_id, customer_name, step_name, note, status, amount
            FROM order_list
            WHERE order_id=?
            """,
            (order_id,),
        ).fetchone()
        if not o:
            abort(404, "order not found")

        # 權限控管：非 admin 只能看自己的訂單
        if session.get("role") != "admin":
            me = session.get("account") or session.get("username") or session.get("full_name")
            if (not me) or ((o["customer_name"] or "") != me):
                abort(403)

        chain = _parse_step_chain(o["step_name"] or "")
        if not chain:
            abort(400, "this order has empty step_name (step chain)")

        try:
            amount = max(1, int(o["amount"] or 1))
        except Exception:
            amount = 1

        # 初始化件數進度
        _ensure_piece_rows(order_db, order_id, chain, amount)

        # 頁面載入時自動執行一次 tick（保證 Step1 會立刻開始）
        _tick_once_for_order(order_db, product_db, order_id)

        # 讀取製程步驟定義
        steps = _get_step_defs(product_db, chain)

        # 聚合每個步驟的完成/執行件數，用於顯示進度
        agg: Dict[int, Dict[str, int]] = {}
        for step_no in chain:
            done = order_db.execute(
                """
                SELECT COUNT(*) AS c FROM piece_step_progress
                WHERE order_id=? AND step_order=? AND state='finished'
                """,
                (order_id, step_no),
            ).fetchone()["c"]

            running = order_db.execute(
                """
                SELECT COUNT(*) AS c FROM piece_step_progress
                WHERE order_id=? AND step_order=? AND state='running'
                """,
                (order_id, step_no),
            ).fetchone()["c"]

            agg[step_no] = {"done": int(done or 0), "running": int(running or 0)}

        # 為每個步驟加上狀態（finished / running / pending）
        for s in steps:
            step_no   = int(s["step_order"])
            done_qty  = agg.get(step_no, {}).get("done", 0)
            running_qty = agg.get(step_no, {}).get("running", 0)

            s["done_qty"]  = done_qty
            s["total_qty"] = amount

            if done_qty >= amount:
                s["state"] = "finished"
            elif running_qty > 0:
                s["state"] = "running"
            else:
                s["state"] = "pending"

        order_info = {
            "order_id":  o["order_id"],
            "user_name": o["customer_name"] or session.get("account") or "Demo User",
            "note":      o["note"] or "無備註",
            "status":    (o["status"] or "").lower(),
            "amount":    amount,
        }

        return render_template("factory/simulate.html", order_info=order_info, steps=steps)

    finally:
        order_db.close()
        product_db.close()


# =============================================================
# API：取得訂單製程進度（供 SSE 動態更新）
# =============================================================

@factory_bp.route("/api/order_status/<order_id>", methods=["GET"])
@login_required
def api_order_status(order_id: str):
    """
    取得指定訂單各製程步驟的即時進度。
    回傳 JSON 包含：
      - order_info: { order_id, status }
      - steps: 每個步驟的 { done_qty, total_qty, state(finished/error/running/pending) }
    
    狀態優先序：finished > error > running > pending
    """
    order_db   = _conn(_db_path(_ORDER_DB_FILENAME))
    product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
    try:
        o = order_db.execute(
            """
            SELECT order_id, customer_name, step_name, note, status, amount
            FROM order_list WHERE order_id=?
            """,
            (order_id,),
        ).fetchone()
        if not o:
            abort(404, "order not found")

        chain = _parse_step_chain(o["step_name"] or "")
        try:
            amount = max(1, int(o["amount"] or 1))
        except Exception:
            amount = 1

        steps = _get_step_defs(product_db, chain)
        agg: Dict[int, Dict[str, int]] = {}

        for step_no in chain:
            done    = order_db.execute(
                "SELECT COUNT(*) AS c FROM piece_step_progress WHERE order_id=? AND step_order=? AND state='finished'",
                (order_id, step_no),
            ).fetchone()["c"]
            running = order_db.execute(
                "SELECT COUNT(*) AS c FROM piece_step_progress WHERE order_id=? AND step_order=? AND state='running'",
                (order_id, step_no),
            ).fetchone()["c"]

            # 檢查此步驟的機台是否處於故障狀態
            err_c = 0
            try:
                err_c = order_db.execute(
                    "SELECT COUNT(*) AS c FROM station_state WHERE current_order_id=? AND current_step_order=? AND IFNULL(is_error,0)=1",
                    (order_id, step_no),
                ).fetchone()["c"]
            except Exception:
                pass

            agg[step_no] = {
                "done":    int(done or 0),
                "running": int(running or 0),
                "error":   int(err_c or 0),
            }

        for s in steps:
            step_no    = int(s["step_order"])
            done_qty   = agg.get(step_no, {}).get("done", 0)
            running_qty = agg.get(step_no, {}).get("running", 0)
            error_qty  = agg.get(step_no, {}).get("error", 0)

            s["done_qty"]  = done_qty
            s["total_qty"] = amount

            if done_qty >= amount:
                s["state"] = "finished"
            elif error_qty > 0:
                s["state"] = "error"
            elif running_qty > 0:
                s["state"] = "running"
            else:
                s["state"] = "pending"

        order_info = {
            "order_id": o["order_id"],
            "status":   (o["status"] or "").lower(),
        }
        return jsonify({"order_info": order_info, "steps": steps})
    finally:
        order_db.close()
        product_db.close()


# =============================================================
# API：初始化 / 重置 / 手動 Tick
# =============================================================

@factory_bp.route("/api/init/<order_id>", methods=["GET", "POST"])
@login_required
def api_init(order_id: str):
    """
    初始化指定訂單的件數進度記錄（piece_step_progress）。
    呼叫後，piece_step_progress 會有此訂單所有件數 × 步驟的 pending 記錄。
    回傳訂單資訊：{ ok, order_id, amount, steps }
    """
    order_db   = _conn(_db_path(_ORDER_DB_FILENAME))
    product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        _ensure_station_rows(order_db, product_db)

        o = order_db.execute(
            "SELECT order_id, step_name, amount FROM order_list WHERE order_id=?",
            (order_id,),
        ).fetchone()
        if not o:
            abort(404, "order not found")

        chain = _parse_step_chain(o["step_name"] or "")
        if not chain:
            abort(400, "empty step chain")

        try:
            amount = max(1, int(o["amount"] or 1))
        except Exception:
            amount = 1

        _ensure_piece_rows(order_db, order_id, chain, amount)
        return jsonify({"ok": True, "order_id": order_id, "amount": amount, "steps": chain})

    finally:
        order_db.close()
        product_db.close()


@factory_bp.route("/api/reset/<order_id>", methods=["GET", "POST"])
@login_required
def api_reset(order_id: str):
    """
    重置指定訂單的所有進度（刪除 piece_step_progress，釋放機台）。
    主要用於開發測試，不建議在正式環境使用。
    """
    order_db = _conn(_db_path(_ORDER_DB_FILENAME))
    try:
        _ensure_tables(order_db)

        # 釋放佔用此訂單的機台
        order_db.execute(
            """
            UPDATE station_state
            SET current_order_id=NULL, current_piece_no=NULL,
                current_step_order=NULL, busy_until=NULL, updated_at=?
            WHERE current_order_id=?
            """,
            (_fmt(_now()), order_id),
        )

        # 刪除所有件數進度記錄
        order_db.execute(
            "DELETE FROM piece_step_progress WHERE order_id=?",
            (order_id,),
        )
        order_db.commit()

        return jsonify({"ok": True, "order_id": order_id})

    finally:
        order_db.close()


@factory_bp.route("/api/tick", methods=["GET", "POST"])
@login_required
def api_tick():
    """
    手動觸發一次排程推進。
    用法：
      /factory/api/tick?order_id=xxx → 只推進指定訂單（simulate 頁面使用）
      /factory/api/tick              → 只完成到點的工作，不主動派工（預防多單混淆）
    """
    focus_order_id = request.args.get("order_id")

    order_db   = _conn(_db_path(_ORDER_DB_FILENAME))
    product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        _ensure_station_rows(order_db, product_db)

        if not focus_order_id:
            # 沒指定訂單：只完成到點工作，不派新工
            _complete_due_jobs(order_db)
            return jsonify({"ok": True, "dispatched": [], "msg": "need ?order_id=... to dispatch"})

        dispatched = _tick_once_for_order(order_db, product_db, focus_order_id)
        return jsonify({"ok": True, "order_id": focus_order_id, "dispatched": dispatched})

    finally:
        order_db.close()
        product_db.close()


@factory_bp.route("/api/debug/state", methods=["GET"])
@login_required
def api_debug_state():
    """
    開發用：查看所有機台的佔用狀態和執行中的工作。
    回傳 JSON 包含：
      - stations : 所有機台的當前狀態
      - running  : 所有 state='running' 的件步驟進度
    """
    order_db = _conn(_db_path(_ORDER_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        stations = [
            dict(r)
            for r in order_db.execute(
                """
                SELECT station, current_order_id, current_piece_no, current_step_order, busy_until
                FROM station_state ORDER BY station
                """
            ).fetchall()
        ]
        running = [
            dict(r)
            for r in order_db.execute(
                """
                SELECT order_id, piece_no, step_order, state
                FROM piece_step_progress
                WHERE state='running'
                ORDER BY order_id, piece_no, step_order
                """
            ).fetchall()
        ]
        return jsonify({"stations": stations, "running": running})
    finally:
        order_db.close()


# =============================================================
# 背景執行緒函式：推進所有 active 訂單
# =============================================================

def _tick_all_active_orders(app) -> None:
    """
    背景執行緒專用函式（由 app.py 的 background_factory_worker 每秒呼叫）。
    在 Flask app_context 中執行，尋找所有 status='active' 的訂單並推進進度。
    """
    with app.app_context():
        order_db   = _conn(_db_path(_ORDER_DB_FILENAME))
        product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
        try:
            _ensure_tables(order_db)
            _ensure_station_rows(order_db, product_db)

            # 先完成所有到點的工作
            _complete_due_jobs(order_db)

            # 找出所有進行中訂單，逐一確保已初始化步驟並推進
            active_orders = order_db.execute(
                "SELECT order_id, step_name, amount FROM order_list WHERE status='active'"
            ).fetchall()
            for row in active_orders:
                order_id = row["order_id"]
                step_name = row["step_name"] or "1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9"
                chain = _parse_step_chain(step_name)
                try:
                    amount = max(1, int(row["amount"] or 1))
                except Exception:
                    amount = 1
                if chain:
                    _ensure_piece_rows(order_db, order_id, chain, amount)
                _tick_once_for_order(order_db, product_db, order_id)
        except Exception as e:
            print(f"[Factory Scheduler Error] {e}")
        finally:
            order_db.close()
            product_db.close()


# =============================================================
# Festo MES 真實工廠戰情室（僅 admin 可存取）
# =============================================================

@factory_bp.route("/mes_dashboard")
@login_required
def mes_dashboard():
    """
    Festo MES 真實工廠戰情室頁面。
    連接真實的 FestoMES.accdb，顯示真實機台狀態與訂單。
    僅 admin 可存取。
    """
    if session.get("role") != "admin":
        abort(403)
    return render_template("factory/mes_dashboard.html")


@factory_bp.route("/api/mes_status", methods=["GET"])
@login_required
def api_mes_status():
    """
    取得 Festo MES 真實工廠狀態（JSON）。
    資料來源：FestoMES.accdb 或 Supabase
    """
    if session.get("role") != "admin":
        abort(403)

    from .mes_data_service import MesDataService
    import datetime

    try:
        raw_machines = MesDataService.get_machine_status()

        machines = []
        for m in raw_machines:
            machines.append(
                {
                    "ResourceID":    m.get("resource_id"),
                    "ResourceName":  m.get("name"),
                    "AutomaticMode": m.get("automatic"),
                    "ManualMode":    m.get("manual"),
                    "Busy":          m.get("busy"),
                    "ErrorL0":       m.get("error"),
                }
            )

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return jsonify(
            {
                "machines": machines,
                "orders":   [],
                "now":      now_str,
            }
        )
    except Exception as e:
        print("MES Status Error:", e)
        return jsonify({"error": str(e)}), 500


@factory_bp.route("/api/mes_analytics", methods=["GET"])
@login_required
def api_mes_analytics():
    """
    取得 Festo MES 各機台平均能源消耗分析（JSON）。
    資料來源：FestoMES.accdb 的 tblResourceOperation + tblResource
    回傳：
      - labels      : 機台名稱列表
      - energy      : 各機台平均電力消耗（kWh）
      - air         : 各機台平均氣壓消耗
    僅 admin 可存取。
    """
    if session.get("role") != "admin":
        abort(403)

    from core.db import get_festo_db
    try:
        conn   = get_festo_db()
        cursor = conn.cursor()

        # 統計各機台的平均電力與氣壓消耗
        cursor.execute("""
            SELECT r.ResourceName,
                   AVG(ro.ElectricEnergy) as AvgEnergy,
                   AVG(ro.CompressedAir)  as AvgAir
            FROM tblResourceOperation ro
            INNER JOIN tblResource r ON ro.ResourceID = r.ResourceID
            GROUP BY r.ResourceName
        """)

        labels      = []
        energy_data = []
        air_data    = []

        for row in cursor.fetchall():
            res_name = row[0]
            avg_eng  = float(row[1]) if row[1] else 0.0
            avg_air  = float(row[2]) if row[2] else 0.0

            labels.append(res_name)
            energy_data.append(round(avg_eng, 2))
            air_data.append(round(avg_air, 2))

        conn.close()

        return jsonify(
            {
                "labels": labels,
                "energy": energy_data,
                "air":    air_data,
            }
        )
    except Exception as e:
        print("MES Analytics Error:", e)
        return jsonify({"error": str(e)}), 500


@factory_bp.route("/api/mes_alerts", methods=["GET"])
@login_required
def api_mes_alerts():
    """
    查詢 Festo MES 機台的即時警報（錯誤狀態）。
    資料來源：FestoMES.accdb 的 tblMachineReport
    僅 admin 可存取（非 admin 回傳空警報列表而非 403，避免前端錯誤）。
    
    特殊邏輯：若剛登入（session["just_logged_in"]=True），回傳 reset_dismiss=True，
    告知前端重置警報彈窗的 dismiss 狀態（讓每次登入都能看到警報）。
    """
    if session.get("role") != "admin":
        return jsonify(
            {"has_error": False, "errors": [], "message": "Only admins can receive MES alerts"}
        )

    reset_dismiss = bool(session.pop("just_logged_in", False))

    from .mes_data_service import MesDataService
    errors = MesDataService.get_active_machine_errors()
    return jsonify(
        {
            "has_error":    len(errors) > 0,
            "errors":       errors,
            "count":        len(errors),
            "reset_dismiss": reset_dismiss,
        }
    )


@factory_bp.route("/api/trigger_mes_error", methods=["POST"])
@login_required
def api_trigger_mes_error():
    """
    測試用：在 FestoMES.accdb 中為指定機台寫入 ErrorL0 錯誤狀態。
    Request Body（JSON）：
      - resource_id : 機台 ID（預設 8，為加熱站）
      - error_l0    : 是否設為錯誤（bool，預設 True）
    僅 admin 可存取。
    """
    if session.get("role") != "admin":
        abort(403)

    data        = request.get_json(silent=True) or {}
    resource_id = int(data.get("resource_id", 8))  # 預設測試 8 號加熱站
    error_l0    = bool(data.get("error_l0", True))

    from .mes_data_service import MesDataService
    ok = MesDataService.set_machine_error(resource_id, error_l0)
    return jsonify(
        {
            "ok":          ok,
            "resource_id": resource_id,
            "error_l0":    error_l0,
            "message":     f"機台 (ID: {resource_id}) ErrorL0 變數已更新為 {error_l0}",
        }
    )


@factory_bp.route("/api/buffer_status", methods=["GET"])
@login_required
def api_buffer_status():
    """
    取得倉儲 Buffer Pose 1~32 的即時狀態（JSON）。
    資料來源：FestoMES.accdb 的 tblBufferPos 或 Supabase

    回傳格式：
      {
        "positions": [
          {
            "buf_pos": 1,       # 位置編號 1~32
            "type": 2,          # 顏色代碼 (0=空, 1=紅, 2=藍, 3=黑, 5=白)
            "f_no": 0,          # FinishedOrder No.
            "o_no": 0,          # Order No.
            "quantity": 1,      # 當前數量
            "quantity_max": 1,  # 最大容量
            "time_stamp": "...",# 最後更新時間
          }, ...
        ],
        "summary": {
          "total": 32, "occupied": 5, "empty": 27
        }
      }

    僅 admin 可存取。
    """
    if session.get("role") != "admin":
        abort(403)

    from .mes_data_service import MesDataService
    try:
        positions = MesDataService.get_buffer_positions()
        # f_no != 0 表示格位有加工品（0=空, 25=盤子, 210=黑, 410=藍, 610=白）
        occupied = sum(1 for p in positions if p.get("f_no", 0) != 0)
        return jsonify({
            "positions": positions,
            "summary": {
                "total":    len(positions),
                "occupied": occupied,
                "empty":    len(positions) - occupied,
            },
        })
    except Exception as e:
        print("Buffer Status Error:", e)
        return jsonify({"error": str(e)}), 500
