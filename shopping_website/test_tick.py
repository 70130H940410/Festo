import sys
sys.path.append("/workspace/tutorials/Festo/shopping_website")
from core.db import get_order_mgmt_db, get_product_db
from core.factory_routes import _tick_once_for_order, _get_step_station_map

order_db = get_order_mgmt_db()
product_db = get_product_db()

step_map = _get_step_station_map(product_db)
print("Step station map:", step_map)

print("\nPending steps for LINE-0008:")
pending = order_db.execute(
    "SELECT piece_no, step_order, state FROM piece_step_progress WHERE order_id='LINE-0008' AND state='pending' LIMIT 10"
).fetchall()
for p in pending:
    print(dict(p))

print("\nExecuting _tick_once_for_order for LINE-0008:")
dispatched = _tick_once_for_order(order_db, product_db, "LINE-0008")
print("Dispatched:", dispatched)

order_db.close()
product_db.close()
