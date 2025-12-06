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

<<<<<<< HEAD
=======
USER_DB_PATH = os.path.join(BASE_DIR, "database", "User_Data.db")
PRODUCT_DB_PATH = os.path.join(BASE_DIR, "database", "product.db")


def get_user_db():
    """連到 User_Data.db（User_profile / registration_key）"""
    conn = sqlite3.connect(USER_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_product_db():
    """連到 product.db（products）"""
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
    - 第一次進來 show_loader = True（給 index.html 顯示開場動畫）
    """
    first_visit = not session.get("seen_index")
    if first_visit:
        session["seen_index"] = True
    return render_template("index.html", show_loader=first_visit)


# =========================
# 共用 decorator
# =========================

def login_required(view_func):
    """需要登入才能看的頁面"""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper


def manager_required(view_func):
    """必須是 manager 的頁面"""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if session.get("role") != "manager":
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapper


# =========================
# 登入 / 登出
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
            # 用 account 欄位當登入帳號
            cur.execute(
                """
<<<<<<< HEAD
                SELECT id, account, password_hash, role
=======
                SELECT id, account, password_hash, role, full_name
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
                FROM User_profile
                WHERE account = ?
                """,
                (username,),
            )
            row = cur.fetchone()
            conn.close()

            if row and check_password_hash(row["password_hash"], password):
                session["user_id"] = row["id"]
                session["username"] = row["account"]
<<<<<<< HEAD
=======
                session["full_name"] = row["full_name"]
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
                session["role"] = row["role"]

                # 依角色導向
                if row["role"] == "manager":
                    return redirect(url_for("manager_inventory"))
                else:
                    return redirect(url_for("order_page"))
            else:
                error_message = "帳號或密碼錯誤。"

    return render_template(
        "auth/login.html",
        error_message=error_message,
        success_message=success_message,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# =========================
# 註冊：一般使用者（customer）
# =========================

@app.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    """
    寫入 User_profile：
    - id: uuid4 字串
    - account: 使用者帳號
<<<<<<< HEAD
=======
    - full_name: 中文姓名
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
    - email
    - password_hash
    - role: 'customer'
    - registration_key: NULL
    """
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()  # 目前不存 DB

        if not username or not password:
            error_message = "帳號與密碼為必填。"
        else:
            conn = get_user_db()
            cur = conn.cursor()

            # 檢查帳號是否重複（account 欄位）
            cur.execute(
                "SELECT id FROM User_profile WHERE account = ?",
                (username,),
            )
            exists = cur.fetchone()

            if exists:
                error_message = "此帳號已被使用，請換一個。"
                conn.close()
            else:
                user_id = uuid.uuid4().hex
                password_hash = generate_password_hash(password)
                cur.execute(
                    """
                    INSERT INTO User_profile
<<<<<<< HEAD
                        (id, account, email, password_hash, role, registration_key)
                    VALUES (?, ?, ?, ?, 'customer', NULL)
                    """,
                    (user_id, username, email, password_hash),
=======
                        (id, account, full_name, email, password_hash, role, registration_key)
                    VALUES (?, ?, ?, ?, ?, 'customer', NULL)
                    """,
                    (user_id, username, full_name, email, password_hash),
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
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


# =========================
# 註冊：工廠管理者（manager，有金鑰）
# =========================

@app.route("/register/manager", methods=["GET", "POST"])
def register_manager():
    """
    role = 'manager'
    - 需要在 registration_key 表裡找到對應的 registration_key
    - 註冊成功後，User_profile.registration_key 存該金鑰
    """
    error_message = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        email = request.form.get("email", "").strip()
        full_name = request.form.get("full_name", "").strip()  # 目前不存 DB
        factory_key = request.form.get("factory_key", "").strip()

        if not username or not password or not factory_key:
            error_message = "帳號、密碼與工廠金鑰為必填。"
        else:
            conn = get_user_db()
            cur = conn.cursor()

            # 1. 檢查金鑰是否存在 registration_key 表
            cur.execute(
                """
                SELECT Manager_name
                FROM registration_key
                WHERE registration_key = ?
                """,
                (factory_key,),
            )
            key_row = cur.fetchone()

            if not key_row:
                error_message = "工廠負責人金鑰錯誤，請確認後再試。"
                conn.close()
            else:
                # 2. 檢查 account 是否已存在
                cur.execute(
                    "SELECT id FROM User_profile WHERE account = ?",
                    (username,),
                )
                exists = cur.fetchone()

                if exists:
                    error_message = "此帳號已被使用，請換一個。"
                    conn.close()
                else:
                    user_id = uuid.uuid4().hex
                    password_hash = generate_password_hash(password)
                    cur.execute(
                        """
                        INSERT INTO User_profile
<<<<<<< HEAD
                            (id, account, email, password_hash, role, registration_key)
                        VALUES (?, ?, ?, ?, 'manager', ?)
                        """,
                        (user_id, username, email, password_hash, factory_key),
=======
                            (id, account, full_name, email, password_hash, role, registration_key)
                        VALUES (?, ?, ?, ?, ?, 'manager', ?)
                        """,
                        (user_id, username, full_name, email, password_hash, factory_key),
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
                    )
                    conn.commit()
                    conn.close()

                    return redirect(url_for("login"))

    return render_template(
        "auth/register_manager.html",
        error_message=error_message,
    )


# =========================
# 個人資料頁
# =========================

@app.route("/user/profile", methods=["GET", "POST"])
@login_required
def user_profile():
    """
    用 id 找 User_profile：
<<<<<<< HEAD
    - account 當 username 顯示
    - email 可修改
    - 密碼可修改
    - full_name 目前沒有存 DB，先給空字串
=======
    - account 當 username 顯示（不可改）
    - full_name / email 可修改
    - 密碼可修改
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
    """
    user_id = session.get("user_id")

    conn = get_user_db()
    cur = conn.cursor()

    cur.execute(
        """
<<<<<<< HEAD
        SELECT id, account, email, role
=======
        SELECT id, account, full_name, email, role
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
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
            email = request.form.get("email", "").strip()
<<<<<<< HEAD
            cur.execute(
                """
                UPDATE User_profile
                SET email = ?
                WHERE id = ?
                """,
                (email, user_id),
            )
            conn.commit()
            success_message = "基本資料已更新。"
=======

            # 1. 檢查這個 Email 有沒有被「其他帳號」使用
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
                # 2. 安全地更新自己的 full_name 與 email
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
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0

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

    # 重新讀一次最新資料
    cur.execute(
        """
<<<<<<< HEAD
        SELECT id, account, email, role
=======
        SELECT id, account, full_name, email, role
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
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
<<<<<<< HEAD
        "email": row["email"],
        "full_name": "",  # 目前未存
=======
        "full_name": row["full_name"] or "",
        "email": row["email"],
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
        "role": row["role"],
    }

    # session 裡順便更新一下 full_name，之後 navbar 如果要秀名字比較好用
    session["full_name"] = user["full_name"]

    return render_template(
        "user/profile.html",
        user=user,
        error_message=error_message,
        success_message=success_message,
    )


# =========================
# 前台：下單 / 製程 / 模擬
# =========================

@app.route("/order", methods=["GET", "POST"])
@login_required
def order_page():
    """
    下單頁：
    - GET：顯示產品列表 + 數量輸入格
    - POST：檢查每個產品的數量，存到 session["current_order_items"]，然後導到製程規劃頁
    """
    # 先把產品列表抓出來（不管 GET / POST 都會用到）
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

    error_message = None

    if request.method == "POST":
        selected_items = []

        for p in products:
            field_name = f"qty_{p['id']}"
            qty_str = request.form.get(field_name, "").strip()
            if qty_str == "" or qty_str == "0":
                continue

            # 檢查數量是否為整數
            try:
                qty = int(qty_str)
            except ValueError:
                error_message = f"{p['name']} 的數量請輸入整數。"
                break

            if qty < 0:
                error_message = f"{p['name']} 的數量不可為負。"
                break

            if qty > p["stock"]:
                error_message = f"{p['name']} 的數量超過庫存（最多 {p['stock']} 件）。"
                break

            if qty > 0:
                selected_items.append({
                    "id": p["id"],
                    "name": p["name"],
                    "quantity": qty,
                })

        if not error_message:
            if not selected_items:
                error_message = "請至少選擇一項產品。"
            else:
                # 將本次選的產品與數量暫存在 session，給製程規劃頁使用
                session["current_order_items"] = selected_items
                return redirect(url_for("process_plan"))

    return render_template(
        "order/order_page.html",
        products=products,
        error_message=error_message,
    )


@app.route("/process-plan", methods=["GET", "POST"])
@login_required
def process_plan():
    """
    製程規劃頁：
    - 從 session["current_order_items"] 讀取本次訂單摘要
    - 若 session 沒東西，退回 demo 資料（避免直接輸入網址爆掉）
    """
    # 標準製程（之後可從 DB 讀）
    standard_steps = [
        {"step_order": 1, "step_name": "揀料（上蓋 / 下蓋 / 保險絲 / 電路板）", "estimated_time_sec": 5},
        {"step_order": 2, "step_name": "組裝", "estimated_time_sec": 10},
        {"step_order": 3, "step_name": "電性測試", "estimated_time_sec": 8},
        {"step_order": 4, "step_name": "包裝", "estimated_time_sec": 5},
    ]

    # 從 session 取得剛剛在 /order 選的產品
    order_items_summary = session.get("current_order_items")

    # 如果沒有（例如直接打網址進來），就給一組 demo 避免報錯
    if not order_items_summary:
        order_items_summary = [
            {"name": "Basic Fuse Box - Black", "quantity": 3},
        ]

    return render_template(
        "order/process_plan.html",
        standard_steps=standard_steps,
        order_items_summary=order_items_summary,
    )


@app.route("/factory/simulate")
@login_required
def factory_simulate():
    """
    工廠運作模擬頁：
    目前用示意資料，之後接 MES / PLC 更新狀態。
    """
    order_info = {
        "id": 1,
<<<<<<< HEAD
        "user_name": session.get("username", "Demo User"),
=======
        "user_name": session.get("full_name") or session.get("username", "Demo User"),
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
        "status": "in_progress",
    }

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
# 管理者後台
# =========================

@app.route("/manager/inventory")
@manager_required
def manager_inventory():
    """
    庫存管理頁：
    目前先純顯示 HTML，之後再接 inventory 表。
    """
    return render_template("manager/inventory.html")


@app.route("/manager/process-templates")
@manager_required
def manager_process_templates():
    """
    製程模板管理頁：
    先用 demo 資料顯示表格。
    """
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
<<<<<<< HEAD
            "name": "高強度測試流程",
            "steps": [
                "揀料",
                "組裝",
                "高温燒機測試",
=======
            "name": "高溫壽命測試流程",
            "steps": [
                "揀料",
                "組裝",
                "高溫燒機測試",
>>>>>>> d3d99d309c302ef9fb96efd84fb89657e60ec7f0
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
>>>>>>> origin/main

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)


