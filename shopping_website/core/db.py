# core/db.py
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

USER_DB_PATH = os.path.join(BASE_DIR, "database", "User_Data.db")
PRODUCT_DB_PATH = os.path.join(BASE_DIR, "database", "product.db")


def get_user_db():
    conn = sqlite3.connect(USER_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_product_db():
    conn = sqlite3.connect(PRODUCT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
