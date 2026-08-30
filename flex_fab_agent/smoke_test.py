"""demo 部署冒烟测试脚本。

分层递进验证，部署完成后必跑，全部通过才进入界面验收。

用例清单（与部署指南 §9 对齐）：
  S0  安全扫描     credentials.local.md 不入库 + .env 无明文 L1/L2 口令
  S1  地基自检     provider 可用 + 工具注册表非空 + 数据加载成功
  S2  数据层       MySQL 迁移状态（mysql 模式）或 CSV 文件齐全（csv 模式）
  S3  数据完整性   订单≥20 / 设备=7 / 零件≥100 / 客户=5
  S4  API 探针     /health 返回 status=ok + providers 非空 + tools>0
  S5  API KPI      /kpi 返回非空报告
  S6  API 配置     /config 返回 data_source + 调试台配置
  S7  排产求解     run_scheduling 生成 version + batches，无异常
  S8  API 排产     /schedule/latest 返回最新版本 + 批次列表
  S9  模拟器       启动后 tick 递增
  S10 Agent 问答   /ask 返回 answer + tool_results + trace_id（调真实 LLM，可跳过）
  S11 前端页面     页面 HTTP 200（可选，需前端已启动）

用法：
  python demo/smoke_test.py                    # 默认全跑（S0-S10，S10 调 LLM）
  python demo/smoke_test.py --skip-llm         # 跳过 S10（不烧 token）
  python demo/smoke_test.py --check-frontend   # 追加 S11
  python demo/smoke_test.py --scan-secrets     # 只跑 S0 安全扫描（快速校验）
  python demo/smoke_test.py --base-url http://host:8000  # HTTP 模式（默认进程内）

退出码：
  0   全部通过
  非0 失败用例数
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# 确保 demo 包可导入（与 conftest.py 同逻辑）
AGENT_TRAINING_ROOT = Path(__file__).resolve().parent.parent
if str(AGENT_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_TRAINING_ROOT))

from flex_fab_agent.config import available_providers, get_data_source, CREDENTIALS_FILE  # noqa: E402

# ---- 结果收集 ----

results: list[dict] = []
fail_count = 0
_skip_llm_mode = False  # --skip-llm 模式下，LLM 相关检查降级为 skip


def _pass(code: str, name: str, detail: str = "") -> None:
    results.append({"code": code, "name": name, "status": "PASS", "detail": detail})
    print(f"  ✅ {code} {name}" + (f" — {detail}" if detail else ""))


def _fail(code: str, name: str, detail: str = "") -> None:
    global fail_count
    fail_count += 1
    results.append({"code": code, "name": name, "status": "FAIL", "detail": detail})
    print(f"  ❌ {code} {name}" + (f" — {detail}" if detail else ""))


def _skip(code: str, name: str, detail: str = "") -> None:
    results.append({"code": code, "name": name, "status": "SKIP", "detail": detail})
    print(f"  ⏭️  {code} {name}" + (f" — {detail}" if detail else ""))


def _section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ============================================================
# S0  安全扫描
# ============================================================

def s0_secrets_scan() -> None:
    _section("S0 · 安全扫描")

    # S0.1 credentials.local.md 不入库
    import subprocess
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain", "--ignored", str(CREDENTIALS_FILE)],
            capture_output=True, text=True, cwd=str(AGENT_TRAINING_ROOT))
        # 被忽略的文件以 '!! ' 开头；如果是 '?? ' 或 ' M ' 等则是未忽略或已跟踪
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        if not lines:
            _pass("S0.1", "凭据文件不入库", "git 未跟踪（gitignore 生效）")
        elif all(l.startswith("!! ") for l in lines):
            _pass("S0.1", "凭据文件不入库", "已被 gitignore（ignored）")
        else:
            _fail("S0.1", "凭据文件不入库", f"git 状态异常: {lines}")
    except FileNotFoundError:
        _skip("S0.1", "凭据文件不入库", "环境无 git（容器内），跳过")
    except Exception as e:
        _fail("S0.1", "凭据文件不入库", f"git 命令失败: {e}")

    # S0.2 .env 无明文 L1/L2 口令（简单模式匹配）
    env_path = AGENT_TRAINING_ROOT / ".env"
    if not env_path.exists():
        _skip("S0.2", ".env 无明文口令", ".env 不存在")
    else:
        content = env_path.read_text(encoding="utf-8")
        suspicious = []
        # 匹配 *_PASSWORD / *_KEY / *_SECRET = 值，且值不是空/占位符/false/数字端口
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
            if not m:
                continue
            key, val = m.group(1), m.group(2)
            # 只检查敏感字段名
            if not re.search(r"(PASSWORD|API_KEY|SECRET|TOKEN|AUTH)", key):
                continue
            # 跳过明确的占位符 / false / 空
            if any(marker in val.lower() for marker in ("your-", "占位", "todo", "xxxx")):
                continue
            if val.lower() in ("false", "true", "null", "none", ""):
                continue
            # 值看起来像真实密钥（长度>8，含字母数字）
            if len(val) >= 8 and re.search(r"[a-zA-Z]", val) and re.search(r"[0-9]", val):
                suspicious.append(f"{key}={val[:4]}*** (len={len(val)})")
        if suspicious:
            _fail("S0.2", ".env 无明文口令", f"发现 {len(suspicious)} 个疑似明文口令: {', '.join(suspicious)}; 建议迁移到 credentials.local.md")
        else:
            _pass("S0.2", ".env 无明文口令", "未发现 L1/L2 级明文口令")

    # S0.3 credentials.local.md 存在性（按数据源+LLM需求判断是否必需）
    ds = get_data_source()
    need_creds = (ds == "mysql")   # MySQL 模式必须有凭据文件
    if not CREDENTIALS_FILE.exists():
        if need_creds:
            _fail("S0.3", "凭据文件存在",
                  f"未找到 {CREDENTIALS_FILE}；MySQL 模式必须配置，请从 example 复制并填充")
        else:
            _skip("S0.3", "凭据文件存在",
                  f"CSV 模式下非必需；如启用 MySQL 或 LLM key 走凭据文件，请先创建 {CREDENTIALS_FILE.name}")
        _skip("S0.4", "凭据文件权限", "文件不存在，跳过")
    else:
        _pass("S0.3", "凭据文件存在", str(CREDENTIALS_FILE))
        # 文件权限检查（仅 POSIX 系统有效）
        try:
            mode = CREDENTIALS_FILE.stat().st_mode
            perms = oct(mode & 0o777)
            if perms in ("0o600", "0o400"):
                _pass("S0.4", "凭据文件权限", perms)
            else:
                _fail("S0.4", "凭据文件权限", f"当前 {perms}，建议 chmod 600")
        except Exception as e:
            _skip("S0.4", "凭据文件权限", f"无法检查: {e}")


# ============================================================
# S1  地基自检
# ============================================================

def s1_foundation() -> None:
    _section("S1 · 地基自检")

    # S1.1 provider 可用
    providers = available_providers()
    if providers:
        _pass("S1.1", "LLM Provider 可用", ", ".join(p["name"] for p in providers))
    elif _skip_llm_mode:
        _skip("S1.1", "LLM Provider 可用", "--skip-llm 模式下未配置 API Key，跳过")
    else:
        _fail("S1.1", "LLM Provider 可用", "没有可用 provider；请检查 .env 或 credentials.local.md 的 API Key")

    # S1.2 工具注册表
    try:
        from flex_fab_agent.tools.registry import build_default_registry
        registry = build_default_registry()
        if len(registry) > 0:
            _pass("S1.2", "工具注册表", f"共 {len(registry)} 个工具")
        else:
            _fail("S1.2", "工具注册表", "工具数为 0")
    except Exception as e:
        _fail("S1.2", "工具注册表", f"构建失败: {e}")

    # S1.3 数据加载
    try:
        from flex_fab_agent.tools.data import load_orders
        orders = load_orders()
        data_source = get_data_source()
        if len(orders) > 0:
            _pass("S1.3", "数据加载", f"数据源={data_source}, 订单={len(orders)} 条")
        else:
            _fail("S1.3", "数据加载", f"数据源={data_source}, 订单为 0")
    except Exception as e:
        _fail("S1.3", "数据加载", f"失败: {e}")


# ============================================================
# S2  数据层迁移状态
# ============================================================

def s2_data_layer() -> None:
    _section("S2 · 数据层")

    ds = get_data_source()
    if ds == "mysql":
        try:
            from flex_fab_agent.schema.migrate import status
            s = status()
            versions = [v["version"] for v in s["versions"]]
            if max(versions or [0]) >= 3 and s["table_count"] >= 18:
                _pass("S2.1", "MySQL 迁移状态", f"version={max(versions)}, tables={s['table_count']}")
            else:
                _fail("S2.1", "MySQL 迁移状态", f"version={max(versions or [0])}, tables={s['table_count']}; 请执行 python -m flex_fab_agent.schema.migrate --up")
        except Exception as e:
            _fail("S2.1", "MySQL 迁移状态", f"失败: {e}")
    else:
        # CSV 模式：检查关键数据文件
        data_dir = AGENT_TRAINING_ROOT / "demo" / "data"
        required = ["orders.csv", "customers.csv", "machines.csv", "inventory.csv", "parts.csv"]
        missing = [f for f in required if not (data_dir / f).exists()]
        if not missing:
            _pass("S2.1", "CSV 数据文件齐全", f"数据源={ds}, 共 {len(required)} 个核心文件")
        else:
            _fail("S2.1", "CSV 数据文件齐全", f"缺失: {', '.join(missing)}")


# ============================================================
# S3  数据完整性
# ============================================================

def s3_data_integrity() -> None:
    _section("S3 · 数据完整性")

    try:
        from flex_fab_agent.tools.data import load_orders, load_machines, load_parts, load_customers
        orders = load_orders()
        machines = load_machines()
        parts = load_parts()
        customers = load_customers()

        # 订单 >= 20（2026-08-28 seed 40→20：40 订单 166 批超 7 设备 5 天产能 → solver infeasible）
        if len(orders) >= 20:
            _pass("S3.1", "订单数量", f"{len(orders)} 条 (≥20)")
        else:
            _fail("S3.1", "订单数量", f"{len(orders)} 条 (<20)")
        # 设备 = 7
        if len(machines) == 7:
            _pass("S3.2", "设备数量", f"{len(machines)} 台 (=7)")
        else:
            _fail("S3.2", "设备数量", f"{len(machines)} 台 (≠7)")
        # 零件 >= 100
        if len(parts) >= 100:
            _pass("S3.3", "零件数量", f"{len(parts)} 件 (≥100)")
        else:
            _fail("S3.3", "零件数量", f"{len(parts)} 件 (<100)")
        # 客户 = 5
        if len(customers) == 5:
            _pass("S3.4", "客户数量", f"{len(customers)} 个 (=5)")
        else:
            _fail("S3.4", "客户数量", f"{len(customers)} 个 (≠5)")
    except Exception as e:
        _fail("S3.x", "数据完整性检查", f"异常: {e}")


# ============================================================
# 内部 HTTP 客户端（--base-url 模式用）
# ============================================================

_http_client = None


def _get_http_client(base_url: str):
    global _http_client
    if _http_client is None:
        import httpx
        _http_client = httpx.Client(base_url=base_url, timeout=30)
    return _http_client


# ============================================================
# S4-S6  API 基础端点
# ============================================================

def s4_api_health(base_url: str | None) -> None:
    _section("S4 · API /health")

    data = _call_api("GET", "/health", base_url)
    if data is None:
        return
    if data.get("status") == "ok":
        _pass("S4.1", "status=ok")
    else:
        _fail("S4.1", "status=ok", f"实际: {data.get('status')}")
    if data.get("providers"):
        _pass("S4.2", "providers 非空", ", ".join(data["providers"]))
    elif _skip_llm_mode:
        _skip("S4.2", "providers 非空", "--skip-llm 模式下未配置 API Key，跳过")
    else:
        _fail("S4.2", "providers 非空")
    tools = data.get("tools", 0)
    if tools > 0:
        _pass("S4.3", f"tools={tools}")
    else:
        _fail("S4.3", "tools>0", f"实际: {tools}")
    # sim 字段存在
    if "sim" in data:
        _pass("S4.4", "sim 状态可查", f"running={data['sim'].get('running')}, tick={data['sim'].get('tick_count')}")
    else:
        _fail("S4.4", "sim 状态可查")


def s5_api_kpi(base_url: str | None) -> None:
    _section("S5 · API /kpi")

    data = _call_api("GET", "/kpi", base_url)
    if data is None:
        return
    report = data.get("report", "")
    if report and len(report) > 50:
        _pass("S5.1", "KPI 报告非空", f"长度 {len(report)} 字符")
    else:
        _fail("S5.1", "KPI 报告非空", f"长度 {len(report)}")


def s6_api_config(base_url: str | None) -> None:
    _section("S6 · API /config")

    data = _call_api("GET", "/config", base_url)
    if data is None:
        return
    if "data_source" in data:
        _pass("S6.1", "data_source", data["data_source"])
    else:
        _fail("S6.1", "data_source 字段存在")
    if "调试台" in data:
        _pass("S6.2", "调试台配置", f"keys={list(data['调试台'].keys())}")
    else:
        _fail("S6.2", "调试台配置存在")


def _call_api(method: str, path: str, base_url: str | None):
    """HTTP 模式走 httpx；进程内模式直接调 FastAPI app（TestClient）。"""
    try:
        if base_url:
            r = _get_http_client(base_url).request(method, path)
            r.raise_for_status()
            return r.json()
        else:
            from fastapi.testclient import TestClient
            from flex_fab_agent.api import app
            client = TestClient(app)
            resp = client.request(method, path)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        _fail("HTTP", f"{method} {path}", f"请求失败: {e}")
        return None


# ============================================================
# S7  排产求解
# ============================================================

def s7_scheduling() -> None:
    _section("S7 · 排产求解")

    try:
        from flex_fab_agent.tools.scheduler_tools import run_scheduling
        result = run_scheduling(triggered_by="smoke_test")
        # run_scheduling 返回格式化字符串，包含 "✅ 排产完成：版本 N" 等信息
        text = result if isinstance(result, str) else str(result)
        has_version = "排产完成" in text and "版本" in text
        has_batches = "批次" in text
        if has_version and has_batches:
            # 提取版本号和批次信息用于展示
            first_line = text.split("\n")[0]
            _pass("S7.1", "排产成功", first_line)
        else:
            _fail("S7.1", "排产成功", f"result={result}")
    except Exception as e:
        _fail("S7.1", "排产成功", f"异常: {e}")


# ============================================================
# S8  API 排产查询
# ============================================================

def s8_api_schedule(base_url: str | None) -> None:
    _section("S8 · API /schedule/latest")

    data = _call_api("GET", "/schedule/latest", base_url)
    if data is None:
        return
    version = data.get("version")
    batches = data.get("batches", [])
    if version:
        _pass("S8.1", "排产版本存在", f"id={version.get('id')}, status={version.get('status')}")
    else:
        _fail("S8.1", "排产版本存在", "version=null；请先跑排产")
    if batches:
        _pass("S8.2", "批次列表", f"{len(batches)} 个批次")
    else:
        _fail("S8.2", "批次列表", "空")


# ============================================================
# S9  模拟器
# ============================================================

def s9_simulator(base_url: str | None) -> None:
    _section("S9 · 模拟器")

    # 启动
    data_start = _call_api("POST", "/sim/start", base_url)
    if data_start is None:
        return
    # 根据 tick_seconds 动态决定等待时间（至少等 1.2 个 tick 周期）
    tick_seconds = float(data_start.get("tick_seconds", 60))
    wait_seconds = max(tick_seconds * 1.2, 3)
    # 但冒烟测试不能等太久，最多等 10 秒（如果 tick 周期太长，跳过递增检查）
    wait_for_tick = min(wait_seconds, 10)

    time.sleep(wait_for_tick)
    data1 = _call_api("GET", "/sim/status", base_url)
    if data1 is None:
        return
    tick1 = data1.get("tick_count", 0)
    running = data1.get("running", False)
    if running:
        _pass("S9.1", "模拟器运行中", f"tick={tick1}, tick_seconds={tick_seconds}")
    else:
        _fail("S9.1", "模拟器运行中", f"running={running}")
        return

    if tick_seconds > 8:
        # tick 周期太长（>8s），跳过递增检查（避免冒烟测试卡太久）
        _skip("S9.2", "tick 递增", f"tick 周期 {tick_seconds}s 太长，跳过递增检查")
        return

    # 再等一个 tick 周期
    time.sleep(tick_seconds + 1)
    data2 = _call_api("GET", "/sim/status", base_url)
    if data2 is None:
        return
    tick2 = data2.get("tick_count", 0)
    if tick2 > tick1:
        _pass("S9.2", "tick 递增", f"{tick1} → {tick2}")
    else:
        _fail("S9.2", "tick 递增", f"{tick1} → {tick2}（未增长）")


# ============================================================
# S10  Agent 问答（调真实 LLM）
# ============================================================

def s10_agent_ask(base_url: str | None) -> None:
    _section("S10 · Agent 问答（调真实 LLM）")

    payload = json.dumps({"query": "现在有多少条待排队订单？用一句话回答。"})
    try:
        if base_url:
            r = _get_http_client(base_url).post("/ask", content=payload,
                                                headers={"Content-Type": "application/json"})
            r.raise_for_status()
            data = r.json()
        else:
            from fastapi.testclient import TestClient
            from flex_fab_agent.api import app
            client = TestClient(app)
            resp = client.post("/ask", json={"query": "现在有多少条待排队订单？用一句话回答。"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        _fail("S10.1", "/ask 请求成功", f"失败: {e}")
        return

    answer = data.get("answer", "")
    tool_results = data.get("tool_results", [])
    trace_id = data.get("trace_id", "")

    if answer and len(answer) > 5:
        _pass("S10.1", "回答非空", f"长度 {len(answer)} 字符")
    else:
        _fail("S10.1", "回答非空", f"长度 {len(answer)}")

    if tool_results:
        _pass("S10.2", "工具调用记录", f"{len(tool_results)} 次调用")
    else:
        _fail("S10.2", "工具调用记录", "空（Agent 可能未调用工具就回答了）")

    if trace_id:
        _pass("S10.3", "trace_id 存在", trace_id[:16] + "...")
    else:
        _fail("S10.3", "trace_id 存在")


# ============================================================
# S11  前端页面（可选）
# ============================================================

def s11_frontend(front_url: str) -> None:
    _section("S11 · 前端页面")

    import httpx
    pages = [
        ("/", "首页 / Dashboard"),
        ("/#/debug", "调试台"),
        ("/#/cases", "案例库"),
        ("/#/config", "配置页"),
    ]
    for path, name in pages:
        try:
            r = httpx.get(front_url + path, timeout=10)
            if r.status_code == 200:
                _pass("S11", name, f"HTTP {r.status_code}")
            else:
                _fail("S11", name, f"HTTP {r.status_code}")
        except Exception as e:
            _fail("S11", name, f"失败: {e}")


# ============================================================
# 主流程
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="demo 部署冒烟测试")
    parser.add_argument("--base-url", default=None,
                        help="后端 API 地址（如 http://localhost:8000）；不传则进程内直调 FastAPI app")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 S10 Agent 问答（不烧 token）")
    parser.add_argument("--check-frontend", action="store_true", help="追加 S11 前端页面检查")
    parser.add_argument("--frontend-url", default="http://localhost:5173", help="前端地址（默认 http://localhost:5173）")
    parser.add_argument("--scan-secrets", action="store_true", help="只跑 S0 敏感信息扫描，快速校验")
    args = parser.parse_args()

    global _skip_llm_mode
    _skip_llm_mode = args.skip_llm

    print("=" * 60)
    print("  demo 部署冒烟测试")
    print(f"  模式: {'HTTP ' + args.base_url if args.base_url else '进程内直调'}")
    print(f"  数据源: {get_data_source()}")
    print("=" * 60)

    # S0 安全扫描（必跑）
    s0_secrets_scan()

    if args.scan_secrets:
        _print_summary()
        return fail_count

    # 若 S0 有 L1 级失败（凭据文件不存在），不继续（地基都没打好）
    if not CREDENTIALS_FILE.exists() and get_data_source() == "mysql":
        print("\n⚠️  MySQL 模式但凭据文件不存在，跳过后续数据层检查")
        _print_summary()
        return fail_count

    # S1 地基
    s1_foundation()
    if fail_count > 0:
        print("\n⚠️  地基自检有失败项，继续后续用例供参考，但建议先修 S1")

    # S2 数据层
    s2_data_layer()

    # S3 数据完整性
    s3_data_integrity()

    # S4 API health
    s4_api_health(args.base_url)

    # S5 API kpi
    s5_api_kpi(args.base_url)

    # S6 API config
    s6_api_config(args.base_url)

    # S7 排产
    s7_scheduling()

    # S8 API 排产查询
    s8_api_schedule(args.base_url)

    # S9 模拟器
    s9_simulator(args.base_url)

    # S10 Agent 问答
    if args.skip_llm:
        _section("S10 · Agent 问答（跳过）")
        _skip("S10", "Agent 问答", "--skip-llm 已设置")
    else:
        s10_agent_ask(args.base_url)

    # S11 前端（可选）
    if args.check_frontend:
        s11_frontend(args.frontend_url)

    _print_summary()
    return fail_count


def _print_summary() -> None:
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    skipped = sum(1 for r in results if r["status"] == "SKIP")

    print(f"\n{'='*60}")
    print(f"  冒烟测试结果汇总")
    print(f"{'='*60}")
    print(f"  ✅ 通过: {passed}")
    print(f"  ❌ 失败: {failed}")
    print(f"  ⏭️  跳过: {skipped}")
    print(f"  总计: {len(results)}")

    if failed > 0:
        print(f"\n  失败项:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    - {r['code']} {r['name']}: {r['detail']}")
        print(f"\n  ❌ 未通过，请修复后重跑；不进入界面验收")
    else:
        print(f"\n  ✅ 全部通过，可进入界面验收")


if __name__ == "__main__":
    raise SystemExit(main())
