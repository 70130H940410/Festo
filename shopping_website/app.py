import os
import sqlite3

from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    session,
)

from werkzeug.security import generate_password_hash, check_password_hash


# ----------------- Flask 基本設定 -----------------
app = Flask(__name__)
# TODO: 之後換成更安全的亂數字串
app.secret_key = "CHANGE_THIS_TO_A_RANDOM_SECRET"


# ----------------- 資料庫連線工具 -----------------

# 專案根目錄：app.py 所在資料夾
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "shopping_data.db")


def get_db():
    """取得一個新的 SQLite 連線（用完記得關）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ----------------- 首頁 -----------------


@app.route("/")
def index():
    # 第一次進首頁時顯示 loader，之後就不顯示
    first_visit = not session.get("seen_index_loader", False)
    session["seen_index_loader"] = True

    return render_template("index.html", show_loader=first_visit)


# ----------------- Auth：登入 / 登出 / 註冊 -----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            error_message = "請輸入帳號與密碼。"
        else:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, username, password_hash, role FROM users WHERE username = ?",
                (username,),
            )
            row = cur.fetchone()
            conn.close()

            if row and check_password_hash(row["password_hash"], password):
                # 登入成功，寫入 session
                session["user_id"] = row["id"]
                session["username"] = row["username"]
                session["role"] = row["role"]

                # 依身分導向不同頁面
                if row["role"] == "manager":
                    return redirect(url_for("manager_inventory"))
                else:
                    return redirect(url_for("order_page"))
            else:
                error_message = "帳號或密碼錯誤。"

    return render_template("auth/login.html", error_message=error_message)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    error_message = None
    success_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()

        if not username or not password:
            error_message = "帳號與密碼為必填。"
        else:
            conn = get_db()
            cur = conn.cursor()
            # 檢查帳號是否已存在
            cur.execute("SELECT id FROM users WHERE username = ?", (username,))
            exists = cur.fetchone()

            if exists:
                error_message = "此帳號已被使用，請換一個。"
                conn.close()
            else:
                password_hash = generate_password_hash(password)
                cur.execute(
                    """
                    INSERT INTO users (username, password_hash, email, full_name, role)
                    VALUES (?, ?, ?, ?, 'customer')
                    """,
                    (username, password_hash, email, full_name),
                )
                conn.commit()
                conn.close()
                # 註冊成功，導向登入
                success_message = "註冊成功，請使用該帳號登入。"
                return render_template(
                    "auth/login.html",
                    success_message=success_message,
                )

    return render_template(
        "auth/register_customer.html",
        error_message=error_message,
    )


@app.route("/register/manager", methods=["GET", "POST"])
def register_manager():
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
            conn = get_db()
            cur = conn.cursor()

            # 檢查金鑰是否存在且啟用
            cur.execute(
                "SELECT id FROM factory_keys WHERE key_value = ? AND is_active = 1",
                (factory_key,),
            )
            key_row = cur.fetchone()

            if not key_row:
                error_message = "工廠負責人金鑰錯誤或已停用。"
                conn.close()
            else:
                # 檢查帳號是否已存在
                cur.execute("SELECT id FROM users WHERE username = ?", (username,))
                exists = cur.fetchone()

                if exists:
                    error_message = "此帳號已被使用，請換一個。"
                    conn.close()
                else:
                    password_hash = generate_password_hash(password)
                    cur.execute(
                        """
                        INSERT INTO users (username, password_hash, email, full_name, role)
                        VALUES (?, ?, ?, ?, 'manager')
                        """,
                        (username, password_hash, email, full_name),
                    )
                    conn.commit()
                    conn.close()
                    # 直接導到登入頁
                    return redirect(url_for("login"))

    return render_template(
        "auth/register_manager.html",
        error_message=error_message,
    )


# ----------------- 使用者個人資料頁 -----------------


@app.route("/user/profile", methods=["GET", "POST"])
def user_profile():
    # 必須登入
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, email, full_name, role FROM users WHERE id = ?",
        (user_id,),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        # 找不到帳號就強制登出
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
                "UPDATE users SET full_name = ?, email = ? WHERE id = ?",
                (full_name, email, user_id),
            )
            conn.commit()
            success_message = "基本資料已更新。"

        elif action == "change_password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            new_password_confirm = request.form.get("new_password_confirm", "")

            # 先查出原本的 hash
            cur.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
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
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (new_hash, user_id),
                )
                conn.commit()
                success_message = "密碼已更新。"

    # 重新拉一次（避免舊資料）
    cur.execute(
        "SELECT id, username, email, full_name, role FROM users WHERE id = ?",
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


# ----------------- 下單 / 製程 / 模擬（目前先 demo 用） -----------------


@app.route("/order", methods=["GET", "POST"])
def order_page():
    # 先給假產品資料，之後再從 DB 讀
    demo_products = [
        {"id": 1, "name": "Basic Fuse Box - Black", "description": "黑色上蓋標準保險絲盒", "base_price": 100},
        {"id": 2, "name": "Basic Fuse Box - Blue", "description": "藍色上蓋標準保險絲盒", "base_price": 100},
        {"id": 3, "name": "Basic Fuse Box - White", "description": "白色上蓋標準保險絲盒", "base_price": 100},
    ]
    return render_template("order/order_page.html", products=demo_products)


@app.route("/process_plan", methods=["GET", "POST"])
def process_plan():
    order_items_summary = [
        {"name": "Basic Fuse Box - Black", "quantity": 3},
    ]
    standard_steps = [
        {"step_order": 1, "step_name": "揀料（上蓋 / 下蓋 / 保險絲 / 電路板）", "estimated_time_sec": 5},
        {"step_order": 2, "step_name": "組裝", "estimated_time_sec": 10},
        {"step_order": 3, "step_name": "電性測試", "estimated_time_sec": 8},
        {"step_order": 4, "step_name": "包裝", "estimated_time_sec": 5},
    ]
    return render_template(
        "order/process_plan.html",
        order_items_summary=order_items_summary,
        standard_steps=standard_steps,
    )


@app.route("/factory/simulate")
def factory_simulate():
    order_info = {
        "id": 1,
        "user_name": "Demo User",
        "status": "in_progress",
    }
    steps = [
        {"step_order": 1, "step_name": "揀料（上蓋 / 下蓋 / 保險絲 / 電路板）", "status": "finished"},
        {"step_order": 2, "step_name": "組裝", "status": "running"},
        {"step_order": 3, "step_name": "電性測試", "status": "pending"},
        {"step_order": 4, "step_name": "包裝", "status": "pending"},
    ]
    return render_template("factory/simulate.html", order_info=order_info, steps=steps)


# ----------------- 管理者後台（目前先空殼） -----------------


@app.route("/manager/inventory")
def manager_inventory():
    return render_template("manager/inventory.html")


@app.route("/manager/process_templates")
def manager_process_templates():
    return render_template("manager/process_templates.html")


# ----------------- 主程式入口 -----------------

if __name__ == "__main__":
    # debug=True 方便開發時看到錯誤訊息
    app.run(debug=True)

