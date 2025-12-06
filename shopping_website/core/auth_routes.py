# core/auth_routes.py
# 處理登入 / 登出 / 註冊 / 個人資料相關路由

from __future__ import annotations

import os
import sqlite3
import uuid
import hashlib
import base64
from typing import Optional

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)

from .db import get_user_db
from . import login_required

auth_bp = Blueprint("auth", __name__)


# ----------------- 密碼相關工具 -----------------


def _hash_scrypt(password: str, salt: bytes) -> bytes:
    """內部使用：用 scrypt 算出 key。"""
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
    )


def hash_password(password: str) -> str:
    """
    產生密碼雜湊，格式：
    scrypt$<salt_base64>$<hash_base64>
    """
    salt = os.urandom(16)
    key = _hash_scrypt(password, salt)
    return "scrypt${}${}".format(
        base64.b64encode(salt).decode("utf-8") + "$",
        base64.b64encode(key).decode("utf-8"),
    )


def verify_password(password: str, stored: str) -> bool:
    """
    驗證密碼是否正確。
    目前只支援上面 hash_password 產生的格式。
    """
    try:
        algo, salt_b64, key_b64 = stored.split("$", 2)
    except ValueError:
        # 格式不對，直接視為錯誤
        return False

    if algo != "scrypt":
        return False

    try:
        salt = base64.b64decode(salt_b64)
        key = base64.b64decode(key_b64)
    except Exception:
        return False

    new_key = _hash_scrypt(password, salt)
    return hashlib.compare_digest(new_key, key)


def generate_user_id() -> str:
    """產生 User_profile.id 用的字串（和你目前資料庫 uuid 形式一致）。"""
    return uuid.uuid4().hex


