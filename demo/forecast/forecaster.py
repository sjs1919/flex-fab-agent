"""聚合与预测入口（M5a T5a.5）。

- history_daily()：orders JOIN parts 按 order_date 逐日聚合分材料件数/机时
- forecast()：读 system_config（预测/forecast_method|forecast_window|smoothing_alpha）
  -> 调 models 纯函数 -> 逐日分材料预测（件数+机时）

口径（用户 2026-08-23 确认）：默认指数平滑 α=0.3，窗口 5 天；机时=Σ(height÷rate×quantity)。
依赖 MySQL 数据源（csv orders 无 order_date 列，预测仅支持 mysql 模式）。
"""
from __future__ import annotations

from datetime import date, timedelta

from ..config import get_config
from .models import exponential_smoothing, moving_average

DEFAULT_METHOD = "exponential"
DEFAULT_WINDOW = 5
DEFAULT_ALPHA = 0.3


def _safe_int(raw: str, fallback: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def _safe_float(raw: str, fallback: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def history_daily(tenant_id: str = "") -> dict[str, dict[str, dict[str, float]]]:
    """按 order_date 逐日聚合分材料件数与机时。

    机时 = Σ(height ÷ rate_mm_h × quantity)，rate 来自 material 表（SLA50/MJS25/SLM15）。
    返回 {material: {date_iso: {"parts": 件数, "hours": 机时}}}；无历史返回 {}。
    """
    from ..tools.data import get_connection

    sql = (
        "SELECT o.order_date, p.material, "
        "SUM(p.quantity) AS parts, "
        "SUM(p.height / m.rate_mm_h * p.quantity) AS hours "
        "FROM orders o JOIN parts p ON p.order_id = o.id "
        "JOIN material m ON p.material = m.process"
    )
    params: tuple = ()
    if tenant_id:
        sql += " WHERE o.tenant_id = %s"
        params = (tenant_id,)
    sql += " GROUP BY o.order_date, p.material ORDER BY o.order_date"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    result: dict[str, dict[str, dict[str, float]]] = {}
    for order_date, material, parts, hours in rows:
        result.setdefault(material, {})[str(order_date)] = {
            "parts": float(parts or 0), "hours": float(hours or 0)}
    return result


def forecast(n_days: int | None = None, tenant_id: str = "") -> dict:
    """逐日分材料预测（件数+机时）。

    - n_days：显式覆盖预测天数（query_forecast(days=...) 透传）；缺省用配置窗口
    - 返回 {method, alpha, window, days, materials: {材料: [{date,parts,hours}...]}, note}
    - 无历史：materials 为空 + note 友好说明
    """
    method = get_config("预测", "forecast_method", DEFAULT_METHOD).strip().lower()
    if method not in ("ma", "exponential"):
        method = DEFAULT_METHOD  # 非法 method 回落 exponential
    window = _safe_int(get_config("预测", "forecast_window", str(DEFAULT_WINDOW)), DEFAULT_WINDOW)
    alpha = _safe_float(get_config("预测", "smoothing_alpha", str(DEFAULT_ALPHA)), DEFAULT_ALPHA)
    days = max(1, int(n_days) if n_days else window)

    hist = history_daily(tenant_id)
    if not hist:
        return {"method": method, "alpha": alpha, "window": window, "days": [],
                "materials": {}, "note": "无历史订单可聚合（需先 seed 或等待订单积累），无法预测"}

    all_dates = sorted({d for per in hist.values() for d in per})
    last = date.fromisoformat(all_dates[-1])
    fc_dates = [str(last + timedelta(days=i)) for i in range(1, days + 1)]

    materials: dict[str, list[dict]] = {}
    for material, by_date in sorted(hist.items()):
        ordered = sorted(by_date)
        parts_series = [by_date[d]["parts"] for d in ordered]
        hours_series = [by_date[d]["hours"] for d in ordered]
        if method == "ma":
            p = moving_average(parts_series, window) or 0.0
            h = moving_average(hours_series, window) or 0.0
            parts_fc, hours_fc = [p] * days, [h] * days
        else:
            parts_fc = exponential_smoothing(parts_series, alpha, days)
            hours_fc = exponential_smoothing(hours_series, alpha, days)
        materials[material] = [
            {"date": d, "parts": round(p, 2), "hours": round(hh, 2)}
            for d, p, hh in zip(fc_dates, parts_fc, hours_fc)]
    return {"method": method, "alpha": alpha, "window": window, "days": fc_dates,
            "materials": materials, "note": ""}
