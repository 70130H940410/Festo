import sys
sys.path.append("/workspace/tutorials/Festo/shopping_website")
from core.db import get_order_mgmt_db

order_db = get_order_mgmt_db()
rows = order_db.execute("SELECT piece_no, step_order, state FROM piece_step_progress WHERE order_id='LINE-0008' AND piece_no=1").fetchall()
for r in rows:
    print(dict(r))

print("\nStation State:")
stations = order_db.execute("SELECT * FROM station_state").fetchall()
for s in stations:
    print(dict(s))
