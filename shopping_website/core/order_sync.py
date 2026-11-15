# core/order_sync.py
"""
LineTalker 與網站訂單同步服務。
負責將 Supabase line_orders 的訂單同步至本地 SQLite order_management.db，
確保網站管理者能在後台完整查看與管理來自 LineTalker 的所有訂單。
"""

import json
from datetime import datetime
from typing import Dict, Any, List

from .db import get_order_mgmt_db, get_supabase_client


def sync_line_orders_to_order_list(order_id=None) -> int:
    """
    從 Supabase line_orders 拉取訂單並同步至本地 SQLite order_list。
    回傳新增/更新的筆數。
    """
    sb = get_supabase_client()
    if not sb:
        return 0

    try:
        # 從 Supabase line_orders 取出所有訂單
        query = sb.table("line_orders").select("*")
        if order_id is not None:
            lookup = get_order_mgmt_db()
            try:
                target = lookup.execute('SELECT supabase_order_id,status FROM order_list WHERE order_id=?', (order_id,)).fetchone()
            finally:
                lookup.close()
            if not target or not target['supabase_order_id'] or target['status'] in ('completed', 'cancelled', 'rejected'):
                return 0
            query = query.eq('id', target['supabase_order_id'])
        resp = query.order("id").execute()
        line_orders = resp.data or []
        if not line_orders:
            return 0

        conn = get_order_mgmt_db()
        cur = conn.cursor()

        # 確保必要欄位存在
        cols = [r[1] for r in cur.execute("PRAGMA table_info(order_list)").fetchall()]
        if "source" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN source TEXT DEFAULT 'web'")
        if "mes_ono" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN mes_ono INTEGER")
        if "supabase_order_id" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN supabase_order_id INTEGER")
        if "contact_name" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN contact_name TEXT")
        if "contact_phone" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN contact_phone TEXT")
        if "company" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN company TEXT")
        if "address" not in cols:
            cur.execute("ALTER TABLE order_list ADD COLUMN address TEXT")

        synced_count = 0

        for o in line_orders:
            sb_id = o.get("id")
            if not sb_id:
                continue

            client_id = o.get("client_id") or ""
            custom_id = f"LINE-{sb_id:04d}"

            # 檢查是否已存在
            cur.execute(
                "SELECT rowid, order_id, mes_ono, status FROM order_list WHERE supabase_order_id = ? OR order_id = ?",
                (sb_id, custom_id),
            )
            existing = cur.fetchone()

            # 解析品項與備註
            items_raw = o.get("items")
            parsed_items: List[Dict[str, Any]] = []
            note = "無備註"

            if isinstance(items_raw, str):
                try:
                    loaded = json.loads(items_raw)
                    if isinstance(loaded, dict):
                        parsed_items = loaded.get("order_items", [])
                        note = loaded.get("note", "無備註")
                    elif isinstance(loaded, list):
                        parsed_items = loaded
                except Exception:
                    pass
            elif isinstance(items_raw, list):
                parsed_items = items_raw
            elif isinstance(items_raw, dict):
                parsed_items = items_raw.get("order_items", [])
                note = items_raw.get("note", "無備註")

            product_parts = []
            total_qty = 0
            for it in parsed_items:
                pname = it.get("product_name") or it.get("name") or "產品"
                qty = int(it.get("quantity") or it.get("qty") or 1)
                product_parts.append(f"{pname} x {qty}")
                total_qty += qty

            product_str = ", ".join(product_parts) if product_parts else "Basic Fuse Box"
            total_amount = total_qty if total_qty > 0 else 1
            total_price = int(o.get("total_price") or 0)

            # 下單時間
            created_at = o.get("created_at") or datetime.now().isoformat()
            date_str = created_at[:19].replace("T", " ")

            # 狀態對應
            raw_status = o.get("status") or "Confirmed"
            if "Cancel" in raw_status:
                db_status = "cancelled"
            elif "Complete" in raw_status:
                db_status = "completed"
            elif raw_status == "Pending Payment":
                db_status = "pending_payment"
            else:
                db_status = "active"

            contact_name = o.get("contact_name") or client_id
            contact_phone = o.get("contact_phone") or ""
            company = o.get("company") or ""
            address = o.get("address") or ""
            mes_ono = o.get("mes_ono")
            if not mes_ono and "MES ONo:" in raw_status:
                try:
                    mes_ono = int(raw_status.split("MES ONo:")[1].split(")")[0].strip())
                except Exception:
                    pass

            # 來源判斷（若是 web 則保留 web，否則設為 line）
            source = "line"
            if client_id.startswith("web:"):
                source = "web"

            if existing and raw_status == 'Pending Payment':
                db_status = existing['status']  # The website payment record is authoritative until dispatch.
            if existing and existing['status'] in ('completed', 'cancelled', 'rejected'):
                db_status = existing['status']
            if not existing:
                # 插入新紀錄
                cur.execute(
                    """
                    INSERT INTO order_list (
                        order_id, date, customer_name, product, amount, total_price,
                        step_name, note, status, contact_name, contact_phone,
                        company, address, source, mes_ono, supabase_order_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        custom_id, date_str, client_id, product_str, total_amount, total_price,
                        "1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9", note, db_status,
                        contact_name, contact_phone, company, address, source, mes_ono, sb_id
                    ),
                )
                synced_count += 1
            else:
                # 已存在，檢查是否需更新 mes_ono 或狀態
                need_update = False
                if mes_ono and mes_ono != existing["mes_ono"]:
                    need_update = True
                if db_status != existing["status"] and existing["status"] != "completed":
                    need_update = True

                if need_update:
                    cur.execute(
                        "UPDATE order_list SET mes_ono = COALESCE(?, mes_ono), status = ? WHERE rowid = ?",
                        (mes_ono, db_status, existing["rowid"]),
                    )
                    synced_count += 1

        conn.commit()
        conn.close()
        return synced_count
    except Exception as e:
        print(f"⚠️ [OrderSync] 同步 LineTalker 訂單至本地資料庫失敗: {e}")
        return 0


def dispatch_active_orders_to_mes() -> int:
    """Publish only explicitly confirmed MES requests through the existing downlink."""
    from .order_dispatch import publish_queued_orders
    return publish_queued_orders()
