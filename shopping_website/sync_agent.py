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
from datetime import datetime

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
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://your-project.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your-anon-key")

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

    # ── tblMachineReport（機台狀態，最重要）────────────────
    last_id = state.get("machine_report_last_id", 0)
    machine_last_state = state.setdefault("machine_last_state", {})
    
    cur.execute(
        f"SELECT ID, ResourceID, TimeStamp, AutomaticMode, ManualMode, "
        f"Busy, [Reset], ErrorL0, ErrorL1, ErrorL2 "
        f"FROM tblMachineReport WHERE ID > {last_id} ORDER BY ID"
    )
    rows = cur.fetchall()
    if rows:
        data = []
        for r in rows:
            res_id = r[1]
            # 狀態組合：(Auto, Manual, Busy, Reset, Err0, Err1, Err2)
            current_state = (bool(r[3]), bool(r[4]), bool(r[5]), bool(r[6]), bool(r[7]), bool(r[8]), bool(r[9]))
            
            # [頻寬優化] 只有狀態發生改變，才需要上傳到雲端
            if res_id not in machine_last_state or machine_last_state[res_id] != current_state:
                machine_last_state[res_id] = current_state
                ts = r[2]
                data.append({
                    "id": r[0], "resource_id": res_id,
                    "timestamp": ts.isoformat() if ts else None,
                    "automatic_mode": current_state[0], "manual_mode": current_state[1],
                    "busy": current_state[2], "reset": current_state[3],
                    "error_l0": current_state[4], "error_l1": current_state[5], "error_l2": current_state[6],
                })
        
        # 即使很多列被過濾掉，我們依然要把 last_id 更新到最後一筆，避免下次重複掃描
        state["machine_report_last_id"] = rows[-1][0]
        
        if data:
            sb.table("tbl_machine_report").upsert(data, on_conflict="id").execute()
            print(f"  [+] tblMachineReport: Uploaded {len(data)} changed rows (Filtered {len(rows)-len(data)} duplicates. Last ID={state['machine_report_last_id']})")
        else:
            print(f"  [-] tblMachineReport: No state changes in {len(rows)} new rows.")

    # ── tblOrder（工單）──────────────────────────────────
    try:
        last_ono = state.get("order_last_ono", 0)
        cur.execute(
            f"SELECT ONo, PlanedStart, PlanedEnd, Start, [End], State, Enabled, CNo "
            f"FROM tblOrder WHERE ONo > {last_ono} ORDER BY ONo"
        )
        rows = cur.fetchall()
        if rows:
            data = []
            for r in rows:
                data.append({
                    "ono": r[0],
                    "planed_start": r[1].isoformat() if r[1] else None,
                    "planed_end": r[2].isoformat() if r[2] else None,
                    "start": r[3].isoformat() if r[3] else None,
                    "end": r[4].isoformat() if r[4] else None,
                    "state": r[5], "enabled": bool(r[6]), "cno": r[7],
                })
            sb.table("tbl_order").upsert(data, on_conflict="ono").execute()
            state["order_last_ono"] = rows[-1][0]
            print(f"  [+] tblOrder: {len(rows)} new rows")
    except Exception as e:
        print(f"  [WARNING] tblOrder sync failed: {e}")

    # ── tblFinStep（已完工步驟）──────────────────────────
    try:
        last_ono = state.get("fin_step_last_ono", 0)
        cur.execute(
            f"SELECT TOP 50 WPNo, StepNo, ONo, Description, ResourceID, "
            f"PlanedStart, PlanedEnd, Start, [End] "
            f"FROM tblFinStep WHERE ONo > {last_ono} ORDER BY ONo DESC"
        )
        rows = cur.fetchall()
        if rows:
            data = []
            for r in rows:
                data.append({
                    "wp_no": r[0], "step_no": r[1], "ono": r[2],
                    "description": r[3] or "", "resource_id": r[4] or 0,
                    "planed_start": r[5].isoformat() if r[5] else None,
                    "planed_end": r[6].isoformat() if r[6] else None,
                    "start": r[7].isoformat() if r[7] else None,
                    "end": r[8].isoformat() if r[8] else None,
                })
            sb.table("tbl_fin_step").upsert(data, on_conflict="ono,step_no").execute()
            state["fin_step_last_ono"] = rows[0][2]  # latest ONo
            print(f"  [+] tblFinStep: {len(rows)} new rows")
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


# ── 主程式 ────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  Festo MES Sync Agent")
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
        except pyodbc.Error as e:
            print(f"[WARNING] Access error: {e}")
        except Exception as e:
            print(f"[WARNING] Sync error: {e}")
        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
