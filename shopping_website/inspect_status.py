import sys
import os
sys.path.append("/workspace/tutorials/Festo/shopping_website")
from core.db import get_order_mgmt_db, get_supabase_client

def inspect_db():
    conn = get_order_mgmt_db()
    cur = conn.cursor()
    print("=== Order List in order_management.db ===")
    orders = cur.execute("SELECT order_id, date, status, source, mes_ono, supabase_order_id, amount, step_name FROM order_list").fetchall()
    for o in orders:
        print(dict(o))
        
    print("\n=== Piece Step Progress (count per order) ===")
    progress = cur.execute("SELECT order_id, state, count(*) as cnt FROM piece_step_progress GROUP BY order_id, state").fetchall()
    for p in progress:
        print(dict(p))

    print("\n=== Station State ===")
    stations = cur.execute("SELECT station, current_order_id, current_piece_no, current_step_order, busy_until FROM station_state").fetchall()
    for s in stations:
        print(dict(s))
        
    conn.close()

    sb = get_supabase_client()
    if sb:
        print("\n=== Supabase tbl_order ===")
        tbl_o = sb.table("tbl_order").select("*").order("ono", desc=True).limit(5).execute()
        for r in (tbl_o.data or []):
            print(r)
            
        print("\n=== Supabase line_orders ===")
        lo = sb.table("line_orders").select("id, client_id, status, created_at").order("id", desc=True).limit(5).execute()
        for r in (lo.data or []):
            print(r)

if __name__ == "__main__":
    inspect_db()
