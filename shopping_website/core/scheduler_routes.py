# =============================================================
# core/scheduler_routes.py
# 排程系統路由模組
# ----------------------------------------------------------
# Blueprint 名稱：scheduler（前綴 /scheduler）
# 僅供 admin 角色使用。
#
# 功能說明：
#   本模組將 order_management.db 的 active 訂單載入排程引擎（SchedulerEngine），
#   支援多種排程演算法（FCFS、SPT、EDD 等），產生甘特圖、瓶頸分析等資料。
#
# 路由清單：
#   GET  /scheduler/                    → 排程儀表板主頁面
#   GET  /scheduler/api/gantt_data      → 甘特圖任務資料
#   GET  /scheduler/api/station_load    → 站點負載分析
#   GET  /scheduler/api/bottleneck      → 瓶頸站點分析
#   GET  /scheduler/api/work_plans      → 列出所有 MES WorkPlan
#   GET  /scheduler/api/compare_algorithms → 比較所有演算法排程結果
#   POST /scheduler/api/reorder         → 手動調整訂單優先順序
#   GET  /scheduler/api/historical_stats → 歷史加工時間統計
# =============================================================

from __future__ import annotations

import json
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, session, abort

from . import login_required, manager_required
from .db import get_order_mgmt_db, get_product_db
from .mes_data_service import MesDataService
from .scheduler_engine import SchedulerEngine, OrderJob, Algorithm

scheduler_bp = Blueprint("scheduler", __name__, url_prefix="/scheduler")


# =============================================================
# 內部 Helper 函式
# =============================================================

def _parse_step_chain_from_str(s: str) -> list[int]:
    """
    解析製程步驟鏈字串（相容現有格式）。
    輸入：'1 -> 2 -> 3'
    輸出：[1, 2, 3]
    """
    if not s:
        return []
    return [int(x.strip()) for x in s.split("->") if x.strip().isdigit()]


