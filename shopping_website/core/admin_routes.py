# =============================================================
# core/admin_routes.py
# 管理後台路由模組（Admin Dashboard）
# ----------------------------------------------------------
# Blueprint 名稱：admin（前綴 /admin）
# 路由清單：
#   GET  /admin/dashboard         → 管理後台主頁面（HTML）
#   GET  /admin/api/status        → 取得機台狀態/原料庫存/活躍訂單（JSON）
#   POST /admin/api/restock       → 補充所有原料庫存至 2000
#   POST /admin/api/break         → 讓指定機台進入故障狀態
#   POST /admin/api/repair        → 修復指定機台故障
#   GET  /admin/api/analytics     → 取得訂單統計圖表資料（JSON）
# =============================================================

from flask import Blueprint, render_template, jsonify, request
import sqlite3
import os
from datetime import datetime

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# -------------------------
# 內部 Helper 函式
# -------------------------

def _db_path(filename: str) -> str:
    """回傳 database/ 目錄下指定檔名的絕對路徑"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "database", filename)


def _conn(path: str) -> sqlite3.Connection:
    """建立 SQLite 連線，並啟用 Row 工廠（可用欄位名稱存取資料）"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


# =============================================================
# 頁面路由
# =============================================================

@admin_bp.route("/dashboard")
def dashboard():
    """
    管理後台主頁面。
    實際資料由前端 JS 呼叫 /admin/api/status 取得（非同步更新）。
    """
    return render_template("admin/dashboard.html")


# =============================================================
# API：取得工廠即時狀態
# =============================================================

@admin_bp.route("/api/status")
def api_status():
    """
    取得工廠即時狀態（供前端 Dashboard 輪詢）。
    回傳 JSON 包含：
      - stations : 所有機台的狀態（是否忙碌、是否故障）
      - materials: 原物料庫存清單
      - orders   : 進行中 / 待付款的訂單
      - now      : 伺服器當前時間
    """
    order_db = _conn(_db_path("order_management.db"))
    prod_db  = _conn(_db_path("product.db"))
    try:
        # 自動補 is_error 欄位（舊資料庫可能沒有）
        try:
            order_db.execute("ALTER TABLE station_state ADD COLUMN is_error INTEGER DEFAULT 0")
            order_db.commit()
        except Exception:
            pass  # 欄位已存在，忽略

        # 機台狀態
        stations = [dict(r) for r in order_db.execute("SELECT * FROM station_state").fetchall()]
        for s in stations:
            s["is_error"] = s.get("is_error") or 0  # 確保 None 轉為 0

        # 原物料庫存
        materials = [dict(r) for r in prod_db.execute("SELECT * FROM raw_materials").fetchall()]

        # 進行中 / 待付款訂單
        orders = [
            dict(r)
            for r in order_db.execute(
                "SELECT order_id, customer_name, product, amount, status, date "
                "FROM order_list "
                "WHERE status IN ('active', 'pending_payment') "
                "ORDER BY date DESC"
            ).fetchall()
        ]

        return jsonify(
            {
                "stations":  stations,
                "materials": materials,
                "orders":    orders,
                "now":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    finally:
        order_db.close()
        prod_db.close()


# =============================================================
# API：補充原物料庫存
# =============================================================

@admin_bp.route("/api/restock", methods=["POST"])
def restock():
    """
    一鍵補充所有原物料庫存至 2000 單位。
    補充完成後透過 SSE 廣播通知所有連線的前端更新畫面。
    """
    prod_db = _conn(_db_path("product.db"))
    try:
        prod_db.execute("UPDATE raw_materials SET stock = 2000")
        prod_db.commit()

        # 透過 SSE 廣播更新事件
        from core.sse import sse_manager
        import json
        sse_manager.announce(json.dumps({"event": "update"}))

        return jsonify({"success": True})
    finally:
        prod_db.close()


# =============================================================
# API：機台故障 / 修復
# =============================================================

@admin_bp.route("/api/break", methods=["POST"])
def break_machine():
    """
    讓指定機台進入故障狀態（is_error = 1）。
    故障機台在工廠排程中會凍結（busy_until 持續延長），無法被派工。
    Request Body（JSON）：{ "station": "機台名稱" }
    """
    data    = request.get_json()
    station = data.get("station")

    order_db = _conn(_db_path("order_management.db"))
    try:
        # 確保 is_error 欄位存在（舊 DB 可能沒有）
        try:
            order_db.execute("ALTER TABLE station_state ADD COLUMN is_error INTEGER DEFAULT 0")
        except Exception:
            pass

        order_db.execute(
            "UPDATE station_state SET is_error = 1 WHERE station = ?",
            (station,),
        )
        order_db.commit()

        # 透過 SSE 廣播更新事件
        from core.sse import sse_manager
        import json
        sse_manager.announce(json.dumps({"event": "update"}))

        return jsonify({"success": True})
    finally:
        order_db.close()


@admin_bp.route("/api/repair", methods=["POST"])
def repair_machine():
    """
    修復指定機台（is_error = 0）。
    修復後機台可以重新接受派工。
    Request Body（JSON）：{ "station": "機台名稱" }
    """
    data    = request.get_json()
    station = data.get("station")

    order_db = _conn(_db_path("order_management.db"))
    try:
        order_db.execute(
            "UPDATE station_state SET is_error = 0 WHERE station = ?",
            (station,),
        )
        order_db.commit()

        # 透過 SSE 廣播更新事件
        from core.sse import sse_manager
        import json
        sse_manager.announce(json.dumps({"event": "update"}))

        return jsonify({"success": True})
    finally:
        order_db.close()


# =============================================================
# API：分析圖表資料
# =============================================================

@admin_bp.route("/api/analytics", methods=["GET"])
def analytics():
    """
    取得訂單統計資料，供前端繪製圖表使用。
    回傳 JSON 包含：
      - status_pie : 訂單狀態分佈（圓餅圖），包含 labels 和 values
      - daily_line : 最近 7 天完成訂單數量趨勢（折線圖），包含 labels 和 values
    """
    order_db = _conn(_db_path("order_management.db"))
    try:
        # 1. 訂單狀態分佈（圓餅圖）
        status_counts = order_db.execute(
            """
            SELECT status, COUNT(*) as c
            FROM order_list
            GROUP BY status
            """
        ).fetchall()

        status_data = {
            "labels": [r["status"] for r in status_counts],
            "values": [r["c"]      for r in status_counts],
        }

        # 2. 最近 7 天每日完成訂單趨勢（折線圖）
        daily_counts = order_db.execute(
            """
            SELECT date(date) as d, COUNT(*) as c
            FROM order_list
            WHERE status = 'completed'
            GROUP BY date(date)
            ORDER BY d ASC
            LIMIT 7
            """
        ).fetchall()

        daily_data = {
            "labels": [r["d"] for r in daily_counts],
            "values": [r["c"] for r in daily_counts],
        }

        return jsonify(
            {
                "status_pie": status_data,
                "daily_line": daily_data,
            }
        )
    finally:
        order_db.close()
