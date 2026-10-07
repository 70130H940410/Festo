import sys
sys.path.append("/workspace/tutorials/Festo/shopping_website")
from core.db import get_supabase_client

sb = get_supabase_client()
if sb:
    res = sb.table("tbl_order").select("*").limit(1).execute()
    if res.data:
        print("tbl_order columns:", list(res.data[0].keys()))
        print("Sample data:", res.data[0])