def _build_engine_from_active_orders() -> SchedulerEngine:
    """
    從 order_management.db 讀取所有 active/pending_payment 訂單，
    建立並回傳排程引擎（SchedulerEngine）。
    
    流程：
      1. 建立 SchedulerEngine 實例，載入 MES 機台資料（資源/加工時間）
      2. 從 DB 讀取所有 active/pending_payment 訂單
      3. 對每筆訂單建立 OrderJob：
         - 優先嘗試從 MES WorkPlan 取得步驟鏈
         - 若無 MES WorkPlan，則從 standard_process 建構步驟鏈
      4. 將每個 OrderJob 加入引擎
    
    回傳準備好的 SchedulerEngine，可呼叫 .schedule(algo) 取得排程結果。
    """
    engine = SchedulerEngine()
    engine.load_mes_data()  # 載入 MES 機台/製程資料

    conn = get_order_mgmt_db()
    try:
        rows = conn.execute(
            "SELECT order_id, customer_name, product, total_price, note, amount, "
            "step_name, status, date, estimated_delivery "
            "FROM order_list WHERE status IN ('active', 'pending_payment') "
            "ORDER BY date ASC"
        ).fetchall()

        for row in rows:
            order_id     = row["order_id"]
            amount       = max(1, int(row["amount"] or 1))
            step_str     = row["step_name"] or ""
            cust_name    = row["customer_name"] or "未知下單者"
            product_name = row["product"] or "客製產品"
            try:
                total_price = float(row["total_price"] or 0)
            except Exception:
                total_price = 0.0
            note   = row["note"] or "無備註"
            status = row["status"] or ""

            # 讀取 priority（欄位可能不存在於舊資料庫）
            priority = 0
            try:
                priority = int(row["priority"] or 0)
            except Exception:
                pass

            # 讀取 work_plan_no（MES WorkPlan 編號，0 表示未指定）
            wp_no = 0
            try:
                wp_no = int(row["work_plan_no"] or 0)
            except Exception:
                pass

            # 解析交期（estimated_delivery）
            due_date = None
            try:
                ed = row["estimated_delivery"]
                if ed:
                    due_date = datetime.strptime(ed, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

            # 解析建立時間
            created_at = None
            try:
                d = row["date"]
                if d:
                    created_at = datetime.strptime(d, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass

            # 建立訂單工作物件
            order_job = OrderJob(
                order_id=order_id,
                amount=amount,
                work_plan_no=wp_no if wp_no > 0 else 1211,  # 預設使用 1211 完整製程
                customer_name=cust_name,
                product_name=product_name,
                total_price=total_price,
                note=note,
                status=status,
                priority=priority,
                due_date=due_date,
                created_at=created_at,
            )

            # 優先從 MES WorkPlan 載入步驟鏈
            if wp_no > 0:
                plan = MesDataService.get_work_plan(wp_no)
                if plan:
                    order_job.step_chain = plan.ordered_steps

            # 若無 MES 步驟，從 standard_process 建構步驟鏈
            if not order_job.step_chain and step_str:
                chain = _parse_step_chain_from_str(step_str)
                if chain:
                    prod_conn = get_product_db()
                    try:
                        from .mes_data_service import StepDef
                        for step_order in chain:
                            sp = prod_conn.execute(
                                "SELECT step_order, step_name, station, estimated_time_sec "
                                "FROM standard_process WHERE step_order = ?",
                                (step_order,),
                            ).fetchone()
                            if sp:
                                order_job.step_chain.append(
                                    StepDef(
                                        wp_no=0,
                                        step_no=int(sp["step_order"]),
                                        description=sp["step_name"] or "",
                                        op_no=0,
                                        next_step_no=0,
                                        first_step=(step_order == chain[0]),
                                        resource_id=step_order,  # 以 step_order 當作 resource_id
                                        working_time_calc=int(sp["estimated_time_sec"] or 5),
                                    )
                                )
                    finally:
                        prod_conn.close()

            engine.add_order(order_job)
    finally:
        conn.close()

    return engine


# =============================================================
# 頁面路由
# =============================================================

@scheduler_bp.route("/")
@login_required
def dashboard():
    """
    排程儀表板主頁面。
    實際資料由前端 JS 呼叫各 API 取得（非同步）。
    僅 admin 可存取。
    """
    if session.get("role") != "admin":
        abort(403)
    return render_template("scheduler/dashboard.html")


# =============================================================
# API：排程結果資料
# =============================================================

@scheduler_bp.route("/api/gantt_data")
@login_required
def api_gantt_data():
    """
    取得甘特圖任務資料（JSON）。
    URL 參數：?algorithm=fcfs|spt|edd|... (預設 fcfs)
    回傳：
      - algorithm          : 使用的演算法名稱
      - tasks              : 甘特圖任務列表
      - order_sequence     : 訂單排程順序
      - orders_details     : 訂單詳細資訊
      - total_makespan_sec : 總完工時間（秒）
      - bottleneck_station : 瓶頸站點名稱
    """
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

        return jsonify(
            {
                "algorithm":          algo.value,
                "tasks":              result.gantt_data(),
                "order_sequence":     result.order_sequence,
                "orders_details":     result.orders_details,
                "total_makespan_sec": result.total_makespan_sec,
                "bottleneck_station": result.bottleneck_station,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/station_load")
@login_required
def api_station_load():
    """
    取得各站點負載分析（JSON）。
    URL 參數：?algorithm=fcfs|spt|edd|...
    回傳：
      - stations          : 每個站點的工作時間、利用率
      - bottleneck_station: 負載最重的站點（瓶頸）
    """
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

        return jsonify(
            {
                "stations":          result.station_load_data(),
                "bottleneck_station": result.bottleneck_station,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/bottleneck")
@login_required
def api_bottleneck():
    """
    取得瓶頸分析詳細報告（JSON）。
    URL 參數：?algorithm=fcfs|spt|edd|...
    分析結果包含各站點的工作比例、平均等待時間等。
    """
    if session.get("role") != "admin":
        abort(403)

    algo_str = request.args.get("algorithm", "fcfs").lower()
    try:
        algo = Algorithm(algo_str)
    except ValueError:
        algo = Algorithm.FCFS

    try:
        engine   = _build_engine_from_active_orders()
        analysis = engine.analyze_bottleneck(algo)
        return jsonify(analysis)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/work_plans")
@login_required
def api_work_plans():
    """
    列出所有可用的 MES WorkPlan（製程方案）。
    回傳每個 WorkPlan 的步驟清單和總加工時間。
    無需特殊權限（所有登入使用者可用）。
    """
    try:
        plans = MesDataService.get_available_work_plans()
        data  = []
        for wp in plans:
            plan_detail = MesDataService.get_work_plan(wp.wp_no)
            steps = []
            if plan_detail:
                for s in plan_detail.ordered_steps:
                    steps.append(
                        {
                            "step_no":      s.step_no,
                            "description":  s.description,
                            "resource_id":  s.resource_id,
                            "station_name": s.station_label,
                            "working_time": s.working_time_calc,
                        }
                    )
            data.append(
                {
                    "wp_no":       wp.wp_no,
                    "description": wp.description,
                    "short":       wp.short,
                    "steps":       steps,
                    "total_time":  plan_detail.total_working_time if plan_detail else 0,
                }
            )
        return jsonify({"work_plans": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/compare_algorithms")
@login_required
def api_compare_algorithms():
    """
    比較所有排程演算法的結果（JSON）。
    對同一批訂單分別跑每種演算法，回傳各演算法的總完工時間和瓶頸站點。
    可用於選出最佳排程方案。
    """
    if session.get("role") != "admin":
        abort(403)

    try:
        engine     = _build_engine_from_active_orders()
        comparison = []
        for algo in Algorithm:
            result = engine.schedule(algo)
            comparison.append(
                {
                    "algorithm":          algo.value,
                    "total_makespan_sec": result.total_makespan_sec,
                    "bottleneck_station": result.bottleneck_station,
                    "order_sequence":     result.order_sequence,
                }
            )
        return jsonify({"comparison": comparison})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scheduler_bp.route("/api/reorder", methods=["POST"])
@login_required
def api_reorder():
    """
    手動調整訂單的優先排程順序。
    Request Body（JSON）：
      - order_sequence: [order_id, order_id, ...] (前面的訂單優先度高)
    
    實作方式：更新 order_list.priority 欄位，
    priority 值越大 = 優先度越高 = 排在越前面排程。
    """
    if session.get("role") != "admin":
        abort(403)

    data      = request.get_json()
    new_order = data.get("order_sequence", [])
    if not new_order:
        return jsonify({"error": "order_sequence required"}), 400

    conn = get_order_mgmt_db()
    try:
        # 確保 priority 欄位存在（舊 DB 可能沒有）
        cols = [r[1] for r in conn.execute("PRAGMA table_info(order_list)").fetchall()]
        if "priority" not in cols:
            conn.execute("ALTER TABLE order_list ADD COLUMN priority INTEGER DEFAULT 0")

        # 反向遍歷：index 越小的訂單給越大的 priority 值
        for idx, order_id in enumerate(reversed(new_order)):
            conn.execute(
                "UPDATE order_list SET priority = ? WHERE order_id = ?",
                (idx + 1, order_id),
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
    """
    取得各站點的歷史加工時間統計（JSON）。
    資料來源：MesDataService（從 FestoMES.accdb 讀取歷史記錄）
    回傳：
      - stats: 每個站點的 avg/min/max 加工時間和樣本數
    """
    if session.get("role") != "admin":
        abort(403)

    try:
        stats = MesDataService.get_historical_stats()
        names = MesDataService.get_resource_names()
        data  = []
        for (res_id, _), st in stats.items():
            data.append(
                {
                    "resource_id":  res_id,
                    "station_name": names.get(res_id, f"Station-{res_id}"),
                    "avg_duration": round(st.avg_duration, 1),
                    "min_duration": round(st.min_duration, 1),
                    "max_duration": round(st.max_duration, 1),
                    "sample_count": st.sample_count,
                }
            )
        return jsonify({"stats": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
