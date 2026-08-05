"""Test scheduler APIs"""
import sys, json
sys.path.insert(0, ".")

from app import create_app

app = create_app()

with app.test_client() as c:
    # Simulate admin login
    with c.session_transaction() as sess:
        sess["user_id"] = 1
        sess["account"] = "admin"
        sess["role"] = "admin"

    # 1. Gantt data
    r = c.get("/scheduler/api/gantt_data?algorithm=fcfs")
    data = r.get_json()
    print("=== Gantt Data (FCFS) ===")
    print("Status:", r.status_code)
    if "error" in data:
        print("ERROR:", data["error"])
    else:
        print("Orders:", len(data.get("order_sequence", [])))
        print("Tasks:", len(data.get("tasks", [])))
        print("Makespan:", data.get("total_makespan_sec"), "sec")
        print("Bottleneck:", data.get("bottleneck_station"))
        if data.get("tasks"):
            t = data["tasks"][0]
            print("First task:", t.get("order_id"), t.get("station_name"), t.get("duration_sec"), "sec")

    # 2. Station load
    r2 = c.get("/scheduler/api/station_load?algorithm=fcfs")
    d2 = r2.get_json()
    print("\n=== Station Load ===")
    if "error" in d2:
        print("ERROR:", d2["error"])
    else:
        for s in d2.get("stations", []):
            flag = " <<< BOTTLENECK" if s["resource_id"] == d2.get("bottleneck_station") else ""
            print(f"  {s['station_name']}: {s['utilization']}%{flag}")

    # 3. Compare algorithms
    r3 = c.get("/scheduler/api/compare_algorithms")
    d3 = r3.get_json()
    print("\n=== Algorithm Comparison ===")
    if "error" in d3:
        print("ERROR:", d3["error"])
    else:
        for item in d3.get("comparison", []):
            m = item["total_makespan_sec"] // 60
            s = item["total_makespan_sec"] % 60
            print(f"  {item['algorithm']:10s}: {m}m {s}s")

    # 4. Work plans from MES
    r4 = c.get("/scheduler/api/work_plans")
    d4 = r4.get_json()
    print("\n=== MES Work Plans ===")
    if "error" in d4:
        print("ERROR:", d4["error"])
    else:
        for wp in d4.get("work_plans", [])[:5]:
            print(f"  WP {wp['wp_no']}: {wp['description']} ({wp['total_time']}s)")

    print("\nAll tests done!")
