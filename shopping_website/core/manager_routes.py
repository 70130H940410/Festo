# core/manager_routes.py
# 負責管理者後台：庫存管理 & 製程模板管理

from flask import Blueprint, render_template

from . import manager_required

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")


@manager_bp.route("/inventory")
@manager_required
def manager_inventory():
    """
    庫存管理頁：
    目前先純顯示 HTML，之後再接 inventory 表。
    """
    return render_template("manager/inventory.html")


@manager_bp.route("/process-templates")
@manager_required
def manager_process_templates():
    """
    製程模板管理頁：
    先用 demo 資料顯示表格。
    之後可以改成從資料庫讀 process_templates / process_template_steps。
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
            "name": "高溫壽命測試流程",
            "steps": [
                "揀料",
                "組裝",
                "高溫燒機測試",
                "電性測試",
                "包裝",
            ],
        },
    ]

    return render_template(
        "manager/process_templates.html",
        templates=templates,
    )
