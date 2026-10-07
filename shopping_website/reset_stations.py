import sys
sys.path.append("/workspace/tutorials/Festo/shopping_website")
from core.db import get_order_mgmt_db

conn = get_order_mgmt_db()
cur = conn.cursor()
cur.execute("UPDATE station_state SET is_error = 0, busy_until = NULL, current_order_id = NULL, current_piece_no = NULL, current_step_order = NULL")
conn.commit()

stations = cur.execute("SELECT station, is_error, busy_until FROM station_state").fetchall()
print("Stations reset successfully:")
for s in stations:
    print(dict(s))
conn.close()
