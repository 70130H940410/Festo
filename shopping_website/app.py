# =============================================================
# app.py
# Flask 應用程式入口點（Application Factory）
# ----------------------------------------------------------
# 此檔案負責：
#   1. 建立 Flask App（create_app）並設定 config
#   2. 載入並註冊各功能 Blueprint
#   3. 定義首頁路由 /
#   4. 建立 SSE 推播串流路由 /api/stream
#   5. 設定全域 context_processor（讓所有 HTML 模板能取得登入狀態）
#   6. 啟動背景執行緒推進工廠排程
#
# Blueprint 對應功能：
#   auth_bp      → /login, /logout, /register/...  (登入/註冊)
#   order_bp     → /order, /orders, /trace/...     (下單/訂單紀錄)
#   factory_bp   → /factory/...                    (工廠模擬/API)
#   admin_bp     → /admin/...                      (管理後台儀表板)
#   manager_bp   → /manager/...                    (訂單管理/庫存/製程)
#   scheduler_bp → /scheduler/...                  (排程演算法/甘特圖)
# =============================================================

import os
import logging
import threading
import time
from flask import Flask, render_template, session

# -------------------------
# 專案路徑 & 資料庫路徑
# -------------------------
BASE_DIR         = os.path.abspath(os.path.dirname(__file__))
DATABASE_PRODUCT = os.path.join(BASE_DIR, "database", "product.db")
DATABASE_USER    = os.path.join(BASE_DIR, "database", "User_Data.db")


def create_app() -> Flask:
    """
    Application Factory：建立並回傳 Flask App 實例。
    在測試或多環境部署時，可以多次呼叫此函式建立獨立的 App。
    """
    app = Flask(__name__)

    # -------------------------
    # App 設定
    # -------------------------
    # 開發用的 secret_key，正式部署請改成環境變數
    app.config["SECRET_KEY"] = "dev-secret-festo-112303537"
    # 把資料庫路徑存進 config，讓 Blueprint 可以透過 current_app.config 存取
    app.config["DATABASE_PRODUCT"] = DATABASE_PRODUCT
    app.config["DATABASE_USER"]    = DATABASE_USER

    # -------------------------
    # 載入並註冊 Blueprints
    # -------------------------
    from core.auth_routes      import auth_bp
    from core.order_routes     import order_bp
    from core.factory_routes   import factory_bp
    from core.manager_routes   import manager_bp
    from core.admin_routes     import admin_bp
    from core.scheduler_routes import scheduler_bp

    app.register_blueprint(auth_bp)       # /login, /logout, /register/...
    app.register_blueprint(order_bp)      # /order, /orders, /trace/...
    app.register_blueprint(factory_bp)    # /factory/...
    app.register_blueprint(admin_bp)      # /admin/...
    app.register_blueprint(manager_bp)    # /manager/...
    app.register_blueprint(scheduler_bp)  # /scheduler/...

    # -------------------------
    # 首頁路由
    # -------------------------
    @app.route("/")
    def index():
        # base.html 裡用 {{ request.endpoint }} 設定 data-page
        # Loader 動畫會判斷 endpoint == "index" 才顯示一次
        return render_template("index.html")

    # -------------------------
    # SSE 推播串流路由
    # -------------------------
    from core.sse import sse_manager
    from flask import Response

    @app.route("/api/stream")
    def stream():
        """
        Server-Sent Events 端點。
        前端透過 EventSource('/api/stream') 連線，
        工廠狀態更新時，sse_manager.announce() 會把訊息推送給所有連線的前端。
        """
        def event_stream():
            q = sse_manager.listen()  # 建立本次連線的 Queue
            try:
                while True:
                    msg = q.get()  # 阻塞等待新訊息
                    yield f"data: {msg}\n\n"
            except GeneratorExit:
                pass  # 前端斷線時 Python 會丟出 GeneratorExit，直接忽略
        return Response(event_stream(), mimetype="text/event-stream")

    from flask import send_file
    @app.route("/download/Festo_Cloud_Update.zip")
    def download_festo_update():
        zip_path = "/workspace/Festo_Cloud_Update.zip"
        if os.path.exists(zip_path):
            return send_file(zip_path, as_attachment=True, download_name="Festo_Cloud_Update.zip")
        return "File not found", 404

    # -------------------------
    # 全域模板變數（所有 HTML 模板都能使用）
    # -------------------------
    @app.context_processor
    def inject_user_info():
        """
        把登入狀態、帳號、角色注入所有模板，
        讓導覽列可以顯示目前登入帳號和角色。
        """
        return {
            "logged_in":       bool(session.get("user_id")),
            "current_account": session.get("account"),
            "current_role":    session.get("role"),
        }

    return app


# =============================================================
# 背景執行緒：工廠排程推進
# =============================================================

def background_factory_worker(app: Flask):
    """
    背景執行緒，每秒執行一次，推進所有 active 訂單的工廠排程進度。
    每 3 秒自動同步雲端訂單並下發至工廠 MES，實現免手動介入的全自動生產運作。
    """
    from core.factory_routes import _tick_all_active_orders
    from core.order_sync import sync_line_orders_to_order_list, dispatch_active_orders_to_mes

    sync_counter = 0
    while True:
        try:
            sync_counter += 1
            # 每 3 秒同步一次 LINE 訂單並自動下發到工廠 MES
            if sync_counter % 3 == 0:
                with app.app_context():
                    try:
                        sync_line_orders_to_order_list()
                    except Exception as se:
                        pass
                    try:
                        dispatch_active_orders_to_mes()
                    except Exception as de:
                        pass

            _tick_all_active_orders(app)
        except Exception as e:
            print(f"Background worker error: {e}")
        time.sleep(1)  # 每 1 秒執行一次



# =============================================================
# 直接執行入口（python app.py）
# =============================================================

if __name__ == "__main__":
    # 若要隱藏 werkzeug 的存取 log，可取消下面兩行的註解
    # log = logging.getLogger('werkzeug')
    # log.setLevel(logging.ERROR)

    app = create_app()

    # 在 debug 模式下，Werkzeug 會啟動兩個 process（主 process + reloader）
    # 使用環境變數判斷，確保背景執行緒只啟動一次
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        t = threading.Thread(
            target=background_factory_worker,
            args=(app,),
            daemon=True  # daemon=True：主程式結束時此執行緒自動停止
        )
        t.start()

    # 開發階段開 debug=True 方便除錯，正式部署請改成 False
    app.run(host="0.0.0.0", port=5000, debug=True)
