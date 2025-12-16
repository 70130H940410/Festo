# core/db.py
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

USER_DB_PATH = os.path.join(BASE_DIR, "database", "User_Data.db")
PRODUCT_DB_PATH = os.path.join(BASE_DIR, "database", "product.db")
ORDER_MGMT_DB_PATH = os.path.join(BASE_DIR, "database", "order_management.db")


def get_user_db():
    conn = sqlite3.connect(USER_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_product_db():
    conn = sqlite3.connect(PRODUCT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_order_mgmt_db():
    """管理者訂單總覽用的 DB:order_management.db"""
    conn = sqlite3.connect(ORDER_MGMT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

