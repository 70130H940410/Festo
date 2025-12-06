# core/factory_routes.py
# 負責「工廠運作模擬」頁面

from flask import Blueprint, render_template, session

from . import login_required

factory_bp = Blueprint("factory", __name__, url_prefix="/factory")


@factory_bp.route("/simulate")
@login_required
def simulate():
    """
    工廠運作模擬頁：
    目前用示意資料，之後接 MES / PLC 更新狀態。
    """
    order_info = {
        "id": 1,
        "user_name": session.get("full_name") or session.get("username", "Demo User"),
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
