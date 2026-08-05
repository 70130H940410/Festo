# core/scheduler_routes.py
"""
排程系統的 API 與頁面路由。
提供甘特圖數據、站點負載、演算法切換、訂單排序等功能。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, session, abort

from . import login_required, manager_required
from .db import get_order_mgmt_db, get_product_db
from .mes_data_service import MesDataService
from .scheduler_engine import SchedulerEngine, OrderJob, Algorithm

scheduler_bp = Blueprint("scheduler", __name__, url_prefix="/scheduler")


def _parse_step_chain_from_str(s: str):
    """相容現有格式：'1 -> 2 -> 3' 解析為 [1,2,3]"""
    if not s:
        return []
    return [int(x.strip()) for x in s.split("->") if x.strip().isdigit()]


def _build_engine_from_active_orders() -> SchedulerEngine:
    """從資料庫讀取所有 active 訂單，建立排程引擎"""
    engine = SchedulerEngine()
    engine.load_mes_data()

    conn = get_order_mgmt_db()
    try:
        rows = conn.execute(
            "SELECT order_id, customer_name, product, total_price, note, amount, step_name, status, date, estimated_delivery "
            "FROM order_list WHERE status IN ('active', 'pending_payment') "
            "ORDER BY date ASC"
        ).fetchall()

        for row in rows:
            order_id = row["order_id"]
            amount = max(1, int(row["amount"] or 1))
            step_str = row["step_name"] or ""
            cust_name = row["customer_name"] or "未知下單者"
            product_name = row["product"] or "客製產品"
            try:
                total_price = float(row["total_price"] or 0)
            except Exception:
                total_price = 0.0
            note = row["note"] or "無備註"
            status = row["status"] or ""

            # 嘗試取得 priority（欄位可能不存在）
            priority = 0
            try:
                priority = int(row["priority"] or 0)
            except Exception:
                pass

            # 嘗試取得 work_plan_no
            wp_no = 0
            try:
                wp_no = int(row["work_plan_no"] or 0)
            except Exception:
                pass

            # 交期
            due_date = None
            try:
                ed = row["estimated_delivery"]
                if ed:
                    due_date = datetime.strptime(ed, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

            # 建立時間
            created_at = None
            try:
                d = row["date"]
                if d:
                    created_at = datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

            order_job = OrderJob(
                order_id=order_id,
                amount=amount,
                work_plan_no=wp_no if wp_no > 0 else 1211,  # 預設 full course
                customer_name=cust_name,
                product_name=product_name,
                total_price=total_price,
                note=note,
                status=status,
                priority=priority,
                due_date=due_date,
                created_at=created_at,
            )

            # 如果有 MES WorkPlan 就從 MES 載入步驟
            if wp_no > 0:
                plan = MesDataService.get_work_plan(wp_no)
                if plan:
                    order_job.step_chain = plan.ordered_steps

            # 如果沒有 MES 步驟，從現有 step_name 建構
            if not order_job.step_chain and step_str:
                chain = _parse_step_chain_from_str(step_str)
                # 用 product.db 的 standard_process 建構 StepDef
                if chain:
                    prod_conn = get_product_db()
                    try:
                        from .mes_data_service import StepDef
                        for step_order in chain:
                            sp = prod_conn.execute(
                                "SELECT step_order, step_name, station, estimated_time_sec "
                                "FROM standard_process WHERE step_order = ?",
                                (step_order,)
                            ).fetchone()
                            if sp:
                                order_job.step_chain.append(StepDef(
                                    wp_no=0,
                                    step_no=int(sp["step_order"]),
                                    description=sp["step_name"] or "",
                                    op_no=0,
                                    next_step_no=0,
                                    first_step=(step_order == chain[0]),
                                    resource_id=step_order,  # 用 step_order 當 resource_id
                                    working_time_calc=int(sp["estimated_time_sec"] or 5),
                                ))
                    finally:
                        prod_conn.close()

            engine.add_order(order_job)
    finally:
        conn.close()

    return engine


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@scheduler_bp.route("/")
@login_required
def dashboard():
    """排程儀表板主頁面"""
    if session.get("role") != "admin":
        abort(403)

    return render_template("scheduler/dashboard.html")



# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

@scheduler_bp.route("/api/gantt_data")
@login_required
def api_gantt_data():
    """取得甘特圖數據"""
    if session.get("role") != "admin":
        abort(403)

    algo_str = request.args.get("algorithm", "fcfs").lower()
    try:
        algo = Algorithm(algo_str)
    except ValueError:
        algo = Algorithm.FCFS

    try:
        engine = _build_engine_from_active_orders()
        result = engine.schedule(algo)

        return jsonify({
            "algorithm": algo.value,
            "tasks": result.gantt_data(),
            "order_sequence": result.order_sequence,
            "orders_details": result.orders_details,
            "total_makespan_sec": result.total_makespan_sec,
            "bottleneck_station": result.bottleneck_station,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/station_load")
@login_required
def api_station_load():
    """取得站點負載數據"""
    if session.get("role") != "admin":
        abort(403)

    algo_str = request.args.get("algorithm", "fcfs").lower()
    try:
        algo = Algorithm(algo_str)
    except ValueError:
        algo = Algorithm.FCFS

    try:
        engine = _build_engine_from_active_orders()
        result = engine.schedule(algo)

        return jsonify({
            "stations": result.station_load_data(),
            "bottleneck_station": result.bottleneck_station,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/bottleneck")
@login_required
def api_bottleneck():
    """瓶頸分析"""
    if session.get("role") != "admin":
        abort(403)

    algo_str = request.args.get("algorithm", "fcfs").lower()
    try:
        algo = Algorithm(algo_str)
    except ValueError:
        algo = Algorithm.FCFS

    try:
        engine = _build_engine_from_active_orders()
        analysis = engine.analyze_bottleneck(algo)
        return jsonify(analysis)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/work_plans")
@login_required
def api_work_plans():
    """列出所有可用 WorkPlan"""
    try:
        plans = MesDataService.get_available_work_plans()
        data = []
        for wp in plans:
            plan_detail = MesDataService.get_work_plan(wp.wp_no)
            steps = []
            if plan_detail:
                for s in plan_detail.ordered_steps:
                    steps.append({
                        "step_no": s.step_no,
                        "description": s.description,
                        "resource_id": s.resource_id,
                        "station_name": s.station_label,
                        "working_time": s.working_time_calc,
                    })
            data.append({
                "wp_no": wp.wp_no,
                "description": wp.description,
                "short": wp.short,
                "steps": steps,
                "total_time": plan_detail.total_working_time if plan_detail else 0,
            })
        return jsonify({"work_plans": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/compare_algorithms")
@login_required
def api_compare_algorithms():
    """比較所有演算法的排程結果"""
    if session.get("role") != "admin":
        abort(403)

    try:
        engine = _build_engine_from_active_orders()
        comparison = []
        for algo in Algorithm:
            result = engine.schedule(algo)
            comparison.append({
                "algorithm": algo.value,
                "total_makespan_sec": result.total_makespan_sec,
                "bottleneck_station": result.bottleneck_station,
                "order_sequence": result.order_sequence,
            })
        return jsonify({"comparison": comparison})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/reorder", methods=["POST"])
@login_required
def api_reorder():
    """手動調整訂單優先順序"""
    if session.get("role") != "admin":
        abort(403)

    data = request.get_json()
    new_order = data.get("order_sequence", [])
    if not new_order:
        return jsonify({"error": "order_sequence required"}), 400

    # 更新 priority 欄位（排在越前面 priority 越高）
    conn = get_order_mgmt_db()
    try:
        # 確保 priority 欄位存在
        cols = [r[1] for r in conn.execute("PRAGMA table_info(order_list)").fetchall()]
        if "priority" not in cols:
            conn.execute("ALTER TABLE order_list ADD COLUMN priority INTEGER DEFAULT 0")

        for idx, order_id in enumerate(reversed(new_order)):
            conn.execute(
                "UPDATE order_list SET priority = ? WHERE order_id = ?",
                (idx + 1, order_id)
            )
        conn.commit()
        return jsonify({"ok": True, "message": "排程順序已更新"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@scheduler_bp.route("/api/historical_stats")
@login_required
def api_historical_stats():
    """歷史加工時間統計"""
    if session.get("role") != "admin":
        abort(403)

    try:
        stats = MesDataService.get_historical_stats()
        names = MesDataService.get_resource_names()
        data = []
        for (res_id, _), st in stats.items():
            data.append({
                "resource_id": res_id,
                "station_name": names.get(res_id, f"Station-{res_id}"),
                "avg_duration": round(st.avg_duration, 1),
                "min_duration": round(st.min_duration, 1),
                "max_duration": round(st.max_duration, 1),
                "sample_count": st.sample_count,
            })
        return jsonify({"stats": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
