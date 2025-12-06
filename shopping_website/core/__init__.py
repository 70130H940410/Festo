# core/__init__.py
from functools import wraps
from flask import session, redirect, url_for


def login_required(view_func):
    """一般登入檢查：只要有登入就可以使用"""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            # Blueprint 名稱是 auth → endpoint 就是 auth.login
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)

    return wrapper


def manager_required(view_func):
    """
    管理者權限檢查：
    1. 沒登入 → 先去登入頁
    2. 有登入但不是 admin → 擋掉（這裡簡單導回首頁，你也可以改成 403 頁面）
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login"))

        role = session.get("role")
        if role != "admin":
            # 沒有管理者權限，導回首頁或別的頁面
            return redirect(url_for("index"))

        return view_func(*args, **kwargs)

    return wrapper



