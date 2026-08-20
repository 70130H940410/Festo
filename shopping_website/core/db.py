# =============================================================
# core/db.py
# 資料庫連線管理模組
# ----------------------------------------------------------
# 提供四個函式，分別連線到專案的四個資料庫：
#   1. get_user_db()      → User_Data.db      (使用者帳號/密碼/角色)
#   2. get_product_db()   → product.db        (產品、BOM、製程步驟)
#   3. get_order_mgmt_db()→ order_management.db (訂單管理、站點狀態)
#   4. get_festo_db()     → FestoMES.accdb    (真實 Festo MES 工廠資料)
# =============================================================

import os
import sqlite3
import threading

# ── Supabase SDK（選用）──────────────────────────────────────
try:
    from supabase import create_client as _sb_create
    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False

# -------------------------
# 各資料庫的絕對路徑
# -------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

USER_DB_PATH       = os.path.join(BASE_DIR, "database", "User_Data.db")
PRODUCT_DB_PATH    = os.path.join(BASE_DIR, "database", "product.db")
ORDER_MGMT_DB_PATH = os.path.join(BASE_DIR, "database", "order_management.db")
# =========================================================
# [修改點] Access 資料庫路徑設定
# ---------------------------------------------------------
# 優先順序：
#   1. 環境變數 FESTO_DB_PATH（由啟動網站.vbs 設定）← 推薦
#   2. 下方預設路徑（程式碼裡的 fallback）
#
# 若 Access 檔案在其他位置，請修改 啟動網站.vbs 裡的
# festoDbPath 變數，不需要動這裡。
#
# 若要改預設 fallback 路徑，把下方 "FestoMES.accdb"
# 換成實際檔名或完整路徑即可。
# 詳細說明請參考：docs/Access資料庫設定說明.md
# =========================================================
FESTO_DB_PATH = os.environ.get(
    "FESTO_DB_PATH",
    os.path.join(BASE_DIR, "database", "FestoMES.accdb")   # ← fallback 預設路徑
)


# -------------------------
# SQLite 連線函式
# -------------------------

def get_user_db() -> sqlite3.Connection:
    """
    連線到 User_Data.db（使用者資料庫）。
    包含：User_profile（帳號/密碼/角色）、registration_key（管理者金鑰）
    """
    conn = sqlite3.connect(USER_DB_PATH)
    conn.row_factory = sqlite3.Row  # 讓查詢結果可用欄位名稱存取
    return conn


def get_product_db() -> sqlite3.Connection:
    """
    連線到 product.db（產品資料庫）。
    包含：products（商品清單）、standard_process（製程步驟）、
          raw_materials（原物料）、bom（物料清單）
    """
    conn = sqlite3.connect(PRODUCT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_order_mgmt_db() -> sqlite3.Connection:
    """
    連線到 order_management.db（訂單管理資料庫）。
    包含：order_list（訂單主表）、station_state（站點狀態）、
          piece_step_progress（每件商品的製程進度）
    """
    conn = sqlite3.connect(ORDER_MGMT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# -------------------------
# Access DB 連線（Festo MES）
# -------------------------

_festo_db_lock = threading.Lock()  # 預留 Lock，避免多執行緒同時寫入

def get_festo_db():
    import pyodbc
    conn_str = r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + FESTO_DB_PATH + ";"
    conn = pyodbc.connect(conn_str, autocommit=True)
    return conn


# =========================================================
# [修改點] Supabase 雲端連線設定
# ---------------------------------------------------------
# 在 啟動網站.vbs 裡設 SUPABASE_URL 和 SUPABASE_KEY
# 即可自動啟用雲端讀取。
# 沒設定环境變數時，個別函式會 fallback 到本機 Access。
# =========================================================
_supabase_client = None
_supabase_lock = threading.Lock()


def get_supabase_client():
    """
    取得 Supabase client。首次呼叫時初始化，之後就用同一個實例。
    如果未設 SUPABASE_URL / SUPABASE_KEY 環境變數，回傳 None。
    """
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client
    if not _SUPABASE_AVAILABLE:
        return None
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key or url.startswith("https://your-project"):
        return None
    with _supabase_lock:
        if _supabase_client is None:
            try:
                _supabase_client = _sb_create(url, key)
            except Exception as e:
                print(f"[db.py] Supabase init failed: {e}")
                return None
    return _supabase_client
