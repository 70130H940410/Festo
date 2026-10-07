import sys
sys.path.append("/workspace/tutorials/Festo/shopping_website")
from core.db import get_order_mgmt_db

conn = get_order_mgmt_db()
cur = conn.cursor()

stations = cur.execute("SELECT station, current_order_id, current_piece_no, current_step_order, busy_until FROM station_state").fetchall()
print("=== Active Station Dispatch ===")
for s in stations:
    if s["current_order_id"]:
        print(f"🏭 [{s['station']}] 正在加工訂單 {s['current_order_id']} 第 {s['current_piece_no']} 件 (步驟 {s['current_step_order']})")
    else:
        print(f"⚪ [{s['station']}] 空閒待命中")

cur.execute("SELECT status, count(*) as cnt FROM order_list GROUP BY status")
print("\n=== Orders Status Breakdown ===")
for r in cur.fetchall():
    print(dict(r))

conn.close()
