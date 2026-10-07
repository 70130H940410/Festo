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


def sync_line_orders_to_order_list() -> int:
    """
    從 Supabase line_orders 拉取訂單並同步至本地 SQLite order_list。
    回傳新增/更新的筆數。
    """
    sb = get_supabase_client()
    if not sb:
        return 0

    try:
        # 從 Supabase line_orders 取出所有訂單
        resp = sb.table("line_orders").select("*").order("id").execute()
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
                if mes_ono and not existing["mes_ono"]:
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
    """
    掃描本地 order_list 中 status='active' 且尚未指派 MES 工單 (mes_ono IS NULL) 的訂單，
    自動向工廠 MES (Supabase tbl_order 及本機 Access) 登記新工單 (ONo)，
    並在 piece_step_progress 初始化該工單的所有加工件與工序，讓工廠機台立即開始運作。
    回傳成功下發至工廠的訂單筆數。
    """
    conn = get_order_mgmt_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT rowid, order_id, status, amount, step_name, supabase_order_id, source
            FROM order_list
            WHERE status = 'active' AND mes_ono IS NULL
            ORDER BY rowid ASC
            """
        )
        unassigned = cur.fetchall()
        if not unassigned:
            conn.close()
            return 0

        sb = get_supabase_client()
        dispatched_count = 0

        for row in unassigned:
            order_id = row["order_id"]
            sb_order_id = row["supabase_order_id"]
            step_name = row["step_name"] or "1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9"
            amount = max(1, int(row["amount"] or 1))

            new_ono = None

            # 1. 取得 MES 當前最大的 ONo
            if sb:
                try:
                    resp = sb.table("tbl_order").select("ono").order("ono", desc=True).limit(1).execute()
                    if resp.data and len(resp.data) > 0:
                        new_ono = int(resp.data[0]["ono"]) + 1
                except Exception as e:
                    print(f"⚠️ [OrderSync] 查詢 Supabase tbl_order max(ono) 失敗: {e}")

            if not new_ono:
                # 若雲端查詢不到，由本地生成起始號或查找本機現有最大 mes_ono
                cur.execute("SELECT MAX(mes_ono) FROM order_list")
                m = cur.fetchone()
                local_max = int(m[0]) if m and m[0] else 3500
                new_ono = local_max + 1

            # 2. 寫入 Supabase tbl_order (State=1: 排定待加工, Enabled=True)
            now_dt = datetime.now()
            now_iso = now_dt.isoformat()
            from datetime import timedelta
            plan_end_iso = (now_dt + timedelta(minutes=15)).isoformat()

            if sb:
                try:
                    sb.table("tbl_order").upsert({
                        "ono": new_ono,
                        "planed_start": now_iso,
                        "planed_end": plan_end_iso,
                        "start": now_iso,
                        "end": None,
                        "state": 1,
                        "enabled": True,
                        "cno": 1,
                    }, on_conflict="ono").execute()
                    print(f"🚀 [MES Dispatch] 成功建立 Supabase 工廠工單 ONo: {new_ono} (對應訂單: {order_id})")
                except Exception as e:
                    print(f"⚠️ [OrderSync] 寫入 Supabase tbl_order 失敗: {e}")

                # 3. 若為 LINE 訂單，更新 Supabase line_orders 的狀態標記
                if sb_order_id:
                    try:
                        sb.table("line_orders").update({
                            "status": f"In Production (MES ONo: {new_ono})"
                        }).eq("id", sb_order_id).execute()
                    except Exception as e:
                        print(f"⚠️ [OrderSync] 回寫 line_orders 狀態失敗: {e}")

            # 4. 更新本地 order_list
            cur.execute(
                "UPDATE order_list SET mes_ono = ? WHERE rowid = ?",
                (new_ono, row["rowid"]),
            )
            conn.commit()

            # 5. 在 piece_step_progress 自動建立件數與製程步驟
            try:
                from .factory_routes import _ensure_piece_rows, _parse_step_chain
                chain = _parse_step_chain(step_name)
                if chain:
                    _ensure_piece_rows(conn, order_id, chain, amount)
                    print(f"⚙️ [Factory Init] 訂單 {order_id} (ONo: {new_ono}) 已初始化 {amount} 件 x {len(chain)} 步驟進入工廠待派工隊列！")
            except Exception as e:
                print(f"⚠️ [OrderSync] 初始化 piece_step_progress 失敗: {e}")

            dispatched_count += 1

        conn.close()
        return dispatched_count
    except Exception as e:
        print(f"⚠️ [OrderSync] dispatch_active_orders_to_mes 發生異常: {e}")
        conn.close()
        return 0

