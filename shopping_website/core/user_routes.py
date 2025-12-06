# core/user_routes.py
from flask import Blueprint, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from . import login_required
from .db import get_user_db

user_bp = Blueprint("user", __name__, url_prefix="/user")


@user_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user_id = session.get("user_id")

    conn = get_user_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, account, full_name, email, role
        FROM User_profile
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        session.clear()
        from flask import redirect, url_for
        return redirect(url_for("auth.login"))

    error_message = None
    success_message = None

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_profile":
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip()

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

    cur.execute(
        """
        SELECT id, account, full_name, email, role
        FROM User_profile
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()

    user = {
        "id": row["id"],
        "username": row["account"],
        "full_name": row["full_name"] or "",
        "email": row["email"],
        "role": row["role"],
    }

    session["full_name"] = user["full_name"]

    return render_template(
        "user/profile.html",
        user=user,
        error_message=error_message,
        success_message=success_message,
    )
