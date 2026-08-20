# =============================================================
# core/__init__.py
# 權限裝飾器（Decorators）模組
# ----------------------------------------------------------
# 定義兩個常用的路由保護裝飾器：
#   - login_required    : 需要登入才能存取的頁面
#   - manager_required  : 需要管理者（admin）權限才能存取的頁面
# =============================================================

from functools import wraps
from flask import session, redirect, url_for


def login_required(view_func):
    """
    一般登入檢查裝飾器。
    只要 session 裡有 user_id 就允許存取，否則導向登入頁。
    使用方式：@login_required（放在路由下方）
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            # 未登入 → 導向 auth Blueprint 的 login 頁
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)

    return wrapper


def manager_required(view_func):
    """
    管理者權限檢查裝飾器。
    規則：
      1. 未登入 → 導向登入頁
      2. 已登入但角色不是 admin → 導向首頁（可改成 403 頁面）
      3. 已登入且是 admin → 允許存取
    使用方式：@manager_required（放在路由下方）
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        # 步驟 1：確認已登入
        if "user_id" not in session:
            return redirect(url_for("auth.login"))

        # 步驟 2：確認有 admin 角色
        role = session.get("role")
        if role != "admin":
            return redirect(url_for("index"))

        return view_func(*args, **kwargs)

    return wrapper
