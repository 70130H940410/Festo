"""Compare independent simulations of one immutable input snapshot."""
import copy
import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from .scheduler_engine import Algorithm


def compare_snapshot(engine, start=None):
    start = start or datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None, microsecond=0)
    frozen = copy.deepcopy(engine)
    orders = frozen._orders
    if len({o.order_id for o in orders}) != len(orders):
        raise ValueError("訂單編號重複，無法公平比較。")
    inputs = []
    for order in orders:
        if not order.step_chain or order.amount <= 0:
            raise ValueError("有訂單缺少製程或有效數量，請補齊後比較。")
        for step in order.step_chain:
            duration = frozen._working_time_map.get((step.resource_id, step.op_no), step.working_time_calc)
            if step.resource_id <= 0 or duration <= 0:
                raise ValueError("有製程缺少有效工站或加工秒數，請補齊後比較。")
            step.working_time_calc = duration
        inputs.append({"order_id": order.order_id, "amount": order.amount,
                       "created_at": order.created_at.isoformat() if order.created_at else None,
                       "due_date": order.due_date.isoformat() if order.due_date else None,
                       "priority": order.priority,
                       "steps": [{"step_no": s.step_no, "resource_id": s.resource_id,
                                  "duration_sec": s.working_time_calc} for s in order.step_chain]})
    payload = {"snapshot_id": uuid.uuid4().hex, "start_time": start.isoformat(),
               "timezone": "Asia/Taipei", "source": "本機 active / pending_payment 訂單；MES 加工時間優先，否則使用製程估計值",
               "input_hash": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
               "inputs": inputs, "order_count": len(orders),
               "due_date_count": sum(o.due_date is not None for o in orders),
               "missing_created_count": sum(o.created_at is None for o in orders),
               "assumptions": "交期採用訂單 estimated_delivery（預估交期），不代表客戶承諾交期。全部訂單於起算時可加工、所有工站初始空閒；不含搬運、換線、故障、既有在製品與已完成工序。未付款訂單亦納入情境。缺少建立時間時 FCFS 排在最前；缺交期時 EDD 排最後，延遲指標不納入。Weighted 權重：急迫性 0.4、SPT 0.3、EDD 0.3。",
               "comparison": []}
    if not orders:
        return payload
    for algo in Algorithm:
        candidate = copy.deepcopy(frozen)
        tick = time.perf_counter()
        result = candidate.schedule(algo, start_time=start)
        elapsed = (time.perf_counter() - tick) * 1000
        details = []
        for order in candidate._orders:
            tasks = [t for t in result.tasks if t.order_id == order.order_id]
            end = max(t.planned_end for t in tasks)
            details.append({"order_id": order.order_id, "due_date": order.due_date.isoformat() if order.due_date else None,
                            "completion": end.isoformat(),
                            "tardiness_sec": max(0, (end-order.due_date).total_seconds()) if order.due_date else None})
        tardiness = [d["tardiness_sec"] for d in details if d["tardiness_sec"] is not None]
        payload["comparison"].append({"algorithm": algo.value,
            "total_makespan_sec": result.total_makespan_sec,
            "total_tardiness_sec": sum(tardiness) if tardiness else None,
            "mean_tardiness_sec": sum(tardiness)/len(tardiness) if tardiness else None,
            "tardy_orders": sum(t > 0 for t in tardiness) if tardiness else None,
            "runtime_ms": round(elapsed, 3), "order_sequence": result.order_sequence,
            "details": details})
    best = min(r["total_makespan_sec"] for r in payload["comparison"])
    for row in payload["comparison"]:
        row["best_makespan"] = row["total_makespan_sec"] == best
    return payload
