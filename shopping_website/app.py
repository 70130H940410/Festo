# app.py
from flask import Flask, render_template
from core.auth_routes import auth_bp
from core.order_routes import order_bp
from core.factory_routes import factory_bp
from core.manager_routes import manager_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = "dev-key-change-this"

    # 註冊所有 blueprint
    app.register_blueprint(auth_bp)
    app.register_blueprint(order_bp)
    app.register_blueprint(factory_bp)
    app.register_blueprint(manager_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)


