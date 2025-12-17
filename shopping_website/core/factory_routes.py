# core/factory_routes.py
# 站點並行流水線：同時允許多個 step running（不同 station 同時加工不同件）
# done/total：每一步顯示已完成件數 / 總件數（例如 1/6）
# 強化：simulate 頁面載入時會自動 tick 一次（只針對這張訂單），避免前端 JS 沒打到 tick 而一直 0/5

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from flask import Blueprint, render_template, session, current_app, request, abort, jsonify

from . import login_required

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")

# ====== 依你的專案實際檔名調整 ======
_ORDER_DB_FILENAME = "order_management.db"
_PRODUCT_DB_FILENAME = "product.db"
_COMPLETE_STATUS = "completed"


# -------------------------
# helpers
# -------------------------
def _db_path(filename: str) -> str:
    return os.path.join(current_app.root_path, "database", filename)


def _conn(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _now() -> datetime:
    return datetime.now()


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_step_chain(s: str) -> List[int]:
    if not s:
        return []
    out: List[int] = []
    for part in s.split("->"):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _ensure_tables(order_db: sqlite3.Connection) -> None:
    # 1) piece_step_progress（若不存在就建立）
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

    # 2) station_state（若不存在就建立舊表也沒關係，下面會補欄位）
    order_db.execute("""
        CREATE TABLE IF NOT EXISTS station_state (
          station TEXT PRIMARY KEY,
          current_order_id TEXT,
          current_step_order INTEGER,
          busy_until TEXT,
          updated_at TEXT DEFAULT (datetime('now'))
        );
    """)

    # 3) ✅ 遷移：補齊缺少的欄位（你的錯誤就是缺 current_piece_no）
    cols = {r["name"] for r in order_db.execute("PRAGMA table_info(station_state)").fetchall()}

    def add_col(sql: str):
        try:
            order_db.execute(sql)
        except sqlite3.OperationalError:
            pass

    if "current_piece_no" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN current_piece_no INTEGER;")

    # 有些人早期版本也可能少這些（保險）
    if "current_step_order" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN current_step_order INTEGER;")
    if "busy_until" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN busy_until TEXT;")
    if "updated_at" not in cols:
        add_col("ALTER TABLE station_state ADD COLUMN updated_at TEXT;")

    order_db.commit()


def _ensure_station_rows(order_db: sqlite3.Connection, product_db: sqlite3.Connection) -> None:
    rows = product_db.execute("""
        SELECT DISTINCT station
        FROM standard_process
        WHERE station IS NOT NULL AND TRIM(station) <> ''
        ORDER BY station
    """).fetchall()
    for r in rows:
        order_db.execute("INSERT OR IGNORE INTO station_state(station) VALUES (?)", (r["station"],))
    order_db.commit()


def _get_est_sec(product_db: sqlite3.Connection, step_order: int) -> int:
    r = product_db.execute("""
        SELECT estimated_time_sec
        FROM standard_process
        WHERE step_order=?
    """, (step_order,)).fetchone()
    if not r:
        return 5
    try:
        return int(r["estimated_time_sec"] or 5)
    except Exception:
        return 5


def _get_step_station_map(product_db: sqlite3.Connection) -> Dict[int, str]:
    rows = product_db.execute("""
        SELECT step_order, station
        FROM standard_process
    """).fetchall()
    mp: Dict[int, str] = {}
    for r in rows:
        mp[int(r["step_order"])] = (r["station"] or "").strip()
    return mp


def _get_step_defs(product_db: sqlite3.Connection, chain: List[int]) -> List[dict]:
    placeholders = ",".join(["?"] * len(chain))
    rows = product_db.execute(f"""
        SELECT step_order, step_name, station, description, estimated_time_sec
        FROM standard_process
        WHERE step_order IN ({placeholders})
    """, chain).fetchall()

    by_no = {int(r["step_order"]): dict(r) for r in rows}
    return [by_no[n] for n in chain if n in by_no]


def _ensure_piece_rows(order_db: sqlite3.Connection, order_id: str, chain: List[int], amount: int) -> None:
    amount = max(1, int(amount or 1))
    for piece_no in range(1, amount + 1):
        for step_no in chain:
            order_db.execute("""
                INSERT OR IGNORE INTO piece_step_progress(order_id, piece_no, step_order, state)
                VALUES (?, ?, ?, 'pending')
            """, (order_id, piece_no, step_no))
    order_db.commit()


def _piece_is_running(order_db: sqlite3.Connection, order_id: str, piece_no: int) -> bool:
    r = order_db.execute("""
        SELECT 1
        FROM piece_step_progress
        WHERE order_id=? AND piece_no=? AND state='running'
        LIMIT 1
    """, (order_id, piece_no)).fetchone()
    return r is not None


def _prev_step(chain: List[int], step_no: int) -> Optional[int]:
    if step_no not in chain:
        return None
    idx = chain.index(step_no)
    if idx == 0:
        return None
    return chain[idx - 1]


def _is_order_completed(order_db: sqlite3.Connection, order_id: str, last_step: int, amount: int) -> bool:
    r = order_db.execute("""
        SELECT COUNT(*) AS c
        FROM piece_step_progress
        WHERE order_id=? AND step_order=? AND state='finished'
    """, (order_id, last_step)).fetchone()
    return int(r["c"] or 0) >= max(1, int(amount or 1))


def _complete_due_jobs(order_db: sqlite3.Connection) -> None:
    """把 busy_until 到點的 station 完成當前工作（running -> finished），並釋放 station。"""
    now = _now()

    running_stations = order_db.execute("""
        SELECT station, current_order_id, current_piece_no, current_step_order, busy_until
        FROM station_state
        WHERE current_order_id IS NOT NULL AND busy_until IS NOT NULL
    """).fetchall()

    for ss in running_stations:
        try:
            end_dt = datetime.fromisoformat(str(ss["busy_until"]))
        except Exception:
            continue
        if now < end_dt:
            continue

        order_id = str(ss["current_order_id"])
        piece_no = int(ss["current_piece_no"])
        step_no = int(ss["current_step_order"])

        order_db.execute("""
            UPDATE piece_step_progress
            SET state='finished', finished_at=?
            WHERE order_id=? AND piece_no=? AND step_order=? AND state='running'
        """, (_fmt(now), order_id, piece_no, step_no))

        order_db.execute("""
            UPDATE station_state
            SET current_order_id=NULL, current_piece_no=NULL, current_step_order=NULL, busy_until=NULL, updated_at=?
            WHERE station=?
        """, (_fmt(now), ss["station"]))

    order_db.commit()


def _dispatch_for_focus_order(order_db: sqlite3.Connection, product_db: sqlite3.Connection, focus_order_id: str) -> List[dict]:
    """
    只針對 focus_order_id 派工（避免你只有一單但前端 tick 沒打到/或之後多單時派錯單）。
    回傳 dispatched list。
    """
    now = _now()
    step_station = _get_step_station_map(product_db)

    # station -> step_orders
    station_steps: Dict[str, List[int]] = {}
    for step_no, st in step_station.items():
        if not st:
            continue
        station_steps.setdefault(st, []).append(step_no)
    for st in station_steps:
        station_steps[st].sort()

    # 讀這張訂單
    o = order_db.execute("""
        SELECT order_id, step_name, amount, status
        FROM order_list
        WHERE status='active' AND order_id=?
        LIMIT 1
    """, (focus_order_id,)).fetchone()
    if not o:
        return []

    chain = _parse_step_chain(o["step_name"] or "")
    if not chain:
        return []

    try:
        amount = max(1, int(o["amount"] or 1))
    except Exception:
        amount = 1

    _ensure_piece_rows(order_db, focus_order_id, chain, amount)

    # idle stations
    idle = order_db.execute("""
        SELECT station
        FROM station_state
        WHERE current_order_id IS NULL
        ORDER BY station
    """).fetchall()

    dispatched: List[dict] = []

    for st_row in idle:
        station = str(st_row["station"])
        step_list = station_steps.get(station, [])
        if not step_list:
            continue

        best_job = None  # (piece_no, step_no, est)

        for step_no in step_list:
            if step_no not in chain:
                continue
            prev = _prev_step(chain, step_no)

            cand = order_db.execute("""
                SELECT piece_no
                FROM piece_step_progress
                WHERE order_id=? AND step_order=? AND state='pending'
                ORDER BY piece_no ASC
            """, (focus_order_id, step_no)).fetchall()

            for r in cand:
                piece_no = int(r["piece_no"])

                # 同一件不允許同時跑兩個 step
                if _piece_is_running(order_db, focus_order_id, piece_no):
                    continue

                # 前一步要 finished 才能進入此步（第一步除外）
                if prev is None:
                    ok = True
                else:
                    pr = order_db.execute("""
                        SELECT state
                        FROM piece_step_progress
                        WHERE order_id=? AND piece_no=? AND step_order=?
                    """, (focus_order_id, piece_no, prev)).fetchone()
                    ok = (pr is not None and pr["state"] == "finished")

                if not ok:
                    continue

                est = _get_est_sec(product_db, step_no)
                best_job = (piece_no, step_no, est)
                break

            if best_job:
                break

        if not best_job:
            continue

        piece_no, step_no, est = best_job

        # pending -> running
        order_db.execute("""
            UPDATE piece_step_progress
            SET state='running', started_at=COALESCE(started_at, ?)
            WHERE order_id=? AND piece_no=? AND step_order=? AND state='pending'
        """, (_fmt(now), focus_order_id, piece_no, step_no))

        end_time = now + timedelta(seconds=int(est))

        # station 占用
        order_db.execute("""
            UPDATE station_state
            SET current_order_id=?, current_piece_no=?, current_step_order=?, busy_until=?, updated_at=?
            WHERE station=?
        """, (focus_order_id, piece_no, step_no, end_time.isoformat(sep=" "), _fmt(now), station))

        order_db.commit()

        dispatched.append({
            "station": station,
            "order_id": focus_order_id,
            "piece_no": piece_no,
            "step_order": step_no,
            "busy_until": end_time.isoformat(sep=" "),
        })

    return dispatched


def _tick_once_for_order(order_db: sqlite3.Connection, product_db: sqlite3.Connection, focus_order_id: str) -> List[dict]:
    """
    一次 tick：
    1) 完成到點的 station
    2) 只針對 focus_order_id 派工
    3) 若訂單最後一步全 finished -> 改 status=completed
    """
    _complete_due_jobs(order_db)

    dispatched = _dispatch_for_focus_order(order_db, product_db, focus_order_id)

    # 檢查是否完成整張訂單
    o = order_db.execute("SELECT step_name, amount FROM order_list WHERE order_id=?", (focus_order_id,)).fetchone()
    if o:
        chain = _parse_step_chain(o["step_name"] or "")
        if chain:
            try:
                amount = max(1, int(o["amount"] or 1))
            except Exception:
                amount = 1
            if _is_order_completed(order_db, focus_order_id, chain[-1], amount):
                order_db.execute("UPDATE order_list SET status=? WHERE order_id=?", (_COMPLETE_STATUS, focus_order_id))
                order_db.commit()

    return dispatched


# -------------------------
# page: simulate
# -------------------------
@factory_bp.route("/simulate")
@login_required
def simulate():
    order_id = request.args.get("order_id")
    if not order_id:
        abort(400, "need ?order_id=...")

    order_db = _conn(_db_path(_ORDER_DB_FILENAME))
    product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        _ensure_station_rows(order_db, product_db)

        o = order_db.execute("""
            SELECT order_id, customer_name, step_name, note, status, amount
            FROM order_list
            WHERE order_id=?
        """, (order_id,)).fetchone()
        if not o:
            abort(404, "order not found")

        # ✅ 權限：非 admin 只能看自己的訂單（避免改網址偷看）
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

        _ensure_piece_rows(order_db, order_id, chain, amount)

        # ⭐ 不靠前端：頁面載入先自動 tick 一次，保證至少 Step1 會開始跑
        _tick_once_for_order(order_db, product_db, order_id)

        steps = _get_step_defs(product_db, chain)

        # 聚合：每個 step done / running
        agg: Dict[int, Dict[str, int]] = {}
        for step_no in chain:
            done = order_db.execute("""
                SELECT COUNT(*) AS c
                FROM piece_step_progress
                WHERE order_id=? AND step_order=? AND state='finished'
            """, (order_id, step_no)).fetchone()["c"]

            running = order_db.execute("""
                SELECT COUNT(*) AS c
                FROM piece_step_progress
                WHERE order_id=? AND step_order=? AND state='running'
            """, (order_id, step_no)).fetchone()["c"]

            agg[step_no] = {"done": int(done or 0), "running": int(running or 0)}

        for s in steps:
            step_no = int(s["step_order"])
            done_qty = agg.get(step_no, {}).get("done", 0)
            running_qty = agg.get(step_no, {}).get("running", 0)

            s["done_qty"] = done_qty
            s["total_qty"] = amount

            if done_qty >= amount:
                s["state"] = "finished"
            elif running_qty > 0:
                s["state"] = "running"
            else:
                s["state"] = "pending"

        order_info = {
            "order_id": o["order_id"],
            "user_name": o["customer_name"] or (session.get("account") or session.get("full_name") or session.get("username", "Demo User")),
            "note": o["note"] or "無備註",
            "status": (o["status"] or "").lower(),
            "amount": amount,
        }

        return render_template("factory/simulate.html", order_info=order_info, steps=steps)

    finally:
        order_db.close()
        product_db.close()


# -------------------------
# API: init / reset / tick (GET/POST 都可)
# -------------------------
@factory_bp.route("/api/init/<order_id>", methods=["GET", "POST"])
@login_required
def api_init(order_id: str):
    order_db = _conn(_db_path(_ORDER_DB_FILENAME))
    product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        _ensure_station_rows(order_db, product_db)

        o = order_db.execute("""
            SELECT order_id, step_name, amount
            FROM order_list
            WHERE order_id=?
        """, (order_id,)).fetchone()
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
    order_db = _conn(_db_path(_ORDER_DB_FILENAME))
    try:
        _ensure_tables(order_db)

        order_db.execute("""
            UPDATE station_state
            SET current_order_id=NULL, current_piece_no=NULL, current_step_order=NULL, busy_until=NULL, updated_at=?
            WHERE current_order_id=?
        """, (_fmt(_now()), order_id))

        order_db.execute("DELETE FROM piece_step_progress WHERE order_id=?", (order_id,))
        order_db.commit()

        return jsonify({"ok": True, "order_id": order_id})

    finally:
        order_db.close()


@factory_bp.route("/api/tick", methods=["GET", "POST"])
@login_required
def api_tick():
    """
    支援：
    - /api/tick?order_id=xxx 只跑這張單（你在 simulate 頁面就用這個）
    - 沒帶 order_id：不做派工（避免未來多單時亂跑），你要全域排程再擴充
    """
    focus_order_id = request.args.get("order_id")

    order_db = _conn(_db_path(_ORDER_DB_FILENAME))
    product_db = _conn(_db_path(_PRODUCT_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        _ensure_station_rows(order_db, product_db)

        if not focus_order_id:
            # 仍會先完成到點的工作，但不主動派新工（避免跑錯單）
            _complete_due_jobs(order_db)
            return jsonify({"ok": True, "dispatched": [], "msg": "need ?order_id=... to dispatch"})

        dispatched = _tick_once_for_order(order_db, product_db, focus_order_id)
        return jsonify({"ok": True, "order_id": focus_order_id, "dispatched": dispatched})

    finally:
        order_db.close()
        product_db.close()


# Debug：看 station 是否占用 / 是否有 running
@factory_bp.route("/api/debug/state", methods=["GET"])
@login_required
def api_debug_state():
    order_db = _conn(_db_path(_ORDER_DB_FILENAME))
    try:
        _ensure_tables(order_db)
        stations = [dict(r) for r in order_db.execute("""
            SELECT station, current_order_id, current_piece_no, current_step_order, busy_until
            FROM station_state
            ORDER BY station
        """).fetchall()]
        running = [dict(r) for r in order_db.execute("""
            SELECT order_id, piece_no, step_order, state
            FROM piece_step_progress
            WHERE state='running'
            ORDER BY order_id, piece_no, step_order
        """).fetchall()]
        return jsonify({"stations": stations, "running": running})
    finally:
        order_db.close()

