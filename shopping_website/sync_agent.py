# =============================================================
# sync_agent.py
# 工廠電腦同步代理：即時將 FestoMES.accdb 資料推送到 Supabase
# =============================================================
# 用法（在工廠電腦上執行）：
#   設定環境變數後執行：
#   set FESTO_DB_PATH=C:\MES4\FestoMES.accdb
#   set SUPABASE_URL=https://xxxx.supabase.co
#   set SUPABASE_KEY=your-anon-key
#   python sync_agent.py
# =============================================================

import os
import sys
import time
import pyodbc
from datetime import datetime, timedelta

# ── Supabase SDK ──────────────────────────────────────────────
try:
    from supabase import create_client, Client
except ImportError as e:
    import traceback
    print("[ERROR] supabase import failed. Details:")
    traceback.print_exc()
    sys.exit(1)

# ── 設定（從環境變數讀取）────────────────────────────────────
# [修改點 A] Access 資料庫路徑

# 預設本機測試路徑
DEFAULT_LOCAL_DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "database", "FestoMES.accdb"))

FESTO_DB_PATH = os.environ.get("FESTO_DB_PATH", DEFAULT_LOCAL_DB)

# [修改點 B] Supabase 設定（貼上你的 Project URL 和 anon key）
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://lgnzcudrhvqhiichmqis.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_yLkS2oqaUUEETl1ESDS9fg_8m2Uk9x4")

# 同步間隔（秒）
SYNC_INTERVAL = 3


# ── Access 連線 ───────────────────────────────────────────────
def open_access():
    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={FESTO_DB_PATH};"
    )
    return pyodbc.connect(conn_str, autocommit=True)


# ── 靜態表同步（啟動時執行一次）──────────────────────────────
def sync_static_tables(sb: "Client"):
    """同步不常變動的設定資料表"""
    print("[Sync] Syncing static tables...")
    acc = open_access()
    cur = acc.cursor()

    # tblResource
    cur.execute("SELECT ResourceID, ResourceName, ResourceType FROM tblResource")
    rows = [{"resource_id": r[0], "resource_name": r[1], "resource_type": r[2]}
            for r in cur.fetchall()]
    if rows:
        sb.table("tbl_resource").upsert(rows, on_conflict="resource_id").execute()
    print(f"  tblResource: {len(rows)} rows")

    # tblResourceOperation
    cur.execute("SELECT ResourceID, OpNo, WorkingTime, OffsetTime FROM tblResourceOperation WHERE ResourceID > 0")
    rows = [{"resource_id": r[0], "op_no": r[1], "working_time": r[2], "offset_time": r[3]}
            for r in cur.fetchall()]
    if rows:
        sb.table("tbl_resource_operation").upsert(rows, on_conflict="resource_id,op_no").execute()
    print(f"  tblResourceOperation: {len(rows)} rows")

    # tblWorkPlanDef
    cur.execute("SELECT WPNo, Description, Short FROM tblWorkPlanDef WHERE WPNo > 0")
    rows = [{"wp_no": r[0], "description": r[1], "short": r[2]}
            for r in cur.fetchall()]
    if rows:
        sb.table("tbl_work_plan_def").upsert(rows, on_conflict="wp_no").execute()
    print(f"  tblWorkPlanDef: {len(rows)} rows")

    # tblStepDef
    cur.execute(
        "SELECT WPNo, StepNo, Description, OpNo, NextStepNo, FirstStep, ResourceID, WorkingTimeCalc "
        "FROM tblStepDef"
    )
    rows = [{"wp_no": r[0], "step_no": r[1], "description": r[2], "op_no": r[3],
             "next_step_no": r[4] or 0, "first_step": bool(r[5]),
             "resource_id": r[6] or 0, "working_time_calc": int(r[7] or 0)}
            for r in cur.fetchall()]
    if rows:
        sb.table("tbl_step_def").upsert(rows, on_conflict="wp_no,step_no").execute()
    print(f"  tblStepDef: {len(rows)} rows")

    acc.close()
    print("[Sync] Static tables done.")


