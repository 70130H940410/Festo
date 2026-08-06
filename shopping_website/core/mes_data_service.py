# core/mes_data_service.py
"""
MES 數據服務層 — 封裝所有與 FestoMES.accdb 的交互。
提供真實工站加工時間、WorkPlan 步驟鏈、歷史統計等查詢。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .db import get_festo_db


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StepDef:
    """一個 WorkPlan 中的單一步驟定義"""
    wp_no: int
    step_no: int
    description: str
    op_no: int
    next_step_no: int
    first_step: bool
    resource_id: int
    working_time_calc: int  # 計劃加工秒數

    @property
    def station_label(self) -> str:
        return _RESOURCE_NAMES.get(self.resource_id, f"Station-{self.resource_id}")


@dataclass
class WorkPlan:
    """一個完整的 WorkPlan（製程路線）"""
    wp_no: int
    description: str
    short: str
    steps: List[StepDef] = field(default_factory=list)

    @property
    def ordered_steps(self) -> List[StepDef]:
        """按照 NextStepNo 鏈結順序排列步驟"""
        if not self.steps:
            return []

        step_map = {s.step_no: s for s in self.steps}

        # 找到 FirstStep
        first = None
        for s in self.steps:
            if s.first_step:
                first = s
                break
        if first is None and self.steps:
            first = min(self.steps, key=lambda s: s.step_no)

        ordered: List[StepDef] = []
        current = first
        visited = set()
        while current and current.step_no not in visited:
            ordered.append(current)
            visited.add(current.step_no)
            nxt = current.next_step_no
            if nxt == 0 or nxt not in step_map:
                break
            current = step_map[nxt]
        return ordered

    @property
    def total_working_time(self) -> int:
        return sum(s.working_time_calc for s in self.ordered_steps)


@dataclass
class ResourceInfo:
    """工站（Resource）基本資訊"""
    resource_id: int
    name: str
    resource_type: Optional[int] = None


@dataclass
class OperationTime:
    """某站對某操作的加工時間"""
    resource_id: int
    op_no: int
    working_time: int  # 秒
    offset_time: int = 0


@dataclass
class FinishedStepRecord:
    """歷史已完工步驟紀錄"""
    wp_no: int
    step_no: int
    order_no: int
    description: str
    resource_id: int
    planned_start: Optional[datetime] = None
    planned_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None

    @property
    def actual_duration_sec(self) -> Optional[float]:
        if self.actual_start and self.actual_end:
            return (self.actual_end - self.actual_start).total_seconds()
        return None

    @property
    def planned_duration_sec(self) -> Optional[float]:
        if self.planned_start and self.planned_end:
            return (self.planned_end - self.planned_start).total_seconds()
        return None


@dataclass
class HistoricalStats:
    """某站某操作的歷史加工時間統計"""
    resource_id: int
    op_no: int
    avg_duration: float
    min_duration: float
    max_duration: float
    sample_count: int


# ---------------------------------------------------------------------------
# 工站名稱對照（來自實際查詢 tblResource）
# ---------------------------------------------------------------------------
_RESOURCE_NAMES: Dict[int, str] = {
    1: "Magazine (上/下蓋站)",
    2: "Pressing (壓合站)",
    3: "ASRS (倉儲站)",
    4: "Camera Inspection (視覺檢測)",
    5: "Robot Assembly (機器人組裝)",
    6: "Measuring (量測站)",
    7: "Drilling (鑽孔站)",
    8: "Heating Oven (加熱站)",
    11: "Feed Front Cover (備用站)",
}


# ---------------------------------------------------------------------------
# 故障原因對照表（用於 Access DB Error 變數說明）
# ---------------------------------------------------------------------------
_ERROR_REASONS: Dict[int, str] = {
    1: "上/下蓋倉儲站料管備料用盡 (Magazine Empty) / 產線退料遮蔽警報",
    2: "壓合站氣壓不足 (<0.4 MPa) / 沖壓模具定位未就位 (Press Position Fault)",
    3: "ASRS 堆垛機立體倉位感測器遮蔽 / 倉位條碼掃描辨識失敗 (ASRS Sensor Fault)",
    4: "視覺檢測站相機未偵測到工件 (Camera found no workpiece) / 檢測光源衰減",
    5: "機器人組裝夾頭夾取工具類型錯誤 (Unknown tool type gripped) / 夾頭未夾緊工件",
    6: "量測探針高度異常 / 產品厚度規格超過設定公差容許值 (Measurement Out-of-Spec)",
    7: "鑽孔刀具磨損告警 (Tool Wear Warning) / 主軸轉速過低",
    8: "加熱爐溫度超過上限 (Overheat Alarm) / 止動器位置無工件 (No Workpiece at Stopper)",
}


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

_CACHE_TTL = 30.0  # 快取 30 秒
_MEMORY_CACHE: Dict[str, Tuple[Any, float]] = {}


def _get_cached(key: str) -> Optional[Any]:
    if key in _MEMORY_CACHE:
        val, ts = _MEMORY_CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return val
    return None


def _set_cached(key: str, val: Any) -> Any:
    _MEMORY_CACHE[key] = (val, time.time())
    return val


def clear_mes_cache():
    """手動清除 MES 快取"""
    _MEMORY_CACHE.clear()


class MesDataService:
    """與 FestoMES.accdb 交互的數據服務"""

    # --- Resources ---

    @staticmethod
    def get_resources() -> List[ResourceInfo]:
        """取得所有工站"""
        cached = _get_cached("resources")
        if cached is not None:
            return cached

        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT ResourceID, ResourceName, ResourceType "
                    "FROM tblResource "
                    "WHERE ResourceType IS NOT NULL OR ResourceName IS NOT NULL"
                )
                res = [
                    ResourceInfo(
                        resource_id=row[0],
                        name=row[1] or f"Station-{row[0]}",
                        resource_type=row[2],
                    )
                    for row in cursor.fetchall()
                ]
                return _set_cached("resources", res)
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] get_resources failed: {e}")
            return [ResourceInfo(resource_id=k, name=v) for k, v in _RESOURCE_NAMES.items()]

    @staticmethod
    def get_resource_names() -> Dict[int, str]:
        """取得 ResourceID → Name 對照表"""
        cached = _get_cached("resource_names")
        if cached is not None:
            return cached

        try:
            resources = MesDataService.get_resources()
            mapping = {r.resource_id: r.name for r in resources}
            merged = dict(_RESOURCE_NAMES)
            merged.update(mapping)
            return _set_cached("resource_names", merged)
        except Exception:
            return dict(_RESOURCE_NAMES)

    # --- Working Times ---

    @staticmethod
    def get_real_working_times() -> List[OperationTime]:
        """取得各站對各操作的真實加工時間 (tblResourceOperation)"""
        cached = _get_cached("real_working_times")
        if cached is not None:
            return cached

        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT ResourceID, OpNo, WorkingTime, OffsetTime "
                    "FROM tblResourceOperation "
                    "WHERE ResourceID > 0 "
                    "ORDER BY ResourceID, OpNo"
                )
                res = [
                    OperationTime(
                        resource_id=row[0],
                        op_no=row[1],
                        working_time=int(row[2] or 0),
                        offset_time=int(row[3] or 0),
                    )
                    for row in cursor.fetchall()
                ]
                return _set_cached("real_working_times", res)
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] get_real_working_times failed: {e}")
            return []

    @staticmethod
    def get_working_time_map() -> Dict[Tuple[int, int], int]:
        """取得 (ResourceID, OpNo) → WorkingTime 查詢表"""
        cached = _get_cached("working_time_map")
        if cached is not None:
            return cached

        times = MesDataService.get_real_working_times()
        res = {(t.resource_id, t.op_no): t.working_time for t in times}
        return _set_cached("working_time_map", res)

    # --- Work Plans ---

    @staticmethod
    def get_available_work_plans() -> List[WorkPlan]:
        """列出所有可用 WorkPlan 定義"""
        cached = _get_cached("available_work_plans")
        if cached is not None:
            return cached

        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT WPNo, Description, Short FROM tblWorkPlanDef "
                    "WHERE WPNo > 0 ORDER BY WPNo"
                )
                plans = []
                for row in cursor.fetchall():
                    plans.append(WorkPlan(
                        wp_no=row[0],
                        description=row[1] or "",
                        short=row[2] or "",
                    ))
                return _set_cached("available_work_plans", plans)
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] get_available_work_plans failed: {e}")
            return []

    @staticmethod
    def get_work_plan(wp_no: int) -> Optional[WorkPlan]:
        """取得某個 WorkPlan 的完整定義（含步驟鏈）"""
        cache_key = f"work_plan_{wp_no}"
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT WPNo, Description, Short FROM tblWorkPlanDef WHERE WPNo = ?",
                    (wp_no,)
                )
                wp_row = cursor.fetchone()
                if not wp_row:
                    return None

                plan = WorkPlan(wp_no=wp_row[0], description=wp_row[1] or "", short=wp_row[2] or "")

                cursor.execute(
                    "SELECT WPNo, StepNo, Description, OpNo, NextStepNo, FirstStep, "
                    "ResourceID, WorkingTimeCalc "
                    "FROM tblStepDef WHERE WPNo = ? ORDER BY StepNo",
                    (wp_no,)
                )
                for row in cursor.fetchall():
                    plan.steps.append(StepDef(
                        wp_no=row[0],
                        step_no=row[1],
                        description=row[2] or "",
                        op_no=row[3],
                        next_step_no=row[4] or 0,
                        first_step=bool(row[5]),
                        resource_id=row[6] or 0,
                        working_time_calc=int(row[7] or 0),
                    ))
                return _set_cached(cache_key, plan)
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] get_work_plan failed: {e}")
            return None

    # --- Machine Errors ---

    @staticmethod
    def get_active_machine_errors() -> List[dict]:
        """
        讀取 Access.db (tblMachineReport) 最新一筆機台回報，
        若 ErrorL0 = True 或 ErrorL1 = True 或 ErrorL2 = True，
        則整理成警示視窗用的詳細資料結構與原因說明。
        """
        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT r.ResourceID, r.ResourceName, m.ErrorL0, m.ErrorL1, m.ErrorL2, m.TimeStamp, m.ID "
                    "FROM tblResource r "
                    "LEFT JOIN tblMachineReport m ON r.ResourceID = m.ResourceID "
                    "WHERE m.ID IN (SELECT MAX(ID) FROM tblMachineReport GROUP BY ResourceID) "
                    "AND (m.ErrorL0 = True OR m.ErrorL1 = True OR m.ErrorL2 = True) "
                    "ORDER BY m.ID DESC"
                )
                errors = []
                for row in cursor.fetchall():
                    res_id = row[0]
                    res_name = row[1] or f"Station-{res_id}"
                    err_l0 = bool(row[2])
                    err_l1 = bool(row[3])
                    err_l2 = bool(row[4])
                    time_stamp = row[5]
                    time_str = time_stamp.strftime("%Y-%m-%d %H:%M:%S") if time_stamp else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    level = "ErrorL0 (一級急停故障)" if err_l0 else ("ErrorL1 (二級製程警報)" if err_l1 else "ErrorL2 (三級系統異常)")
                    reason = _ERROR_REASONS.get(res_id, "機台感測器或機械手通訊異常，請至戰情室檢查。")

                    errors.append({
                        "resource_id": res_id,
                        "resource_name": res_name,
                        "error_l0": err_l0,
                        "error_l1": err_l1,
                        "error_l2": err_l2,
                        "error_level": level,
                        "reason": reason,
                        "timestamp": time_str,
                    })
                return errors
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] get_active_machine_errors failed: {e}")
            return []

    @staticmethod
    def set_machine_error(resource_id: int, error_l0: bool = True) -> bool:
        """在 Access DB (tblMachineReport) 寫入一筆機台狀態紀錄以測試 Error 變數"""
        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO tblMachineReport (ResourceID, [TimeStamp], AutomaticMode, ManualMode, Busy, [Reset], ErrorL0, ErrorL1, ErrorL2) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (resource_id, datetime.now(), True, False, False, False, error_l0, False, False)
                )
                conn.commit()
                clear_mes_cache()
                return True
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] set_machine_error failed: {e}")
            return False

    # --- Machine Status ---

    @staticmethod
    def get_machine_status() -> List[dict]:
        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT ResourceID, ResourceName FROM tblResource "
                    "WHERE ResourceType IS NOT NULL OR ResourceName IS NOT NULL"
                )
                resources = cursor.fetchall()

                machines = []
                for r in resources:
                    cursor.execute(
                        "SELECT TOP 1 AutomaticMode, ManualMode, Busy, ErrorL0 "
                        "FROM tblMachineReport WHERE ResourceID = ? ORDER BY ID DESC",
                        (r[0],)
                    )
                    m = cursor.fetchone()
                    machines.append({
                        "resource_id": r[0],
                        "name": r[1],
                        "automatic": bool(m[0]) if m else False,
                        "manual": bool(m[1]) if m else False,
                        "busy": bool(m[2]) if m else False,
                        "error": bool(m[3]) if m else False,
                    })
                return machines
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] get_machine_status failed: {e}")
            return []

    # --- Historical Statistics ---

    @staticmethod
    def get_finished_steps(limit: int = 200) -> List[FinishedStepRecord]:
        """取得歷史已完工步驟紀錄 (tblFinStep)"""
        try:
            conn = get_festo_db()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT TOP {limit} WPNo, StepNo, ONo, Description, ResourceID, "
                    "PlanedStart, PlanedEnd, Start, [End] "
                    "FROM tblFinStep ORDER BY ONo DESC, StepNo"
                )
                records = []
                for row in cursor.fetchall():
                    records.append(FinishedStepRecord(
                        wp_no=row[0],
                        step_no=row[1],
                        order_no=row[2],
                        description=row[3] or "",
                        resource_id=row[4] or 0,
                        planned_start=row[5],
                        planned_end=row[6],
                        actual_start=row[7],
                        actual_end=row[8],
                    ))
                return records
            finally:
                conn.close()
        except Exception as e:
            print(f"[MesDataService Warning] get_finished_steps failed: {e}")
            return []

    @staticmethod
    def get_historical_stats() -> Dict[Tuple[int, int], HistoricalStats]:
        """
        統計各 (ResourceID, OpNo) 的歷史加工時間。
        基於 tblFinStep 的 Start/End 計算。
        回傳 {(resource_id, op_no): HistoricalStats}
        """
        records = MesDataService.get_finished_steps(limit=500)

        # 按 (resource_id, 描述) 分組計算
        from collections import defaultdict
        groups: Dict[int, List[float]] = defaultdict(list)

        for rec in records:
            dur = rec.actual_duration_sec
            if dur is not None and dur > 0:
                groups[rec.resource_id].append(dur)

        stats: Dict[Tuple[int, int], HistoricalStats] = {}
        for res_id, durations in groups.items():
            if not durations:
                continue
            stats[(res_id, 0)] = HistoricalStats(
                resource_id=res_id,
                op_no=0,  # 聚合所有操作
                avg_duration=sum(durations) / len(durations),
                min_duration=min(durations),
                max_duration=max(durations),
                sample_count=len(durations),
            )
        return stats

    # --- MES Write-back ---

    @staticmethod
    def write_order_to_mes(
        planned_start: datetime,
        planned_end: datetime,
        customer_no: int = 1,
    ) -> int:
        """
        將排程結果寫入 tblOrder，回傳新的 ONo。
        State=1 (排定), Enabled=True
        """
        conn = get_festo_db()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(ONo) FROM tblOrder")
            max_row = cursor.fetchone()
            new_ono = (max_row[0] or 0) + 1 if max_row else 1

            cursor.execute(
                "INSERT INTO tblOrder (ONo, PlanedStart, PlanedEnd, CNo, State, Enabled, Release) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_ono, planned_start, planned_end, customer_no, 1, True, datetime.now())
            )
            conn.commit()
            return new_ono
        finally:
            conn.close()

    @staticmethod
    def get_active_mes_orders() -> List[dict]:
        """取得 MES 中所有進行中的工單"""
        conn = get_festo_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT ONo, PlanedStart, PlanedEnd, Start, [End], State, Enabled "
                "FROM tblOrder ORDER BY ONo DESC"
            )
            orders = []
            for row in cursor.fetchall():
                orders.append({
                    "ono": row[0],
                    "planned_start": row[1],
                    "planned_end": row[2],
                    "actual_start": row[3],
                    "actual_end": row[4],
                    "state": row[5],
                    "enabled": row[6],
                })
            return orders
        finally:
            conn.close()
