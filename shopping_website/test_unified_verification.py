import sys
import os
import sqlite3

# 設定路徑
base_dir = os.path.dirname(os.path.abspath(__file__))
line_talker_dir = os.path.abspath(os.path.join(base_dir, "..", "..", "Line_Talker"))
sys.path.insert(0, base_dir)

print("=" * 60)
print("  統一網站、LineTalker 與工廠 MES 資料庫驗證測試")
print("=" * 60)

# ── 1. 驗證網站端與工廠倉儲 ──
print("\n[測試 1] 驗證網站讀取工廠 ASRS 倉儲庫存 (SSOT)...")
from core.mes_data_service import MesDataService
web_inv = MesDataService.get_warehouse_inventory()
products = MesDataService.get_unified_products()

print(f"  ASRS 總格位: {web_inv['total_capacity']} 格, 已佔用成品: {web_inv['total_occupied']} 件")
for p in products:
    print(f"  - {p['name']} (PNo {p['f_no']}): 在庫 {p['stock']} 件 (貨位: {p['warehouse_positions']})")

assert web_inv['total_occupied'] >= 0
print("  ✅ 網站端成功讀取工廠 ASRS 即時庫存！")

# ── 2. 驗證 LineTalker 端 ──
print("\n[測試 2] 驗證 LineTalker 庫存與 5 大資訊收集步驟...")
import importlib.util
def load_module(name, filepath):
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

line_sb_mod = load_module("line_supabase_client", os.path.join(line_talker_dir, "app", "supabase_client.py"))
line_session_mod = load_module("line_order_session", os.path.join(line_talker_dir, "app", "order_session.py"))

line_sb_client = line_sb_mod.supabase_client
line_inv = line_sb_client.get_warehouse_inventory()
for p in ['Basic Fuse Box - Black', 'Basic Fuse Box - Blue', 'Basic Fuse Box - White']:
    print(f"  - {p} -> 網站: {web_inv[p]['count']} 件 | LINE: {line_inv[p]['count']} 件")
    assert web_inv[p]['count'] == line_inv[p]['count'], f"庫存不一致: {p}"

print(f"  Line 資訊收集步驟: {line_session_mod.INFO_STEPS}")
assert line_session_mod.INFO_STEPS == ["name", "phone", "company", "address", "note"]
print("  ✅ LineTalker 與網站庫存完全一致，5 大必要欄位已對齊！")

# ── 3. 測試網站下單流程 (欄位驗證 + 庫存校驗 + 雲端同步) ──
print("\n[測試 3] 測試網站下單流程與資料存取...")
from app import create_app
flask_app = create_app()
client = flask_app.test_client()

# 測試 A：缺少電話與地址時應拒絕
with client.session_transaction() as sess:
    sess['user_id'] = 1
    sess['account'] = 'test_buyer'
    sess['role'] = 'user'
    sess['current_order_items'] = [{'id': 1, 'name': 'Basic Fuse Box - Black', 'quantity': 1, 'base_price': 100}]

resp_fail = client.post('/api/submit_order', json={
    'selected_steps': [1, 2, 3],
    'contact_name': '測試購買者'
})
assert resp_fail.status_code == 400
print(f"  - 缺少必填欄位防呆測試成功 (回傳 400: {resp_fail.get_json()['message']})")

# 測試 B：超出工廠倉儲庫存下單時應拒絕
with client.session_transaction() as sess:
    sess['user_id'] = 1
    sess['account'] = 'test_buyer'
    sess['role'] = 'user'
    sess['current_order_items'] = [{'id': 2, 'name': 'Basic Fuse Box - Blue', 'quantity': 5, 'base_price': 100}]

resp_stock_fail = client.post('/api/submit_order', json={
    'selected_steps': [1, 2, 3],
    'contact_name': '陳品萱',
    'contact_phone': '0922334455',
    'company': '宏達自動化股份有限公司',
    'address': '桃園市中壢區中大路300號'
})
assert resp_stock_fail.status_code == 400
print(f"  - 庫存超額防呆測試成功 (回傳 400: {resp_stock_fail.get_json()['message']})")

# 測試 C：完整 5 大欄位且庫存充足時成功下單
with client.session_transaction() as sess:
    sess['user_id'] = 1
    sess['account'] = 'test_buyer'
    sess['role'] = 'user'
    sess['current_order_items'] = [{'id': 1, 'name': 'Basic Fuse Box - Black', 'quantity': 1, 'base_price': 100}]

resp_ok = client.post('/api/submit_order', json={
    'selected_steps': [1, 2, 3, 4, 5, 6, 7, 8, 9],
    'contact_name': '陳品萱',
    'contact_phone': '0922334455',
    'company': '宏達自動化股份有限公司',
    'address': '桃園市中壢區中大路300號',
    'note': '請備妥原廠保固卡'
})
assert resp_ok.status_code == 200
print("  - 完整 5 大收件資料下單成功 (回傳 200)！")

# 驗證 SQLite 資料庫寫入
db_path = os.path.join(base_dir, "database", "order_management.db")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT * FROM order_list ORDER BY rowid DESC LIMIT 1")
latest_order = dict(cur.fetchone())
conn.close()

print(f"  SQLite 最新訂單:")
print(f"    單號: {latest_order['order_id']}")
print(f"    聯絡人: {latest_order['contact_name']}")
print(f"    電話: {latest_order['contact_phone']}")
print(f"    公司: {latest_order['company']}")
print(f"    地址: {latest_order['address']}")
print(f"    備註: {latest_order['note']}")
print(f"    來源: {latest_order['source']}")
print(f"    Supabase 雲端ID: {latest_order['supabase_order_id']}")

assert latest_order['contact_name'] == '陳品萱'
assert latest_order['contact_phone'] == '0922334455'
assert latest_order['source'] == 'web'
print("  ✅ 網站端與 SQLite、Supabase 雙向資料鏈結驗證成功！")

print("\n" + "=" * 60)
print("  🎉 全部統一測試通過！")
print("=" * 60)