# ── 動態表同步（定期執行）────────────────────────────────────
def sync_dynamic_tables(sb: "Client", state: dict):
    """同步機台狀態、工單、已完工步驟（只推送新資料）"""
    acc = open_access()
    cur = acc.cursor()

    # ── tblMachineReport（機台狀態：智能時間對齊）─────────────
    try:
        # 1. 取得 Access 本機當前最新的一筆資料 (ID 與 TimeStamp)
        cur.execute("SELECT TOP 1 ID, TimeStamp FROM tblMachineReport ORDER BY ID DESC")
        latest_row = cur.fetchone()
        access_max_id = int(latest_row[0] or 0) if latest_row else 0
        access_latest_ts = latest_row[1] if latest_row else None

        # 2. 智能時間對齊（Time Alignment）：若為首次啟動或定期校驗
        last_alignment_check = state.get("last_alignment_check", 0)
        now_ts = time.time()
        
        # 每 30 秒或初次啟動時，檢查雲端與本地是否產生時間倒退 (Rollback)
        if now_ts - last_alignment_check > 30:
            state["last_alignment_check"] = now_ts
            try:
                # 查詢雲端目前最大的一筆紀錄
                sb_latest = sb.table("tbl_machine_report").select("id, timestamp").order("id", desc=True).limit(1).execute()
                if sb_latest.data and len(sb_latest.data) > 0:
                    sb_id = int(sb_latest.data[0]["id"])
                    sb_ts_str = sb_latest.data[0].get("timestamp")

                    # 情況 A：若雲端的 ID 明顯大於工廠目前的 ID（工廠資料庫被還原至舊版本）
                    # 情況 B：若雲端時間比工廠最新時間更未來
                    is_rollback = False
                    if sb_id > access_max_id:
                        is_rollback = True
                    elif access_latest_ts and sb_ts_str:
                        # 比較 ISO 時間
                        acc_iso = access_latest_ts.isoformat() if hasattr(access_latest_ts, 'isoformat') else str(access_latest_ts)
                        if sb_ts_str > acc_iso and sb_id != access_max_id:
                            is_rollback = True

                    if is_rollback:
                        print(f"  [Time Alignment] 偵測到工廠資料庫版本還原！(工廠 Max ID: {access_max_id}, 雲端殘留 ID: {sb_id})")
                        print(f"  [Time Alignment] 自動清理雲端 ID > {access_max_id} 的幽靈資料...")
                        sb.table("tbl_machine_report").delete().gt("id", access_max_id).execute()
                        state["machine_report_last_id"] = max(0, access_max_id - 50)
            except Exception as align_err:
                print(f"  [Time Alignment Warning] 對齊校驗失敗: {align_err}")

        # 3. 確保本地同步指針不超越 Access 當前最大 ID
        if "machine_report_last_id" not in state or state["machine_report_last_id"] > access_max_id:
            state["machine_report_last_id"] = max(0, access_max_id - 50)
            print(f"  [Init] 對齊工廠基準點，從 ID: {state['machine_report_last_id']} 開始同步")

        last_id = state.get("machine_report_last_id", 0)

        # 4. 抓取新增或變動的資料行 (ID > last_id)
        cur.execute(
            f"SELECT TOP 500 ID, ResourceID, TimeStamp, AutomaticMode, ManualMode, "
            f"Busy, [Reset], ErrorL0, ErrorL1, ErrorL2 "
            f"FROM tblMachineReport WHERE ID > {last_id} ORDER BY ID"
        )
        rows = cur.fetchall()

        # 5. 若無新資料，保底抓取當前各工站最新 30 筆（確保時間與狀態不斷線）
        is_fallback = False
        if not rows:
            cur.execute(
                "SELECT TOP 30 ID, ResourceID, TimeStamp, AutomaticMode, ManualMode, "
                "Busy, [Reset], ErrorL0, ErrorL1, ErrorL2 "
                "FROM tblMachineReport ORDER BY ID DESC"
            )
            rows = cur.fetchall()
            is_fallback = True

        if rows:
            data = []
            machine_snapshots = state.setdefault("machine_snapshots", {})
            for r in rows:
                row_id = int(r[0])
                res_id = int(r[1] or 0)
                cur_snap = (res_id, bool(r[3]), bool(r[4]), bool(r[5]), bool(r[6]), bool(r[7]), bool(r[8]), bool(r[9]))
                
                # 若為新序號或狀態有變化，則上傳
                if not is_fallback or (res_id not in machine_snapshots or machine_snapshots[res_id] != cur_snap):
                    machine_snapshots[res_id] = cur_snap
                    ts = r[2]
                    data.append({
                        "id": row_id,
                        "resource_id": res_id,
                        "timestamp": ts.isoformat() if hasattr(ts, 'isoformat') else str(ts) if ts else None,
                        "automatic_mode": bool(r[3]),
                        "manual_mode": bool(r[4]),
                        "busy": bool(r[5]),
                        "reset": bool(r[6]),
                        "error_l0": bool(r[7]),
                        "error_l1": bool(r[8]),
                        "error_l2": bool(r[9]),
                    })

            if not is_fallback and rows:
                state["machine_report_last_id"] = int(rows[-1][0])
            elif is_fallback and rows:
                state["machine_report_last_id"] = int(rows[0][0])

            if data:
                sb.table("tbl_machine_report").upsert(data, on_conflict="id").execute()
                print(f"  [+] tblMachineReport: 智能對齊並更新 {len(data)} 筆紀錄 (目前工廠 Max ID: {access_max_id})")
    except Exception as e:
        print(f"  [WARNING] tblMachineReport sync failed: {e}")

    # ── tblOrder（工單：同步最新建立或狀態更新的訂單）─────────
    try:
        # 取最近 50 張工單，包含已存在的（狀態可能有更新，如 Start、End、State）
        cur.execute(
            "SELECT TOP 50 ONo, PlanedStart, PlanedEnd, Start, [End], State, Enabled, CNo "
            "FROM tblOrder ORDER BY ONo DESC"
        )
        rows = cur.fetchall()
        if rows:
            data = []
            order_snapshots = state.setdefault("order_snapshots", {})
            for r in rows:
                ono = r[0]
                # 比對狀態是否有變動 (state, start, end, enabled)
                cur_snap = (r[5], str(r[3]), str(r[4]), bool(r[6]))
                if ono not in order_snapshots or order_snapshots[ono] != cur_snap:
                    order_snapshots[ono] = cur_snap
                    data.append({
                        "ono": ono,
                        "planed_start": r[1].isoformat() if r[1] else None,
                        "planed_end": r[2].isoformat() if r[2] else None,
                        "start": r[3].isoformat() if r[3] else None,
                        "end": r[4].isoformat() if r[4] else None,
                        "state": r[5], "enabled": bool(r[6]), "cno": r[7],
                    })
            if data:
                sb.table("tbl_order").upsert(data, on_conflict="ono").execute()
                print(f"  [+] tblOrder: {len(data)} orders updated")
    except Exception as e:
        print(f"  [WARNING] tblOrder sync failed: {e}")

    # ── tblFinStep（已完工步驟：取最近 100 筆更新）────────────
    try:
        cur.execute(
            "SELECT TOP 100 WPNo, StepNo, ONo, Description, ResourceID, "
            "PlanedStart, PlanedEnd, Start, [End] "
            "FROM tblFinStep ORDER BY ONo DESC, StepNo DESC"
        )
        rows = cur.fetchall()
        if rows:
            data = []
            finstep_snapshots = state.setdefault("finstep_snapshots", {})
            for r in rows:
                key = (r[2], r[1])  # (ono, step_no)
                cur_snap = (str(r[7]), str(r[8])) # (start, end)
                if key not in finstep_snapshots or finstep_snapshots[key] != cur_snap:
                    finstep_snapshots[key] = cur_snap
                    data.append({
                        "wp_no": r[0], "step_no": r[1], "ono": r[2],
                        "description": r[3] or "", "resource_id": r[4] or 0,
                        "planed_start": r[5].isoformat() if r[5] else None,
                        "planed_end": r[6].isoformat() if r[6] else None,
                        "start": r[7].isoformat() if r[7] else None,
                        "end": r[8].isoformat() if r[8] else None,
                    })
            if data:
                sb.table("tbl_fin_step").upsert(data, on_conflict="ono,step_no").execute()
                print(f"  [+] tblFinStep: {len(data)} steps updated")
    except Exception as e:
        print(f"  [WARNING] tblFinStep sync failed: {e}")

    # ── tblBufferPos（倉儲 Buffer 位置 1~32）──────────────
    try:
        # 使用 SELECT * 避免任何欄位遺失造成的查詢錯誤
        # 既然確認了工廠的 ResourceId 就是 3，我們就把條件嚴格加回來
        cur.execute("SELECT * FROM tblBufferPos WHERE ResourceId = 3 AND BufPos >= 1 AND BufPos <= 32 ORDER BY BufPos")
        cols = [d[0].lower() for d in cur.description]
        raw_rows = cur.fetchall()
        
        if raw_rows:
            # 優先保留 f_no != 0 的那筆資料
            best_rows = {}
            for r in raw_rows:
                row_dict = dict(zip(cols, r))
                buf_pos = int(row_dict.get('bufpos', 0))
                new_fno = int(row_dict.get('fno') or row_dict.get('pno') or 0)
                
                if buf_pos not in best_rows:
                    best_rows[buf_pos] = row_dict
                else:
                    old_fno = int(best_rows[buf_pos].get('fno') or best_rows[buf_pos].get('pno') or 0)
                    if old_fno == 0 and new_fno != 0:
                        best_rows[buf_pos] = row_dict

            buf_rows = list(best_rows.values())
            
            new_snapshot = {}
            data = []
            for row_dict in buf_rows:
                
                buf_pos = int(row_dict.get('bufpos', 0))
                buf_no  = int(row_dict.get('bufno', 0))
                f_no    = int(row_dict.get('fno') or row_dict.get('pno') or 0)
                o_no    = int(row_dict.get('ono', 0) or 0)
                u_pos   = int(row_dict.get('upos') or row_dict.get('opos') or 0)
                m_type  = int(row_dict.get('type', 0) or 0)
                zone    = int(row_dict.get('zone', 0) or 0)
                qty     = int(row_dict.get('quantity', 0) or 0)
                qty_max = int(row_dict.get('quantitymax', 0) or 0)
                ts      = row_dict.get('timestamp')
                pallet  = int(row_dict.get('palletid', 0) or 0)
                
                new_snapshot[buf_pos] = (f_no, o_no, m_type)
                data.append({
                    "buf_pos":      buf_pos,
                    "buf_no":       buf_no,
                    "f_no":         f_no,
                    "o_no":         o_no,
                    "u_pos":        u_pos,
                    "type":         m_type,
                    "zone":         zone,
                    "quantity":     qty,
                    "quantity_max": qty_max,
                    "time_stamp":   ts.isoformat() if hasattr(ts, 'isoformat') else str(ts) if ts else None,
                    "pallet_id":    pallet,
                })
                
            last_snapshot = state.get("buffer_snapshot", {})
            if new_snapshot != last_snapshot:
                sb.table("tbl_buffer_pos").upsert(data, on_conflict="buf_pos").execute()
                state["buffer_snapshot"] = new_snapshot
                occupied = sum(1 for d in data if d["f_no"] != 0)
                print(f"  [+] tblBufferPos: {len(data)} positions updated (佔用 {occupied}/32)")
            else:
                print(f"  [-] tblBufferPos: No changes (skip upload)")
    except Exception as e:
        print(f"  [WARNING] tblBufferPos sync failed: {e}")

    acc.close()


