# M5b 看板 Dashboard 踩坑（2026-08-24）

> 按 `rules/common/pitfalls.md` 从 todo-M5b 踩坑记录区迁移 M5b 执行期新增项（第 9-12 条）。第 1-8 条为计划期预判，均按预期处理，不迁移。格式复用 M5a 文件。

## 1. csv 模式 kpi_metrics KeyError 'id' 新暴露路径：MySQL 连接 + csv load_machines 错配（存量 bug 复发）

- **根因**：`DEMO_DATA_SOURCE` 默认 csv，`load_machines()` 走 csv.DictReader 返回中文表头键（机器编号/型号）无 `id`，`{m["id"]: m ...}` 抛 KeyError。M5a 已记录（csv 模式 query_kpi 本就不通）。M5b 把 `kpi_metrics()` 挂进每 tick 后，**新的暴露路径**：`test_runner_ticks` 一直处于「MySQL 连接 + csv 读取」错配态（M5b 前 run_tick 不读 load_machines 所以从未触发），现在每 tick 抛 KeyError + 额外 DB 查询，10s 死线被撑爆。
- **教训**：依赖 DB 计算的测试必须显式 `DEMO_DATA_SOURCE=mysql`（仓库既有约定：test_scheduler_tools fixture、forecast/assessment/solver 测试都这么做）。csv 是离线兜底不是正式数据源。
- **规避**：`test_runner_ticks` 加 `monkeypatch.setenv("DEMO_DATA_SOURCE", "mysql")`。csv 模式的 query_kpi 修复记为待办（不属 M5b 范围）。
- **升级为规则**：否（M5a 已记 #1；本轮是同一根因的新暴露路径）。

## 2. GIL 饿死忙等主线程：CPU 密集 kpi_metrics 进 worker 后，测试忙等 10s/tick（本轮新增）

- **根因**：`kpi_metrics()` 是 ~364ms CPU 密集（持 GIL 连续计算）。挂进 run_tick（worker 线程）后，测试主线程的**忙等循环**（`while tick_count < 3: assert monotonic() < deadline`）持续抢 GIL，worker 被饿死到单 tick 10s（sleep 轮询时 3 tick 仅 0.45s）。
- **教训**：① 忙等循环是反模式，必配短 `time.sleep()` 让出 GIL；② 生产主线程是 async 事件循环（会 sleep/yield），无此问题——纯测试工件。
- **规避**：`test_runner_ticks` 轮询加 `_time.sleep(0.01)`，保留 10s deadline 断言。
- **升级为规则**：是候选——若再出现测试忙等饿死线程 → 升级 `rules/common/`「测试轮询必须带 sleep」。

## 3. ECharts init 于 v-show 隐藏 div → 0 尺寸图（本轮新增）

- **根因**：`v-show` 绑定的 div 初始 `display:none`，echarts.init 在隐藏容器上得到 0×0，图表不渲染。
- **教训**：数据到位后必须 `await nextTick()` 等 v-show 渲染完成再 init。
- **规避**：DashboardView onMounted 里 `await nextTick()` 后调 `renderKpiChart()`/`renderCostChart()`。
- **升级为规则**：否（前端框架约定）。

## 4. yield_rate Decimal → str：json.dumps(default=str) 使快照类型不一致（本轮新增·真 Bug）

- **根因**：`_kpi_yield_rate` 返回 `round(Decimal, 4)`，`record_kpi_snapshot` 做 `json.dumps(metrics, default=str)` 时 Decimal 被序列化成字符串 `"0.9507"`，回读后 yield_rate 是 str、on_time_rate 是 float——类型不一致，前端渲染良率会拿到字符串。E2E 断言 `latest["yield_rate"] == fresh["yield_rate"]`（str vs Decimal）暴露。
- **教训**：JSON 持久化边界必须显式定类型。kpi_metrics 出口 `float(yield_rate)`（与 delay_total 同模式），避免 Decimal 泄漏到序列化。
- **规避**：`scheduler_tools.py` 出口统一 float；`on_time_rate`/`delay_total` 已是 float，唯 yield_rate 漏网。
- **升级为规则**：是候选——「kpi_metrics 返回 dict 的数值字段全部显式 float」加入 scheduler_tools 相关规则。
