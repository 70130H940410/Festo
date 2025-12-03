from flask import Flask, render_template, redirect, url_for, session

# --- 建立 Flask App ---
app = Flask(__name__)
app.secret_key = "CHANGE_ME_LATER"   # 之後再改成安全一點


# --- 首頁 ---
@app.route("/")
def index():
    # 第一次進來：session 裡沒有這個 key
    first_visit = not session.get("seen_index_loader", False)
    # 之後就記錄起來
    session["seen_index_loader"] = True

    return render_template("index.html", show_loader=first_visit)


# --- auth 區（先做簡單版，之後你可以拆到 core/auth_routes.py） ---
@app.route("/login", methods=["GET", "POST"])
def login():
    # 現在先只顯示畫面，不做真正登入
    return render_template("auth/login.html")


@app.route("/logout")
def logout():
    # 現在先直接跳回首頁，之後再清 session
    return redirect(url_for("index"))


@app.route("/register/customer", methods=["GET", "POST"])
def register_customer():
    return render_template("auth/register_customer.html")


@app.route("/register/manager", methods=["GET", "POST"])
def register_manager():
    return render_template("auth/register_manager.html")


# --- 下單相關 ---
@app.route("/order", methods=["GET", "POST"])
def order_page():
    # 先給假資料，之後再改成從 DB 抓 products
    demo_products = [
        {"id": 1, "name": "Basic Fuse Box - Black", "description": "黑色上蓋標準保險絲盒", "base_price": 100},
        {"id": 2, "name": "Basic Fuse Box - Blue",  "description": "藍色上蓋標準保險絲盒", "base_price": 100},
        {"id": 3, "name": "Basic Fuse Box - White", "description": "白色上蓋標準保險絲盒", "base_price": 100},
    ]
    return render_template("order/order_page.html", products=demo_products)


@app.route("/process_plan", methods=["GET", "POST"])
def process_plan():
    # 之後會用 session 帶入訂單內容，現在放簡單假資料
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


# --- 模擬產線頁面 ---
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


# --- 管理者後台：先做空頁 ---
@app.route("/manager/inventory")
def manager_inventory():
    return render_template("manager/inventory.html")


@app.route("/manager/process_templates")
def manager_process_templates():
    return render_template("manager/process_templates.html")


# --- 使用者個人資料頁（先做空頁） ---
@app.route("/user/profile")
def user_profile():
    return render_template("user/profile.html")


# Flask 主程式入口
if __name__ == "__main__":
    app.run(debug=True)
