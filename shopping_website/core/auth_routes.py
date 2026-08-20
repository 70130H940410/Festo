# =============================================================
# core/auth_routes.py
# 登入 / 登出 / 個人資料 / 使用者註冊 模組
# ----------------------------------------------------------
# Blueprint 名稱：auth
# 路由清單：
#   GET/POST /login              → 登入頁（支援帳號或 Email）
#   GET      /logout             → 登出（清除 session）
#   GET/POST /profile            → 個人資料頁（更新姓名/Email/密碼）
#   GET/POST /register/customer  → 一般使用者註冊
#   GET/POST /register/manager   → 工廠管理者註冊（需輸入金鑰）
#   GET      /debug_db           → 開發用：確認 DB 連線是否正常
# =============================================================

import secrets
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


# =============================================================
# 登入 / 登出
# =============================================================

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    登入頁。
    - GET : 顯示登入表單
    - POST: 驗證「帳號或 Email」+ 密碼，成功後建立 session 並導向訂單頁
    """
    error_message = None

    if request.method == "POST":
        # 允許使用帳號 或 Email 任何一個來登入
        identifier = request.form.get("user_login", "").strip()
        password   = request.form.get("password", "")

        if not identifier or not password:
            error_message = "請輸入帳號（或 Email)與密碼。"
        else:
            conn = get_user_db()
            cur  = conn.cursor()

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

            if user and check_password_hash(user["password_hash"], password):
                # 登入成功：建立 session
                session.clear()
                session["user_id"]        = user["id"]
                session["account"]        = user["account"]
                session["role"]           = user["role"]
                session["just_logged_in"] = True  # 控制首次登入動畫

                return redirect(url_for("order.order_page"))
            else:
                # 登入失敗（帳號不存在 or 密碼錯誤）
                error_message = "帳號或密碼錯誤，請再試一次。"

    return render_template("auth/login.html", error_message=error_message)


@auth_bp.route("/logout")
def logout():
    """
    登出：清除所有 session，導回登入頁。
    """
    session.clear()
    return redirect(url_for("auth.login"))


# =============================================================
# 個人資料頁（更新姓名/Email + 更改密碼）
# =============================================================

@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """
    個人資料頁。
    - GET : 顯示目前的帳號資訊
    - POST: 依 action 欄位執行不同操作：
        action = "update_profile" → 更新姓名和 Email
        action = "change_password" → 更改密碼（需驗證舊密碼）
    """
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    error_message   = None
    success_message = None

    conn = get_user_db()
    cur  = conn.cursor()

    # 先讀取目前使用者資料（GET 用）
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
        # 資料找不到（罕見情況），清除 session 並登出
        conn.close()
        session.clear()
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        action = request.form.get("action")

        # ---------- 更新基本資料 ----------
        if action == "update_profile":
            full_name = request.form.get("full_name", "").strip()
            email     = request.form.get("email", "").strip()

            # 若有填 Email，檢查是否已被其他帳號使用
            if email:
                cur.execute(
                    """
                    SELECT id FROM User_profile
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

        # ---------- 更改密碼 ----------
        elif action == "change_password":
            current_password     = request.form.get("current_password", "")
            new_password         = request.form.get("new_password", "")
            new_password_confirm = request.form.get("new_password_confirm", "")

            # 重新從 DB 讀取最新的 password_hash（防止資料被同時修改）
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

        # POST 後重新讀取最新資料（讓畫面顯示更新後的值）
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

    # 將資料整理成模板用的字典格式
    user = {
        "id":               row["id"],
        "username":         row["account"],       # 模板用 user['username']
        "full_name":        row["full_name"] or "",
        "email":            row["email"],
        "role":             row["role"],
        "registration_key": row["registration_key"],
    }

    return render_template(
        "user/profile.html",
        user=user,
        error_message=error_message,
        success_message=success_message,
    )


# =============================================================
# 一般使用者（customer）註冊
# =============================================================

@auth_bp.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    """
    一般使用者註冊。
    不需要任何金鑰，任何人都可以申請 customer 帳號。
    欄位：帳號、Email、密碼、姓名（可選）
    """
    error_message   = None
    success_message = None

    if request.method == "POST":
        account   = request.form.get("account", "").strip()
        email     = request.form.get("email", "").strip()
        password  = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip() or None  # 空字串轉 None

        if not account or not email or not password:
            error_message = "請完整填寫帳號、密碼與Email。"
        else:
            conn = get_user_db()
            cur  = conn.cursor()

            # 檢查帳號或 Email 是否已存在
            cur.execute(
                "SELECT 1 FROM User_profile WHERE account = ? OR email = ?",
                (account, email),
            )
            exists = cur.fetchone()

            if exists:
                error_message = "帳號或 Email 已被使用，請改用其他。"
            else:
                # 產生隨機 user_id（12 位 hex 字串）
                user_id  = secrets.token_hex(6)
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
                        "customer",   # 角色固定為 customer
                        None,         # 一般使用者沒有金鑰
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


# =============================================================
# 工廠管理者（admin）註冊
# =============================================================

@auth_bp.route("/register/manager", methods=["GET", "POST"])
def register_manager():
    """
    工廠管理者（admin）註冊。
    需要輸入「工廠負責人金鑰」，金鑰存在 User_Data.db 的 registration_key 資料表中。
    欄位：帳號、Email、密碼、姓名（可選）、工廠負責人金鑰
    """
    error_message   = None
    success_message = None

    if request.method == "POST":
        account     = request.form.get("account", "").strip()
        email       = request.form.get("email", "").strip()
        password    = request.form.get("password", "")
        full_name   = request.form.get("full_name", "").strip() or None
        factory_key = request.form.get("factory_key", "").strip()

        if not account or not email or not password or not factory_key:
            error_message = "請完整填寫帳號、密碼、Email與工廠負責人金鑰。"
        else:
            conn = get_user_db()
            cur  = conn.cursor()

            # 步驟 1：驗證金鑰是否存在於 registration_key 資料表
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
                # 步驟 2：確認帳號或 Email 未被使用
                cur.execute(
                    "SELECT 1 FROM User_profile WHERE account = ? OR email = ?",
                    (account, email),
                )
                exists = cur.fetchone()

                if exists:
                    error_message = "帳號或 Email 已被使用，請改用其他。"
                else:
                    user_id  = secrets.token_hex(6)
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
                            "admin",       # 角色設定為 admin
                            factory_key,   # 把使用的金鑰存起來，方便日後追蹤
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


# =============================================================
# 開發用：資料庫連線測試
# =============================================================

@auth_bp.route("/debug_db")
def debug_db():
    """
    開發測試用路由。
    顯示 User_profile 資料表前 5 筆資料，確認 DB 連線正常。
    正式部署前建議移除或加上權限保護。
    """
    conn = get_user_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, account FROM User_profile LIMIT 5")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return "Database connected, but User_profile table is empty."

    lines = [f"{row['id']} - {row['account']}" for row in rows]
    return "<br>".join(lines)
