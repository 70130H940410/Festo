import sys
sys.path.append("/workspace/tutorials/Festo/shopping_website")
from core.db import get_supabase_client

sb = get_supabase_client()
if sb:
    res = sb.table("line_orders").select("*").limit(1).execute()
    if res.data:
        print("line_orders columns:", list(res.data[0].keys()))
        print("Sample data:", res.data[0])