# ----------------- 登入 / 登出 -----------------


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    登入：
    - 使用 account + password
    - 驗證成功後，將 user_id, account, role 放到 session
    """
    error: Optional[str] = None

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "").strip()

        if not account or not password:
            error = "請輸入帳號與密碼。"
        else:
            conn = get_user_db()
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM User_profile WHERE account = ?",
                (account,),
            )
            row = cur.fetchone()
            conn.close()

            if row is None:
                error = "查無此帳號。"
            else:
                if not verify_password(password, row["password_hash"]):
                    error = "密碼錯誤。"
                else:
                    # 登入成功
                    session["user_id"] = row["id"]
                    session["account"] = row["account"]
                    session["role"] = row["role"]
                    flash("登入成功。", "success")
                    return redirect(url_for("index"))

    return render_template("auth/login.html", error=error)


@auth_bp.route("/logout")
def logout():
    """登出：清掉 session。"""
    session.clear()
    flash("您已登出。", "info")
    return redirect(url_for("index"))


# ----------------- 一般使用者註冊 -----------------


@auth_bp.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    """
    一般使用者註冊：
    - 建立 role='customer' 的帳號
    - 不檢查工廠金鑰
    """
    error: Optional[str] = None

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "").strip()
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()

        if not account or not password or not email or not full_name:
            error = "所有欄位都必填。"
        else:
            conn = get_user_db()
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # 檢查 account 是否重複
            cur.execute(
                "SELECT 1 FROM User_profile WHERE account = ?",
                (account,),
            )
            if cur.fetchone():
                error = "此帳號已被使用。"

            # 檢查 email 是否重複
            if not error:
                cur.execute(
                    "SELECT 1 FROM User_profile WHERE email = ?",
                    (email,),
                )
                if cur.fetchone():
                    error = "此 Email 已被註冊。"

            # 建立帳號
            if not error:
                user_id = generate_user_id()
                password_hash = hash_password(password)

                cur.execute(
                    """
                    INSERT INTO User_profile
                        (id, account, email, password_hash, role, registration_key, full_name)
                    VALUES (?, ?, ?, ?, 'customer', NULL, ?)
                    """,
                    (user_id, account, email, password_hash, full_name),
                )
                conn.commit()
                conn.close()

                flash("一般使用者帳號建立成功，請用此帳號登入。", "success")
                return redirect(url_for("auth.login"))

            conn.close()

    return render_template("auth/register_customer.html", error=error)


# ----------------- 工廠管理者註冊 -----------------


@auth_bp.route("/register/manager", methods=["GET", "POST"])
def register_manager():
    """
    工廠管理者註冊：
    - 需要輸入「工廠負責人金鑰」
    - 從 User_Data.db 的 registration_key 表驗證金鑰
    - 通過後建立 role='admin' 的帳號
    """
    error: Optional[str] = None

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "").strip()
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()
        factory_key = request.form.get("factory_key", "").strip()

        # 基本欄位檢查
        if not account or not password or not email or not full_name or not factory_key:
            error = "所有欄位都必填。"
        else:
            conn = get_user_db()
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # 1) 檢查 account 是否存在
            cur.execute(
                "SELECT 1 FROM User_profile WHERE account = ?",
                (account,),
            )
            if cur.fetchone():
                error = "這個帳號已經被使用。"

            # 2) 檢查 email 是否存在
            if not error:
                cur.execute(
                    "SELECT 1 FROM User_profile WHERE email = ?",
                    (email,),
                )
                if cur.fetchone():
                    error = "這個 Email 已經被註冊。"

            # 3) 驗證工廠金鑰（使用既有的 registration_key 資料表）
            if not error:
                cur.execute(
                    """
                    SELECT 1
                    FROM registration_key
                    WHERE registration_key = ?
                    """,
                    (factory_key,),
                )
                key_row = cur.fetchone()
                if not key_row:
                    error = "工廠負責人金鑰錯誤，請確認或聯絡系統管理者。"

            # 4) 建立管理者帳號
            if not error:
                user_id = generate_user_id()
                password_hash = hash_password(password)

                cur.execute(
                    """
                    INSERT INTO User_profile
                        (id, account, email, password_hash, role, registration_key, full_name)
                    VALUES (?, ?, ?, ?, 'admin', ?, ?)
                    """,
                    (user_id, account, email, password_hash, factory_key, full_name),
                )
                conn.commit()
                conn.close()

                flash("工廠管理者帳號建立成功，請用此帳號登入。", "success")
                return redirect(url_for("auth.login"))

            conn.close()

    return render_template("auth/register_manager.html", error=error)
    

# ----------------- 個人資料頁 -----------------


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """
    個人資料頁：
    - 左邊區塊：顯示帳號、姓名、Email、身份
    - 右邊區塊：修改密碼
    """
    conn = get_user_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    user_id = session.get("user_id")

    # 先讀出目前使用者資料
    cur.execute(
        "SELECT * FROM User_profile WHERE id = ?",
        (user_id,),
    )
    user = cur.fetchone()
    if not user:
        conn.close()
        flash("找不到使用者資料，請重新登入。", "error")
        return redirect(url_for("auth.login"))

    basic_error = None
    pwd_error = None
    pwd_success = None

    if request.method == "POST":
        form_type = request.form.get("form_type")

        # 1) 更新基本資料（姓名 / email）
        if form_type == "basic":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip()

            if not full_name or not email:
                basic_error = "姓名與 Email 不可為空。"
            else:
                # 檢查 email 是否被別人使用
                cur.execute(
                    """
                    SELECT 1 FROM User_profile
                    WHERE email = ? AND id != ?
                    """,
                    (email, user_id),
                )
                if cur.fetchone():
                    basic_error = "這個 Email 已經被其他帳號使用。"

            if not basic_error:
                cur.execute(
                    """
                    UPDATE User_profile
                    SET full_name = ?, email = ?
                    WHERE id = ?
                    """,
                    (full_name, email, user_id),
                )
                conn.commit()
                flash("基本資料已更新。", "success")

                # 重新取得最新資料
                cur.execute(
                    "SELECT * FROM User_profile WHERE id = ?",
                    (user_id,),
                )
                user = cur.fetchone()

        # 2) 修改密碼
        elif form_type == "password":
            current_pwd = request.form.get("current_password", "").strip()
            new_pwd = request.form.get("new_password", "").strip()
            confirm_pwd = request.form.get("confirm_password", "").strip()

            if not current_pwd or not new_pwd or not confirm_pwd:
                pwd_error = "所有欄位都必填。"
            elif not verify_password(current_pwd, user["password_hash"]):
                pwd_error = "目前密碼錯誤。"
            elif new_pwd != confirm_pwd:
                pwd_error = "兩次輸入的新密碼不一致。"
            else:
                new_hash = hash_password(new_pwd)
                cur.execute(
                    """
                    UPDATE User_profile
                    SET password_hash = ?
                    WHERE id = ?
                    """,
                    (new_hash, user_id),
                )
                conn.commit()
                pwd_success = "密碼已更新。"

    conn.close()

    return render_template(
        "auth/profile.html",
        user=user,
        basic_error=basic_error,
        pwd_error=pwd_error,
        pwd_success=pwd_success,
    )



