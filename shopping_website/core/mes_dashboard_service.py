"""Read-only cloud dashboard queries; record time is not a sync heartbeat."""
from datetime import datetime, timezone


def record_freshness(value, now):
    if not value:
        return "unknown"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            return "clock_unverified"
        age = (now - stamp).total_seconds()
        if age < -60:
            return "clock_unverified"
        return "recent" if age <= 300 else "old"
    except (ValueError, TypeError):
        return "unknown"


def cloud_snapshot(client):
    now = datetime.now(timezone.utc)
    result = {"source": "Supabase", "queried_at": now.isoformat(),
              "machines": [], "orders": [], "machines_error": None,
              "orders_error": None, "latest_record_at": None,
              "sync_heartbeat_at": None}
    try:
        resources = client.table("tbl_resource").select("resource_id,resource_name").order("resource_id").execute().data
        for resource in resources or []:
            rows = (client.table("tbl_machine_report")
                    .select("timestamp,automatic_mode,manual_mode,busy,error_l0")
                    .eq("resource_id", resource["resource_id"])
                    .order("timestamp", desc=True).order("id", desc=True).limit(1).execute().data)
            row = rows[0] if rows else {}
            stamp = row.get("timestamp")
            result["machines"].append({
                "ResourceID": resource["resource_id"], "ResourceName": resource["resource_name"],
                "AutomaticMode": row.get("automatic_mode"), "ManualMode": row.get("manual_mode"),
                "Busy": row.get("busy"), "ErrorL0": row.get("error_l0"),
                "recorded_at": stamp, "freshness": record_freshness(stamp, now)})
        latest = (client.table("tbl_machine_report").select("timestamp")
                  .order("timestamp", desc=True).limit(1).execute().data)
        result["latest_record_at"] = latest[0]["timestamp"] if latest else None
    except Exception:
        result["machines"] = []
        result["machines_error"] = "機台資料讀取失敗，請稍後重試。"
    try:
        rows = (client.table("tbl_order")
                .select("ono,state,planed_start,planed_end,start,end")
                .order("ono", desc=True).limit(50).execute().data)
        result["orders"] = [{"ONo": r["ono"], "State": r.get("state"),
                              "PlanedStart": r.get("planed_start"), "PlanedEnd": r.get("planed_end"),
                              "Start": r.get("start"), "End": r.get("end")} for r in rows or []]
    except Exception:
        result["orders_error"] = "工單讀取失敗，並非沒有工單。"
    result["freshness"] = record_freshness(result["latest_record_at"], now)
    result["connection"] = "degraded" if result["machines_error"] or result["orders_error"] else "connected"
    return result
