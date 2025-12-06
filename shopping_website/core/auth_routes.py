# core/auth_routes.py
import os
import sqlite3

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    current_app,
)
from werkzeug.security import generate_password_hash, check_password_hash

from . import login_required  # 從 core/__init__.py 匯入


auth_bp = Blueprint("auth", __name__)


# ========= 共用：取得 User_Data.db 連線 =========

def get_user_db():
    db_path = os.path.join(current_app.root_path, "database", "User_Data.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ========= 登入 =========

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_user_db()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, account, email, password_hash, role
                FROM User_profile
                WHERE account = ?
                """,
                (username,),
            )
            user = cur.fetchone()
        finally:
            conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            error_message = "帳號或密碼錯誤。"
        else:
            # 登入成功 → 寫入 session
            session["user_id"] = user["id"]
            session["account"] = user["account"]
            session["role"] = user["role"]

            # 登入後導向下單頁
            return redirect(url_for("order.order_page"))

    return render_template("auth/login.html", error_message=error_message)


# ========= 登出 =========

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# ========= 一般使用者註冊 =========

@auth_bp.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()  # 目前沒有欄位就先不用存

        if not username or not password:
            error_message = "請填寫帳號與密碼。"
            return render_template(
                "auth/register_customer.html",
                error_message=error_message,
            )

        conn = get_user_db()
        cur = conn.cursor()
        try:
            # 檢查帳號 / Email 是否重複
            cur.execute(
                "SELECT id FROM User_profile WHERE account = ? OR email = ?",
                (username, email),
            )
            if cur.fetchone():
                error_message = "帳號或 Email 已被使用，請改用其他帳號 / Email。"
                return render_template(
                    "auth/register_customer.html",
                    error_message=error_message,
                )

            password_hash = generate_password_hash(password)

            cur.execute(
                """
                INSERT INTO User_profile (account, email, password_hash, role, registration_key)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (username, email, password_hash, "customer"),
            )
            conn.commit()
        finally:
            conn.close()

        return redirect(url_for("auth.login"))

    return render_template("auth/register_customer.html", error_message=error_message)


# ========= 管理者註冊（需要工廠負責人金鑰） =========

@auth_bp.route("/register/manager", methods=["GET", "POST"])
def register_manager():
    """工廠管理者註冊：必須輸入存在於 registration_key 資料表中的金鑰。"""
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()
        factory_key = request.form.get("factory_key", "").strip()

        if not username or not password or not factory_key:
            error_message = "請填寫帳號、密碼與工廠負責人金鑰。"
            return render_template(
                "auth/register_manager.html",
                error_message=error_message,
            )

        conn = get_user_db()
        cur = conn.cursor()

        try:
            # 1. 檢查金鑰是否存在於 registration_key
            cur.execute(
                "SELECT Manager_name FROM registration_key WHERE registration_key = ?",
                (factory_key,),
            )
            row = cur.fetchone()

            if row is None:
                error_message = "工廠負責人金鑰錯誤，請確認後再試。"
                return render_template(
                    "auth/register_manager.html",
                    error_message=error_message,
                )

            # 2. 檢查帳號 / Email 是否重複
            cur.execute(
                "SELECT id FROM User_profile WHERE account = ? OR email = ?",
                (username, email),
            )
            exists = cur.fetchone()
            if exists:
                error_message = "帳號或 Email 已被使用，請改用其他帳號 / Email。"
                return render_template(
                    "auth/register_manager.html",
                    error_message=error_message,
                )

            # 3. 寫入 User_profile，角色 admin，記錄使用的金鑰
            password_hash = generate_password_hash(password)

            cur.execute(
                """
                INSERT INTO User_profile (account, email, password_hash, role, registration_key)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, email, password_hash, "admin", factory_key),
            )
            conn.commit()

        finally:
            conn.close()

        return redirect(url_for("auth.login"))

    return render_template("auth/register_manager.html", error_message=error_message)


# ========= 個人資料頁 =========

@auth_bp.route("/profile", methods=["GET", "POST"], endpoint="profile")
@login_required
def user_profile():
    """
    顯示 & 編輯目前登入使用者的基本資料：
    - account
    - email
    （目前資料表沒有 full_name，就先不處理姓名）
    """
    error_message = None
    success_message = None

    user_id = session.get("user_id")

    conn = get_user_db()
    cur = conn.cursor()

    if request.method == "POST":
        new_account = request.form.get("account", "").strip()
        new_email = request.form.get("email", "").strip()

        if not new_account:
            error_message = "帳號不可為空白。"
        else:
            try:
                # 檢查其他人是否已使用同一個 account 或 email
                cur.execute(
                    """
                    SELECT id FROM User_profile
                    WHERE (account = ? OR email = ?) AND id != ?
                    """,
                    (new_account, new_email, user_id),
                )
                exists = cur.fetchone()
                if exists:
                    error_message = "帳號或 Email 已被其他使用者使用。"
                else:
                    # 更新自己的資料
                    cur.execute(
                        """
                        UPDATE User_profile
                        SET account = ?, email = ?
                        WHERE id = ?
                        """,
                        (new_account, new_email, user_id),
                    )
                    conn.commit()
                    success_message = "個人資料已更新。"
                    session["account"] = new_account
            except sqlite3.Error:
                error_message = "更新資料時發生錯誤，請稍後再試。"

    # 不管 GET 或 POST，都重新讀一次自己的資料
    cur.execute(
        """
        SELECT id, account, email, role, registration_key
        FROM User_profile
        WHERE id = ?
        """,
        (user_id,),
    )
    profile = cur.fetchone()
    conn.close()

    return render_template(
        "user/profile.html",
        profile=profile,
        error_message=error_message,
        success_message=success_message,
    )


