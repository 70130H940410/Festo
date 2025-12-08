# core/order_routes.py
# 負責「我要下單」與「製程規劃」頁面

from flask import Blueprint, render_template, request, redirect, url_for, session

from . import login_required
from .db import get_product_db

order_bp = Blueprint("order", __name__)


@order_bp.route("/order", methods=["GET", "POST"])
@login_required
def order_page():
    """
    下單頁：
    - GET:顯示產品列表 + 數量輸入格
    - POST:檢查每個產品的數量，存到 session["current_order_items"]，然後導到製程規劃頁
    """

    # 先把產品列表抓出來（不管 GET / POST 都會用到）
    conn = get_product_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            id,
            name,
            description,
            base_price,
            TOTAL AS stock_total    -- 資料庫欄位叫 TOTAL，這裡取一個好記的別名
        FROM products
        ORDER BY id
        """
    )
    rows = cur.fetchall()
    conn.close()

    # 把資料整理成給模板用的格式
    # 注意：雖然 DB 欄位是 TOTAL，我們在 Python 裡統一叫做 p["stock"]
    products = [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "base_price": row["base_price"],
            "stock": row["stock_total"],  # 這裡對應到上面的別名
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
                selected_items.append(
                    {
                        "id": p["id"],
                        "name": p["name"],
                        "quantity": qty,
                    }
                )

        if not error_message:
            if not selected_items:
                error_message = "請至少選擇一項產品。"
            else:
                # 將本次選的產品與數量暫存在 session，給製程規劃頁使用
                session["current_order_items"] = selected_items
                return redirect(url_for("order.process_plan"))

    return render_template(
        "order/order_page.html",
        products=products,
        error_message=error_message,
    )


@order_bp.route("/process-plan", methods=["GET", "POST"])
@login_required
def process_plan():
    """
    製程規劃頁：
    - 從 session["current_order_items"] 讀取本次訂單摘要
    - 若 session 沒東西，退回 demo 資料（避免直接輸入網址爆掉）
    """
    # 標準製程（之後可從 DB 讀）
    standard_steps = [
        {
            "step_order": 1,
            "step_name": "訂單與供料 (Order & Dispensing)",
            "station": "ASRS 自動倉儲站 (Stopper 1 / A1)",
            "description": "由外部訂單觸發，ASRS 從貨架取出載有上蓋的托盤並送上輸送帶，流程開始。",
            "estimated_time_sec": 5,
        },
        {
            "step_order": 2,
            "step_name": "尺寸量測 (Measuring)",
            "station": "量測工作站 (Measuring Module / B)",
            "description": "使用雷射距離感測器對上蓋進行類比差分量測，確認尺寸是否符合規格。",
            "estimated_time_sec": 5,
        },
        {
            "step_order": 3,
            "step_name": "鑽孔加工 (Drilling)",
            "station": "鑽孔工作站 (Drilling CPS / C)",
            "description": "雙鑽軸模擬 X / Z 軸移動，於上蓋鑽出兩對孔位。",
            "estimated_time_sec": 8,
        },
        {
            "step_order": 4,
            "step_name": "機器人組裝 (Robot Assembly)",
            "station": "機器人組裝室 (Robot Assembly / D)",
            "description": "Mitsubishi 六軸機器人將 PCB 安裝至上蓋，並將保險絲插入電路板。",
            "estimated_time_sec": 10,
        },
        {
            "step_order": 5,
            "step_name": "視覺檢測 (Camera Inspection)",
            "station": "視覺檢測工作站 (Camera Inspection / E)",
            "description": "工業相機檢查保險絲是否安裝、位置是否正確，並判定良品 / 不良品。",
            "estimated_time_sec": 6,
        },
        {
            "step_order": 6,
            "step_name": "放置下蓋 (Place Lower Cover)",
            "station": "盒匣 / 堆疊工作站 (Stacking Magazine / F)",
            "description": "從堆疊模組分離下蓋，放置到托盤上的工件，準備與上蓋結合。",
            "estimated_time_sec": 5,
        },
        {
            "step_order": 7,
            "step_name": "氣壓壓合 (Pressing)",
            "station": "氣壓壓製工作站 (Muscle Press / G)",
            "description": "利用氣壓肌腱 (Fluidic Muscle) 將上蓋與下蓋緊密壓合，完成外殼組裝。",
            "estimated_time_sec": 6,
        },
        {
            "step_order": 8,
            "step_name": "烘烤加熱 (Heating)",
            "station": "烘烤加熱工作站 (Heating Oven / H)",
            "description": "隧道式烤箱模擬膠合固化 / 熱處理，產品在受控溫度曲線下進行加熱。",
            "estimated_time_sec": 12,
        },
        {
            "step_order": 9,
            "step_name": "成品入庫 (Storage)",
            "station": "ASRS 自動倉儲站 (Stopper 2 / A2)",
            "description": "完成工序的成品返回 ASRS，由倉儲機器人放回指定貨位，完成生產循環。",
            "estimated_time_sec": 5,
        },
    ]

    order_items_summary = session.get("current_order_items")
    if not order_items_summary:
        order_items_summary = [
            {"name": "Basic Fuse Box - Black", "quantity": 3},
        ]

    return render_template(
        "order/process_plan.html",
        standard_steps=standard_steps,
        order_items_summary=order_items_summary,
    )

