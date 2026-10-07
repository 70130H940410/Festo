import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/workspace/tutorials/Line_Talker/.env")
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
sp = create_client(url, key)

# 查看 Supabase 上的工廠表
factory_tables = ["tbl_order", "tbl_order_pos", "tbl_buffer_pos", "tbl_part", "tbl_resource", "tbl_step_def", "line_orders", "orders"]

for t in factory_tables:
    try:
        res = sp.table(t).select("*").limit(3).execute()
        print(f"\n=== Table: {t} (Count returned: {len(res.data)}) ===")
        if res.data:
            print("Columns:", list(res.data[0].keys()))
            print("Sample row:", res.data[0])
    except Exception as e:
        print(f"Table {t} error:", e)
