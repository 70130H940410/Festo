# app.py
# -*- coding: utf-8 -*-

import os
import sqlite3

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
)
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.secret_key = "dev-secret-key-change-later"  # 之後可以改成環境變數或 .env

# === 資料庫路徑設定 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 使用者 / 金鑰 → User_Data.db
USER_DB_PATH = os.path.join(BASE_DIR, "database", "User_Data.db")
# 產品 / 庫存 → product.db
PRODUCT_DB_PATH = os.path.join(BASE_DIR, "database", "product.db")


def get_user_db():
    """連到 User_Data.db（User_profile / registration_key 用）"""
    conn = sqlite3.connect(USER_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_product_db():
    """連到 product.db（products 用）"""
    conn = sqlite3.connect(PRODUCT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# =========================
# 首頁
# =========================

@app.route("/")
def index():
    """
    首頁：
    - 第一次進來才顯示 FESTO loader 動畫（index.html 裡的 show_loader）
    """
    first_visit = not session.get("seen_index")
    if first_visit:
        session["seen_index"] = True

    return render_template("index.html", show_loader=first_visit)


# =========================
# 認證 / 會員系統
# =========================

@app.route("/login", methods=["GET", "POST"])
def login():
    error_message = None
    success_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            error_message = "請輸入帳號與密碼。"
        else:
            conn = get_user_db()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, username, password_hash, role
                FROM User_profile
                WHERE username = ?
                """,
                (username,),
            )
            row = cur.fetchone()
            conn.close()

            if row and check_password_hash(row["password_hash"], password):
                # 登入成功，寫入 session
                session["user_id"] = row["id"]
                session["username"] = row["username"]
                session["role"] = row["role"]

                # 依角色導向不同頁面
                if row["role"] == "manager":
                    return redirect(url_for("manager_inventory"))
                else:
                    return redirect(url_for("order_page"))
            else:
                error_message = "帳號或密碼錯誤。"

    # 若是註冊成功後 redirect 來這裡，也可以透過 query string 或 template 傳 success_message
    return render_template(
        "auth/login.html",
        error_message=error_message,
        success_message=success_message,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    """
    一般使用者註冊：role = 'customer'
    寫入 User_profile
    """
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()

        if not username or not password:
            error_message = "帳號與密碼為必填。"
        else:
            conn = get_user_db()
            cur = conn.cursor()

            # 檢查帳號有沒有被用過
            cur.execute(
                "SELECT id FROM User_profile WHERE username = ?",
                (username,),
            )
            exists = cur.fetchone()

            if exists:
                error_message = "此帳號已被使用，請換一個。"
                conn.close()
            else:
                password_hash = generate_password_hash(password)
                cur.execute(
                    """
                    INSERT INTO User_profile
                        (username, password_hash, email, full_name, role)
                    VALUES (?, ?, ?, ?, 'customer')
                    """,
                    (username, password_hash, email, full_name),
                )
                conn.commit()
                conn.close()

                return render_template(
                    "auth/login.html",
                    success_message="註冊成功，請使用該帳號登入。",
                )

    return render_template(
        "auth/register_customer.html",
        error_message=error_message,
    )


@app.route("/register/manager", methods=["GET", "POST"])
def register_manager():
    """
    工廠管理者註冊：role = 'manager'
    需要先驗證 registration_key.Key_code
    """
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()
        factory_key = request.form.get("factory_key", "").strip()

        if not username or not password or not factory_key:
            error_message = "帳號、密碼與工廠金鑰為必填。"
        else:
            conn = get_user_db()
            cur = conn.cursor()

            # 1. 檢查金鑰是否存在
            cur.execute(
                """
                SELECT Manager_name
                FROM registration_key
                WHERE Key_code = ?
                """,
                (factory_key,),
            )
            key_row = cur.fetchone()

            if not key_row:
                error_message = "工廠負責人金鑰錯誤，請確認後再試。"
                conn.close()
            else:
                # 2. 檢查帳號是否已存在
                cur.execute(
                    "SELECT id FROM User_profile WHERE username = ?",
                    (username,),
                )
                exists = cur.fetchone()

                if exists:
                    error_message = "此帳號已被使用，請換一個。"
                    conn.close()
                else:
                    password_hash = generate_password_hash(password)
                    cur.execute(
                        """
                        INSERT INTO User_profile
                            (username, password_hash, email, full_name, role)
                        VALUES (?, ?, ?, ?, 'manager')
                        """,
                        (username, password_hash, email, full_name),
                    )
                    conn.commit()
                    conn.close()

                    return redirect(url_for("login"))

    return render_template(
        "auth/register_manager.html",
        error_message=error_message,
    )


@app.route("/user/profile", methods=["GET", "POST"])
def user_profile():
    """
    個人資料頁：
    - 顯示 username / email / full_name / role
    - 可修改基本資料
    - 可變更密碼
    """
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_user_db()
    cur = conn.cursor()

    # 先讀目前資料
    cur.execute(
        """
        SELECT id, username, email, full_name, role
        FROM User_profile
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        session.clear()
        return redirect(url_for("login"))

    error_message = None
    success_message = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_profile":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip()

            cur.execute(
                """
                UPDATE User_profile
                SET full_name = ?, email = ?
                WHERE id = ?
                """,
                (full_name, email, user_id),
            )
            conn.commit()
            success_message = "基本資料已更新。"

        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            new_password_confirm = request.form.get("new_password_confirm", "")

            cur.execute(
                "SELECT password_hash FROM User_profile WHERE id = ?",
                (user_id,),
            )
            pw_row = cur.fetchone()

            if not pw_row:
                error_message = "找不到使用者資料。"
            elif not check_password_hash(pw_row["password_hash"], current_password):
                error_message = "目前密碼不正確。"
            elif not new_password:
                error_message = "新密碼不可為空白。"
            elif new_password != new_password_confirm:
                error_message = "兩次輸入的新密碼不一致。"
            else:
                new_hash = generate_password_hash(new_password)
                cur.execute(
                    """
                    UPDATE User_profile
                    SET password_hash = ?
                    WHERE id = ?
                    """,
                    (new_hash, user_id),
                )
                conn.commit()
                success_message = "密碼已更新。"

    # 再抓一次最新資料
    cur.execute(
        """
        SELECT id, username, email, full_name, role
        FROM User_profile
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()

    user = {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
    }

    return render_template(
        "user/profile.html",
        user=user,
        error_message=error_message,
        success_message=success_message,
    )


# =========================
# 前台：下單 / 製程規劃 / 工廠模擬
# =========================

@app.route("/order", methods=["GET", "POST"])
def order_page():
    """
    下單頁：
    目前先只顯示產品列表，後續再加購物車 / 製程規劃串接。
    """
    conn = get_product_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, description, base_price, stock
        FROM products
        """
    )
    rows = cur.fetchall()
    conn.close()

    products = [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "base_price": row["base_price"],
            "stock": row["stock"],
        }
        for row in rows
    ]

    return render_template("order/order_page.html", products=products)


@app.route("/process-plan", methods=["GET", "POST"])
def process_plan():
    """
    製程規劃頁：
    目前用 demo 的 standard_steps，
    之後可以改成從資料庫 process_templates 讀取。
    """
    # demo 用：標準製程（之後可從 DB 讀）
    standard_steps = [
        {"step_order": 1, "step_name": "揀料（上蓋 / 下蓋 / 保險絲 / 電路板）", "estimated_time_sec": 5},
        {"step_order": 2, "step_name": "組裝", "estimated_time_sec": 10},
        {"step_order": 3, "step_name": "電性測試", "estimated_time_sec": 8},
        {"step_order": 4, "step_name": "包裝", "estimated_time_sec": 5},
    ]

    # demo 用：訂單摘要（實際上應由 session 或暫存表取得）
    order_items_summary = [
        {"name": "Basic Fuse Box - Black", "quantity": 3},
    ]

    # 目前先讓前端 JS 接管，不真正寫入 DB
    return render_template(
        "order/process_plan.html",
        standard_steps=standard_steps,
        order_items_summary=order_items_summary,
    )


@app.route("/factory/simulate")
def factory_simulate():
    """
    工廠運作模擬頁：
    目前用示意資料，之後可以接 MES 更新 order_process_steps 狀態。
    """
    # demo 用：訂單資訊
    order_info = {
        "id": 1,
        "user_name": session.get("username", "Demo User"),
        "status": "in_progress",
    }

    # demo 用：製程步驟與狀態
    steps = [
        {"step_order": 1, "step_name": "揀料（上蓋 / 下蓋 / 保險絲 / 電路板）", "status": "finished"},
        {"step_order": 2, "step_name": "組裝", "status": "running"},
        {"step_order": 3, "step_name": "電性測試", "status": "pending"},
        {"step_order": 4, "step_name": "包裝", "status": "pending"},
    ]

    return render_template(
        "factory/simulate.html",
        order_info=order_info,
        steps=steps,
    )


# =========================
# 後台：庫存管理 / 製程模板管理（manager）
# =========================

def manager_required(view_func):
    """
    簡單的 manager 權限檢查 decorator。
    必須登入且 role == 'manager'
    """
    from functools import wraps

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        role = session.get("role")
        if role != "manager":
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapper


@app.route("/manager/inventory")
@manager_required
def manager_inventory():
    """
    庫存管理頁：
    目前先單純 render template，之後再把 inventory 表接上。
    """
    return render_template("manager/inventory.html")


@app.route("/manager/process-templates")
@manager_required
def manager_process_templates():
    """
    製程模板管理頁：
    目前先用示意資料顯示表格。
    """
    # demo 用：兩個標準製程
    templates = [
        {
            "id": 1,
            "name": "標準保險絲盒組裝流程",
            "steps": [
                "揀料（上蓋 / 下蓋 / 保險絲 / 電路板）",
                "組裝",
                "電性測試",
                "包裝",
            ],
        },
        {
            "id": 2,
            "name": "高強度測試流程",
            "steps": [
                "揀料",
                "組裝",
                "高溫燒機測試",
                "電性測試",
                "包裝",
            ],
        },
    ]

    return render_template(
        "manager/process_templates.html",
        templates=templates,
    )


# =========================
# 主程式入口
# =========================

if __name__ == "__main__":
    # debug=True 方便開發時自動重啟與看到錯誤
    app.run(debug=True)

