"""scheduler_tools.py 排产工具集（M4a T4a.1）-- 11 工具中 4 个实装。

实装（复用 M2 求解器 + M3 模拟器事件表）：
  run_scheduling      求解 + 落库（triggered_by=agent），返回版本号与指标
  query_schedule      查最新（或指定）排产版本 + 批次表
  query_sim_events    查模拟器事件（类型/状态过滤）
  approve_schedule    排版人审批：待审核 -> 已审核/已驳回（单事务含 approvals）

占位（M4b/M5 实装，注册保证工具数 18）：query_ctp / query_load_assessment /
query_order_tracking / query_preprocess_load / query_kpi / query_forecast /
query_yield。

审计在 registry 治理层统一落（写工具执行入审计），handler 保持纯业务。
"""
from __future__ import annotations

from datetime import datetime

from demo.scheduler.snapshot import load_snapshot
from demo.scheduler.solver import persist, solve
from demo.tools.data import format_table, get_connection, transaction

_PLACEHOLDER_M4B = ("query_ctp", "query_load_assessment", "query_order_tracking",
                    "query_preprocess_load", "query_kpi")
_PLACEHOLDER_M5 = ("query_forecast", "query_yield")


def run_scheduling(triggered_by: str = "agent") -> str:
    """触发一轮排产求解并落库（写工具，需 reviewer 审批后生效）。"""
    snapshot = load_snapshot()
    result = solve(snapshot, triggered_by=triggered_by)
    version_id = persist(result, snapshot, triggered_by=triggered_by)
    m = result["metrics"]
    lines = [
        f"✅ 排产完成：版本 {version_id}（待审核）",
        f"求解状态 {m['status']} | 批次 {m['total_batches']} | 零件 {m['total_parts']} 件",
        f"目标值 {m['objective']} | 准交率 {m['on_time_rate']}"
        f"（{m['on_time']}/{m['total_orders']}）| 延期 {len(m['delay_list'])} 单",
        f"timed_out={m['timed_out']} | 求解耗时 {m['solver_duration_ms']:.0f}ms",
    ]
    if result["warnings"]:
        lines.append(f"⚠️ 预警 {len(result['warnings'])} 条（超尺寸/超承重，详见 query_schedule）")
    if result["conflicts"]:
        for c in result["conflicts"]:
            lines.append(f"❌ 冲突：{c['reason']}")
    return "\n".join(lines)


def query_schedule(version_id: int = 0) -> str:
    """查排产表。version_id=0 返回最新版本，否则返回指定版本。"""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if version_id:
                cur.execute("SELECT id, created_at, triggered_by, status "
                            "FROM schedule_versions WHERE id=%s", (version_id,))
            else:
                cur.execute("SELECT id, created_at, triggered_by, status "
                            "FROM schedule_versions ORDER BY id DESC LIMIT 1")
            vrow = cur.fetchone()
            if not vrow:
                return "（暂无排产版本，可先调 run_scheduling）"
            vid = vrow[0]
            cur.execute(
                "SELECT id, order_ids, process, model_type, machine_id, start_time, "
                "end_time, post_process_end, status, approval_status "
                "FROM batches WHERE schedule_version_id=%s ORDER BY start_time, id",
                (vid,))
            cols = [d[0] for d in cur.description]
            batches = [dict(zip(cols, r)) for r in cur.fetchall()]
    header = (f"排产版本 {vrow[0]} | 创建 {vrow[1]} | 触发 {vrow[2]} | "
              f"审批状态 {vrow[3]} | 批次 {len(batches)}")
    return header + "\n" + format_table(batches)


def query_sim_events(event_type: str = "", status: str = "", limit: int = 50) -> str:
    """查模拟器事件表。event_type/status 可选过滤（空=全部）。"""
    conds, params = [], []
    if event_type:
        conds.append("event_type=%s")
        params.append(event_type)
    if status:
        conds.append("status=%s")
        params.append(status)
    where = f"WHERE {' AND '.join(conds)}" if conds else ""
    params.append(max(1, min(limit, 200)))
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT sim_time, event_type, status, payload_json FROM sim_events "
                f"{where} ORDER BY sim_time DESC, id DESC LIMIT %s", tuple(params))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not rows:
        return "（无匹配事件）"
    return format_table(rows)


def approve_schedule(version_id: int, action: str, note: str = "",
                     approver: str = "") -> str:
    """排版人审批排产版本：action=通过|驳回（写工具，reviewer 专属）。

    单事务：schedule_versions.status + batches.approval_status + approvals 行。
    """
    if action not in ("通过", "驳回"):
        return f"❌ 非法审批动作：{action}（仅支持 通过/驳回）"
    version_status = "已审核" if action == "通过" else "已驳回"
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM schedule_versions WHERE id=%s",
                            (version_id,))
                row = cur.fetchone()
                if not row:
                    return f"❌ 排产版本不存在：{version_id}"
                if row[0] != "待审核":
                    return f"❌ 版本 {version_id} 状态为 {row[0]}，仅待审核版本可审批"
                cur.execute("UPDATE schedule_versions SET status=%s WHERE id=%s",
                            (version_status, version_id))
                cur.execute("UPDATE batches SET approval_status=%s "
                            "WHERE schedule_version_id=%s", (action, version_id))
                cur.execute(
                    "INSERT INTO approvals (schedule_version_id, approver, action, "
                    "time, note) VALUES (%s, %s, %s, %s, %s)",
                    (version_id, approver or "reviewer", action, datetime.now(),
                     note or None))
    except Exception as e:  # noqa: BLE001 - 审批失败需给调用方明确反馈
        return f"❌ 审批失败（已回滚）：{type(e).__name__}: {e}"
    return f"✅ 版本 {version_id} 审批{action}（{version_status}），批次同步更新"


def _placeholder(name: str, milestone: str):
    def _handler(**_kwargs) -> str:
        return f"ℹ️ {name} 将在 {milestone} 提供（当前为占位注册，保证工具清单完整）"
    return _handler


PLACEHOLDER_TOOLS = {
    **{n: _placeholder(n, "M4b") for n in _PLACEHOLDER_M4B},
    **{n: _placeholder(n, "M5") for n in _PLACEHOLDER_M5},
}