# ── 下行訂單同步（從 Supabase line_orders 拉取新訂單下發至 Festo MES tblOrder）──
def sync_orders_down_to_mes(sb: "Client", state: dict):
    """
    查詢 Supabase 中新確認的訂單（status='Confirmed'），
    在工廠 Access FestoMES.accdb 中自動生成新工單 (ONo)，
    並將產生之工廠 ONo 回寫至 Supabase 訂單狀態。
    """
    try:
        resp = sb.table("line_orders").select("*").eq("status", "Confirmed").order("id").limit(10).execute()
        orders = resp.data or []
        if not orders:
            return

        acc = open_access()
        cur = acc.cursor()

        for order in orders:
            order_id = order["id"]
            contact_name = order.get("contact_name") or order.get("client_id")
            print(f"  [MES Dispatch] 偵測到雲端新訂單 #{order_id} (客戶: {contact_name})，正在排入工廠 MES...")

            # 1. 取得目前工廠 MAX ONo
            cur.execute("SELECT MAX(ONo) FROM tblOrder")
            max_row = cur.fetchone()
            max_ono = int(max_row[0] or 0) if max_row and max_row[0] is not None else 0
            new_ono = max_ono + 1

            # 2. 預計開始與完工時間
            now_dt = datetime.now()
            plan_end_dt = now_dt + timedelta(minutes=15)

            # 3. 寫入工廠真實 tblOrder (State=1 排定/待加工, Enabled=True)
            cur.execute(
                """
                INSERT INTO tblOrder (ONo, PlanedStart, PlanedEnd, Start, [End], CNo, State, Enabled, Release)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (new_ono, now_dt, plan_end_dt, None, None, 1, 1, True, now_dt)
            )

            # 4. 回寫 Supabase 訂單狀態 (標註已下發的工廠 ONo)
            new_status = f"In Production (MES ONo: {new_ono})"
            sb.table("line_orders").update({"status": new_status}).eq("id", order_id).execute()
            print(f"  [+] 成功下發訂單 #{order_id} 至工廠 MES！生成工單 ONo: {new_ono}，狀態已更新。")

        acc.close()

        # 5. 同步更新網站端本地 order_management.db
        try:
            from core.order_sync import sync_line_orders_to_order_list
            sync_line_orders_to_order_list()
        except Exception as e:
            pass
    except Exception as e:
        print(f"  [WARNING] 下行訂單同步失敗: {e}")


# ── 主程式 ────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  Festo MES Sync Agent (Two-Way Sync)")
    print(f"  Access DB : {FESTO_DB_PATH}")
    print(f"  Supabase  : {SUPABASE_URL}")
    print(f"  Interval  : {SYNC_INTERVAL}s")
    print("=" * 55)

    if not os.path.exists(FESTO_DB_PATH):
        print(f"[ERROR] Access DB not found: {FESTO_DB_PATH}")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("[OK] Connected to Supabase")

    # 初次同步靜態資料表
    try:
        sync_static_tables(sb)
    except Exception as e:
        print(f"[WARNING] Static sync failed: {e}")

    state = {}
    print(f"\n[Sync] Starting real-time sync every {SYNC_INTERVAL}s... (Ctrl+C to stop)\n")

    while True:
        try:
            sync_dynamic_tables(sb, state)
            sync_orders_down_to_mes(sb, state)
        except pyodbc.Error as e:
            print(f"[WARNING] Access error: {e}")
        except Exception as e:
            print(f"[WARNING] Sync error: {e}")
        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
