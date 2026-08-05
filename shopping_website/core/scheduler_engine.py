# core/scheduler_engine.py
"""
工業級排程引擎 — 支持 FCFS / SPT / EDD / Weighted 四種演算法。
基於真實 MES 數據進行排程與交期預估。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from .mes_data_service import MesDataService, WorkPlan, StepDef


# ---------------------------------------------------------------------------
# Enums & data classes
# ---------------------------------------------------------------------------

class Algorithm(Enum):
    FCFS = "fcfs"           # 先到先做
    SPT = "spt"             # 最短加工時間優先
    EDD = "edd"             # 最早交期優先
    WEIGHTED = "weighted"   # 加權複合排程


@dataclass
class OrderJob:
    """一張待排程的訂單"""
    order_id: str
    amount: int                         # 生產件數
    work_plan_no: int                   # MES WorkPlan 編號
    customer_name: str = "未知下單者"     # 下單者姓名
    product_name: str = ""              # 產品名稱
    total_price: float = 0.0            # 總金額
    note: str = "無備註"                 # 備註
    status: str = ""                    # 狀態
    priority: int = 0                   # 0=普通, 1=加急, 2=特急
    due_date: Optional[datetime] = None # 客戶期望交期
    created_at: Optional[datetime] = None
    step_chain: List[StepDef] = field(default_factory=list)

    # 排程結果
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    priority_score: float = 0.0         # 排序分數（越大越優先）

    @property
    def total_working_time(self) -> int:
        """單件加工總時間（秒）"""
        return sum(s.working_time_calc for s in self.step_chain)

    @property
    def total_job_time(self) -> int:
        """所有件的加工總時間（不考慮並行）"""
        return self.total_working_time * self.amount

    def to_detail_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "customer_name": self.customer_name,
            "product_name": self.product_name,
            "amount": self.amount,
            "total_price": self.total_price,
            "note": self.note,
            "status": self.status,
            "total_working_time": self.total_working_time,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S") if self.created_at else "",
            "scheduled_start": self.scheduled_start.strftime("%Y-%m-%d %H:%M:%S") if self.scheduled_start else "",
            "scheduled_end": self.scheduled_end.strftime("%Y-%m-%d %H:%M:%S") if self.scheduled_end else "",
        }


@dataclass
class ScheduledTask:
    """排程結果中的一個任務區塊（甘特圖用）"""
    order_id: str
    piece_no: int
    step_no: int
    resource_id: int
    station_name: str
    op_description: str
    planned_start: datetime
    planned_end: datetime
    duration_sec: int

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "piece_no": self.piece_no,
            "step_no": self.step_no,
            "resource_id": self.resource_id,
            "station_name": self.station_name,
            "op_description": self.op_description,
            "planned_start": self.planned_start.strftime("%Y-%m-%d %H:%M:%S"),
            "planned_end": self.planned_end.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": self.duration_sec,
        }


@dataclass
class ScheduleResult:
    """排程引擎的完整結果"""
    algorithm: Algorithm
    tasks: List[ScheduledTask] = field(default_factory=list)
    order_sequence: List[str] = field(default_factory=list)  # 排程後的訂單順序
    orders_details: Dict[str, dict] = field(default_factory=dict) # 訂單詳細資料
    bottleneck_station: Optional[int] = None
    station_utilization: Dict[int, float] = field(default_factory=dict)  # resource_id → 利用率 (0~1)
    total_makespan_sec: int = 0

    def gantt_data(self) -> List[dict]:
        return [t.to_dict() for t in self.tasks]

    def station_load_data(self) -> List[dict]:
        names = MesDataService.get_resource_names()
        return [
            {
                "resource_id": rid,
                "station_name": names.get(rid, f"Station-{rid}"),
                "utilization": round(util * 100, 1),
            }
            for rid, util in sorted(self.station_utilization.items())
        ]


# ---------------------------------------------------------------------------
# Scheduler Engine
# ---------------------------------------------------------------------------

class SchedulerEngine:
    """
    排程引擎核心。
    
    使用方式：
        engine = SchedulerEngine()
        engine.add_order(OrderJob(...))
        result = engine.schedule(Algorithm.EDD)
    """

    def __init__(self):
        self._orders: List[OrderJob] = []
        self._resource_names: Dict[int, str] = {}
        self._working_time_map: Dict[Tuple[int, int], int] = {}
        self._historical_stats: Dict[Tuple[int, int], float] = {}

    def add_order(self, order: OrderJob) -> None:
        """加入一張待排程訂單"""
        # 如果沒有 step_chain，從 MES 載入
        if not order.step_chain:
            plan = MesDataService.get_work_plan(order.work_plan_no)
            if plan:
                order.step_chain = plan.ordered_steps
        self._orders.append(order)

    def clear_orders(self) -> None:
        self._orders.clear()

    def load_mes_data(self) -> None:
        """預載 MES 數據（工站名稱、加工時間）"""
        self._resource_names = MesDataService.get_resource_names()
        self._working_time_map = MesDataService.get_working_time_map()

    # --- 主排程方法 ---

    def schedule(self, algorithm: Algorithm = Algorithm.FCFS,
                 start_time: Optional[datetime] = None,
                 weights: Optional[Dict[str, float]] = None) -> ScheduleResult:
        """
        根據指定演算法進行排程。
        
        Args:
            algorithm: 排程演算法
            start_time: 排程起始時間，預設為現在
            weights: Weighted 演算法的權重 {"urgency": w1, "spt": w2, "edd": w3}
        
        Returns:
            ScheduleResult 包含甘特圖數據、站點負載等
        """
        if not self._resource_names:
            self.load_mes_data()

        if start_time is None:
            start_time = datetime.now()

        # 1. 根據演算法決定訂單排序
        sorted_orders = self._sort_orders(algorithm, weights)

        # 2. 使用模擬法產生甘特圖排程
        result = self._simulate_schedule(sorted_orders, start_time)
        result.algorithm = algorithm
        result.order_sequence = [o.order_id for o in sorted_orders]

        # 3. 回寫排程結果到 OrderJob
        order_map: Dict[str, OrderJob] = {o.order_id: o for o in sorted_orders}
        for oid in result.order_sequence:
            order_tasks = [t for t in result.tasks if t.order_id == oid]
            if order_tasks:
                oj = order_map.get(oid)
                if oj:
                    oj.scheduled_start = min(t.planned_start for t in order_tasks)
                    oj.scheduled_end = max(t.planned_end for t in order_tasks)

        return result

    # --- 排序策略 ---

    def _sort_orders(self, algorithm: Algorithm,
                     weights: Optional[Dict[str, float]] = None) -> List[OrderJob]:
        orders = list(self._orders)
        if not orders:
            return orders

        if algorithm == Algorithm.FCFS:
            # 先到先做：按建立時間排序
            orders.sort(key=lambda o: o.created_at or datetime.min)

        elif algorithm == Algorithm.SPT:
            # 最短加工時間優先
            orders.sort(key=lambda o: o.total_job_time)

        elif algorithm == Algorithm.EDD:
            # 最早交期優先
            far_future = datetime(2099, 12, 31)
            orders.sort(key=lambda o: o.due_date or far_future)

        elif algorithm == Algorithm.WEIGHTED:
            # 加權複合排程
            w = weights or {"urgency": 0.4, "spt": 0.3, "edd": 0.3}
            now = datetime.now()

            max_job_time = max((o.total_job_time for o in orders), default=1) or 1
            max_urgency = max((o.priority for o in orders), default=1) or 1

            for o in orders:
                # 緊急度分數 (0~1)
                urgency_score = o.priority / max_urgency

                # SPT 分數 (0~1, 越短越高)
                spt_score = 1.0 - (o.total_job_time / max_job_time)

                # EDD 分數 (0~1, 交期越近越高)
                if o.due_date:
                    hours_left = max((o.due_date - now).total_seconds() / 3600, 0.01)
                    edd_score = 1.0 / hours_left  # 越緊迫分數越高
                    edd_score = min(edd_score, 1.0)
                else:
                    edd_score = 0.0

                o.priority_score = (
                    w.get("urgency", 0.4) * urgency_score +
                    w.get("spt", 0.3) * spt_score +
                    w.get("edd", 0.3) * edd_score
                )

            orders.sort(key=lambda o: o.priority_score, reverse=True)

        return orders

    # --- 模擬排程（產生甘特圖數據）---

    def _simulate_schedule(self, orders: List[OrderJob],
                           start_time: datetime) -> ScheduleResult:
        """
        使用離散事件模擬法排程。
        
        模擬邏輯：
        - 每個工站同一時間只能加工一件
        - 同一件工件必須按步驟順序加工
        - 不同件可以在不同站並行加工（流水線效果）
        """
        result = ScheduleResult(algorithm=Algorithm.FCFS)

        # station_free_at[resource_id] = 該站最早可用的時間
        station_free_at: Dict[int, datetime] = {}

        # piece_free_at[(order_id, piece_no)] = 該件最早可用的時間（上一步完成後）
        piece_free_at: Dict[Tuple[str, int], datetime] = {}

        # 統計每站的總忙碌時間
        station_busy_sec: Dict[int, float] = {}

        for order in orders:
            if not order.step_chain:
                continue

            for piece_no in range(1, order.amount + 1):
                for step in order.step_chain:
                    res_id = step.resource_id
                    if res_id <= 0:
                        continue

                    # 加工時間：優先用真實數據，否則用 WorkPlan 定義
                    duration = self._working_time_map.get(
                        (res_id, step.op_no),
                        step.working_time_calc
                    )
                    if duration <= 0:
                        duration = step.working_time_calc or 5

                    # 此件此步驟最早可以開始的時間 = max(站空閒, 上一步完成)
                    piece_key = (order.order_id, piece_no)
                    earliest_piece = piece_free_at.get(piece_key, start_time)
                    earliest_station = station_free_at.get(res_id, start_time)
                    actual_start = max(earliest_piece, earliest_station)
                    actual_end = actual_start + timedelta(seconds=duration)

                    # 更新狀態
                    station_free_at[res_id] = actual_end
                    piece_free_at[piece_key] = actual_end

                    # 統計忙碌時間
                    station_busy_sec[res_id] = station_busy_sec.get(res_id, 0) + duration

                    # 記錄排程任務
                    result.tasks.append(ScheduledTask(
                        order_id=order.order_id,
                        piece_no=piece_no,
                        step_no=step.step_no,
                        resource_id=res_id,
                        station_name=self._resource_names.get(res_id, f"Station-{res_id}"),
                        op_description=step.description,
                        planned_start=actual_start,
                        planned_end=actual_end,
                        duration_sec=duration,
                    ))

        # 計算總工期與記錄訂單詳情
        for order in orders:
            result.orders_details[order.order_id] = order.to_detail_dict()

        if result.tasks:
            overall_start = min(t.planned_start for t in result.tasks)
            overall_end = max(t.planned_end for t in result.tasks)
            result.total_makespan_sec = int((overall_end - overall_start).total_seconds())

            # 計算站點利用率
            total_span = max(result.total_makespan_sec, 1)
            for res_id, busy_sec in station_busy_sec.items():
                result.station_utilization[res_id] = min(busy_sec / total_span, 1.0)

            # 找瓶頸站
            if result.station_utilization:
                result.bottleneck_station = max(
                    result.station_utilization,
                    key=result.station_utilization.get
                )

        return result

    # --- 交期預估 ---

    def estimate_delivery(self, order: OrderJob,
                          start_time: Optional[datetime] = None) -> datetime:
        """
        精準預估單張訂單的交期。
        考慮：流水線並行、站點排隊（前面的訂單佔用）、真實加工時間。
        """
        if not self._resource_names:
            self.load_mes_data()

        if start_time is None:
            start_time = datetime.now()

        # 把這張訂單加入現有排程，模擬整體
        temp_engine = SchedulerEngine()
        temp_engine._resource_names = self._resource_names
        temp_engine._working_time_map = self._working_time_map

        # 先加入現有訂單
        for existing in self._orders:
            temp_engine.add_order(existing)
        # 再加入新訂單
        temp_engine.add_order(order)

        result = temp_engine.schedule(Algorithm.FCFS, start_time)

        # 找出這張訂單的最晚完成時間
        order_tasks = [t for t in result.tasks if t.order_id == order.order_id]
        if order_tasks:
            return max(t.planned_end for t in order_tasks)

        # fallback: 簡單計算
        total_sec = order.total_job_time
        return start_time + timedelta(seconds=total_sec)

    # --- 產能分析 ---

    def analyze_bottleneck(self, algorithm: Algorithm = Algorithm.FCFS) -> dict:
        """分析瓶頸站"""
        result = self.schedule(algorithm)
        names = self._resource_names

        station_tasks: Dict[int, List[ScheduledTask]] = {}
        for t in result.tasks:
            station_tasks.setdefault(t.resource_id, []).append(t)

        analysis = []
        for res_id, tasks in sorted(station_tasks.items()):
            total_busy = sum(t.duration_sec for t in tasks)
            queue_count = len(tasks)
            analysis.append({
                "resource_id": res_id,
                "station_name": names.get(res_id, f"Station-{res_id}"),
                "total_busy_sec": total_busy,
                "task_count": queue_count,
                "utilization": result.station_utilization.get(res_id, 0),
                "is_bottleneck": res_id == result.bottleneck_station,
            })

        analysis.sort(key=lambda x: x["utilization"], reverse=True)

        return {
            "bottleneck": {
                "resource_id": result.bottleneck_station,
                "station_name": names.get(result.bottleneck_station or 0, "Unknown"),
            },
            "stations": analysis,
            "total_makespan_sec": result.total_makespan_sec,
        }
