# shopping_website/app.py
import os
import logging
import threading
import time
from flask import Flask, render_template, session

# === 專案路徑 & 資料庫路徑 ===
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PRODUCT = os.path.join(BASE_DIR, "database", "product.db")
DATABASE_USER = os.path.join(BASE_DIR, "database", "User_Data.db")


def create_app() -> Flask:
    app = Flask(__name__)
    # 開發用的 secret key，之後要部署再換成環境變數
    app.config["SECRET_KEY"] = "dev-secret-festo-112303537"

    # 把兩個資料庫路徑放到 config，給各個 Blueprint 用
    app.config["DATABASE_PRODUCT"] = DATABASE_PRODUCT
    app.config["DATABASE_USER"] = DATABASE_USER

    # === 載入並註冊 Blueprints ===
    from core.auth_routes import auth_bp
    from core.order_routes import order_bp
    from core.factory_routes import factory_bp
    from core.manager_routes import manager_bp
    from core.admin_routes import admin_bp

    app.register_blueprint(auth_bp)       # /login, /logout, /register...
    app.register_blueprint(order_bp)      # /order/...
    app.register_blueprint(factory_bp)    # /factory/...
    app.register_blueprint(admin_bp)      # /admin/...
    app.register_blueprint(manager_bp)    # /manager/...

    # === 首頁 ===
    @app.route("/")
    def index():
        # base.html 裡已經用 {{ request.endpoint }} 設定 data-page
        # Loader 會判斷 endpoint == "index" 才顯示一次動畫
        return render_template("index.html")

    # === SSE Stream ===
    from core.sse import sse_manager
    from flask import Response

    @app.route('/api/stream')
    def stream():
        def event_stream():
            q = sse_manager.listen()
            try:
                while True:
                    msg = q.get()
                    yield f"data: {msg}\n\n"
            except GeneratorExit:
                pass
        return Response(event_stream(), mimetype="text/event-stream")

    # === 給所有模板共用的變數（例如右上角顯示帳號） ===
    @app.context_processor
    def inject_user_info():
        return {
            "logged_in": bool(session.get("user_id")),
            "current_account": session.get("account"),
            "current_role": session.get("role"),
        }

    return app


def background_factory_worker(app):
    """背景執行緒，持續推動工廠排程"""
    from core.factory_routes import _tick_all_active_orders
    while True:
        try:
            _tick_all_active_orders(app)
        except Exception as e:
            print(f"Background worker error: {e}")
        time.sleep(1)


# 直接 python app.py 執行時用這段
if __name__ == "__main__":
    # 一般的存取紀錄就會被隱藏，只留下錯誤訊息
    #log = logging.getLogger('werkzeug')
    #log.setLevel(logging.ERROR)

    app = create_app()

    # 在除錯模式下，Werkzeug 會啟動兩個 process（一個主 process，一個 worker）
    # 為了避免啟動兩次背景執行緒，我們只在主 worker 內啟動它
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        t = threading.Thread(target=background_factory_worker, args=(app,), daemon=True)
        t.start()

    # 開發階段開 debug 比較好除錯，之後部署再關掉
    app.run(host='0.0.0.0', port=5000, debug=True)

#from core.auth_routes import auth_bp

#@auth_bp.route("/debug_db")
#def debug_db():
  #from core.db import get_user_db

  #conn = get_user_db()
  #cur = conn.cursor()
  #cur.execute("SELECT id, account FROM User_profile LIMIT 5")
  #rows = cur.fetchall()
  #conn.close()

  # 直接用最簡單的方式回傳看看 
  #lines = [f"{row['id']} - {row['account']}" for row in rows]
  #return "<br>".join(lines) or "no rows"
