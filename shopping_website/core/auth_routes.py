# core/auth_routes.py
# 負責登入 / 登出 / 註冊 / 個人資料

import uuid
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import login_required
from .db import get_user_db

auth_bp = Blueprint("auth", __name__)


# -------------------------------
# 登入 / 登出
# -------------------------------

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    - GET: 顯示登入頁
    - POST: 用「帳號或 Email」+ 密碼登入
    """
    error_message = None

    if request.method == "POST":
        # 允許使用「帳號或 Email」任何一個來登入
        identifier = (
            request.form.get("user_login", "").strip()
            or request.form.get("user_login", "").strip()
        )
        password = request.form.get("password", "")

        if not identifier or not password:
            error_message = "請輸入帳號（或 Email)與密碼。"
        else:
            conn = get_user_db()
            cur = conn.cursor()

            # 帳號 or Email 其中一個符合就抓出來
            cur.execute(
                """
                SELECT * FROM User_profile
                WHERE account = ? OR email = ?
                """,
                (identifier, identifier),
            )
            user = cur.fetchone()
            conn.close()

            if not user:
                error_message = "找不到對應的帳號 / Email。"
            else:
                if not check_password_hash(user["password_hash"], password):
                    error_message = "密碼錯誤，請再試一次。"
                else:
                    # 登入成功
                    session.clear()
                    session["user_id"] = user["id"]
                    session["account"] = user["account"]
                    session["role"] = user["role"]

                    return redirect(url_for("order.order_page"))

    return render_template("auth/login.html", error_message=error_message)


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# -------------------------------
# 個人資料頁（含：更新基本資料 + 更新密碼）
# -------------------------------

@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    error_message = None
    success_message = None

    conn = get_user_db()
    cur = conn.cursor()

    # 先抓一次使用者資料
    cur.execute(
        """
        SELECT id, account, full_name, email, role, registration_key, password_hash
        FROM User_profile
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        session.clear()
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        action = request.form.get("action")

        # ---------- 更新基本資料 ----------
        if action == "update_profile":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip()

            # Email 不空才檢查是否被其他人用過
            if email:
                cur.execute(
                    """
                    SELECT id
                    FROM User_profile
                    WHERE email = ? AND id != ?
                    """,
                    (email, user_id),
                )
                exists_email = cur.fetchone()
            else:
                exists_email = None

            if exists_email:
                error_message = "此 Email 已被其他帳號使用，請改用另一個 Email。"
            else:
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

        # ---------- 更新密碼（✅你要的：寫回資料庫） ----------
        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            new_password_confirm = request.form.get("new_password_confirm", "")

            # 重新抓 password_hash 以防資料被更新過
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

        # POST 後再抓一次最新資料（讓畫面顯示更新後的值）
        cur.execute(
            """
            SELECT id, account, full_name, email, role, registration_key
            FROM User_profile
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cur.fetchone()

    conn.close()

    user = {
        "id": row["id"],
        "username": row["account"],       # 給 template 用 user['username']
        "full_name": row["full_name"] or "",
        "email": row["email"],
        "role": row["role"],
        "registration_key": row["registration_key"],
    }

    return render_template(
        "user/profile.html",
        user=user,
        error_message=error_message,
        success_message=success_message,
    )


# -------------------------------
# 一般使用者註冊
# -------------------------------

@auth_bp.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    error_message = None
    success_message = None

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip() or None

        if not account or not email or not password:
            error_message = "請完整填寫帳號、密碼與Email。"
        else:
            conn = get_user_db()
            cur = conn.cursor()

            # 檢查帳號 / Email 是否重複
            cur.execute(
                "SELECT 1 FROM User_profile WHERE account = ? OR email = ?",
                (account, email),
            )
            exists = cur.fetchone()
            if exists:
                error_message = "帳號或 Email 已被使用，請改用其他。"
            else:
                user_id = uuid.uuid4().hex
                pwd_hash = generate_password_hash(password)

                cur.execute(
                    """
                    INSERT INTO User_profile
                    (id, account, email, password_hash, role, registration_key, full_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        account,
                        email,
                        pwd_hash,
                        "customer",
                        None,  # 一般使用者沒有註冊金鑰
                        full_name,
                    ),
                )
                conn.commit()
                conn.close()

                success_message = "一般使用者註冊成功，請返回登入。"

    return render_template(
        "auth/register_customer.html",
        error_message=error_message,
        success_message=success_message,
    )


# -------------------------------
# 工廠管理者 / 工程師註冊
# -------------------------------

@auth_bp.route("/register/manager", methods=["GET", "POST"])
def register_manager():
    """
    管理者註冊需要輸入「工廠負責人金鑰」，
    這個金鑰存在 User_Data.db 裡的 registration_key table。
    """
    error_message = None
    success_message = None

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip() or None
        factory_key = request.form.get("factory_key", "").strip()

        if not account or not email or not password or not factory_key:
            error_message = "請完整填寫帳號、密碼、Email與工廠負責人金鑰。"
        else:
            conn = get_user_db()
            cur = conn.cursor()

            # 先檢查金鑰是否存在於 registration_key table
            cur.execute(
                """
                SELECT * FROM registration_key
                WHERE registration_key = ?
                """,
                (factory_key,),
            )
            key_row = cur.fetchone()

            if not key_row:
                error_message = "工廠負責人金鑰錯誤，請確認後再試。"
            else:
                # 檢查帳號 / Email 是否重複
                cur.execute(
                    "SELECT 1 FROM User_profile WHERE account = ? OR email = ?",
                    (account, email),
                )
                exists = cur.fetchone()
                if exists:
                    error_message = "帳號或 Email 已被使用，請改用其他。"
                else:
                    user_id = uuid.uuid4().hex
                    pwd_hash = generate_password_hash(password)

                    cur.execute(
                        """
                        INSERT INTO User_profile
                        (id, account, email, password_hash, role, registration_key, full_name)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            account,
                            email,
                            pwd_hash,
                            "admin",        # 或 "manager"
                            factory_key,    # 把使用的金鑰存起來
                            full_name,
                        ),
                    )
                    conn.commit()
                    conn.close()

                    success_message = "工廠管理者帳號建立成功，請返回登入。"

    return render_template(
        "auth/register_manager.html",
        error_message=error_message,
        success_message=success_message,
    )


# -------------------------------
# 測試用的資料庫連線檢查
# -------------------------------

@auth_bp.route("/debug_db")
def debug_db():
    conn = get_user_db()
    cur = conn.cursor()
    cur.execute("SELECT id, account FROM User_profile LIMIT 5")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Database connected, but User_profile table is empty."

    lines = [f"{row['id']} - {row['account']}" for row in rows]
    return "<br>".join(lines)


