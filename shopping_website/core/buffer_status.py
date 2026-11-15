"""ASRS occupancy and processing stage, independent from supply inventory."""
import json
import os
from .db import get_supabase_client

LABELS = {"raw": "未加工", "wip": "加工中（半成品）", "finished": "成品",
          "empty": "空位", "plate": "PLATE（僅托盤）", "unknown": "待確認"}


def classify(row, type_map):
    if row is None:
        return "unknown", "缺少倉位資料"
    if row.get("f_no") == 0:
        return "empty", "已確認料號 0：空位"
    if row.get("f_no") == 25:
        return "plate", "已確認料號 25：PLATE，僅有托盤"
    stage = row.get("processing_status") or type_map.get(str(row.get("type")))
    if stage in ("raw", "wip", "finished"):
        return stage, "MES 加工狀態對照"
    # Confirmed material codes: black / blue / white unprocessed workpieces.
    if row.get("f_no") in (210, 410, 610):
        return "raw", "已確認料號：210 黑色、410 藍色、610 白色均為未加工品"
    return "unknown", "尚未設定 MES 加工狀態對照；料號與顏色不代表加工進度"


def read_buffer_status():
    client = get_supabase_client()
    if client is None:
        raise RuntimeError("Cloud unavailable")
    type_map = json.loads(os.environ.get("ASRS_PROCESS_TYPE_MAP", "{}"))
    if not isinstance(type_map, dict) or any(v not in ("raw", "wip", "finished") for v in type_map.values()):
        raise ValueError("Invalid ASRS stage mapping")
    rows = client.table("tbl_buffer_pos").select("*").order("buf_pos").execute().data
    by_position = {}
    for row in rows or []:
        pos = row.get("buf_pos")
        if pos in by_position:
            raise ValueError("Ambiguous buffer positions")
        by_position[pos] = row
    counts = dict.fromkeys(LABELS, 0)
    positions = []
    for pos in range(1, 33):
        row = by_position.get(pos)
        stage, reason = classify(row, type_map)
        counts[stage] += 1
        positions.append(dict(row or {}, buf_pos=pos, processing_status=stage,
                              processing_label=LABELS[stage], status_reason=reason))
    return {"positions": positions, "summary": {"total": 32, **counts},
            "source": "Supabase", "inventory_included": False}
