-- ============================================================
-- demo 业务库建表脚本（M1 · v2 重构方案 §4.1 + v1 §3 字段定义）
-- 库：demo_scheduling（WSL MySQL 8.0，utf8mb4）
--
-- 表所有权（v2 §4.2，写方唯一，交叉只读快照）：
--   业务表   customer/orders/parts/machines/material/inventory/personnel → 写方 seed + 模拟器 B 层（订单到达/restock/leave）
--   求解输出 schedule_versions/batches/preprocess_tasks         → 写方 solver（approval_status → approve_schedule）
--   配置     system_config                                     → 写方 运维/配置 API
--   模拟/审计 sim_clock/state_change_log/sim_events            → 写方 simulator
--   审批     approvals                                         → 写方 approve_schedule
--
-- 幂等：全部 CREATE TABLE IF NOT EXISTS，重复执行无副作用（配合 migrate.py schema_version）。
-- 建表顺序按外键依赖拓扑（父表在前），避免循环依赖（batches.machine_id 仅索引不设 FK）。
-- ============================================================

-- ---------------- 业务表 ----------------

-- 客户（写方：seed + 模拟器 B 层；读方：solver/tools/forecast）
CREATE TABLE IF NOT EXISTS customer (
    id            CHAR(8)      NOT NULL COMMENT '客户编号',
    name          VARCHAR(64)  NOT NULL COMMENT '客户名',
    level         ENUM('S','A','B','C') NOT NULL COMMENT '客户等级（去 D，v2 §4.1）',
    credit_score  INT          NOT NULL DEFAULT 0 COMMENT '信用分（仅展示，不进权重公式）',
    discount_rate DECIMAL(3,2) NOT NULL DEFAULT 0.00 COMMENT '折扣率',
    industry      VARCHAR(64)  DEFAULT NULL COMMENT '行业',
    penalty_rate  DECIMAL(4,3) NOT NULL DEFAULT 0.000 COMMENT '违约金日费率（S=0.01/A=0.005/B=C=0.003）',
    tenant_id     VARCHAR(32)  NOT NULL DEFAULT 'default' COMMENT 'R8 租户隔离',
    PRIMARY KEY (id),
    KEY idx_customer_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='客户（所有权：seed + B 层）';

-- 订单（写方：seed + 模拟器 B 层；读方：solver/tools/forecast）
CREATE TABLE IF NOT EXISTS orders (
    id          CHAR(8)      NOT NULL COMMENT '订单号',
    customer_id CHAR(8)      NOT NULL COMMENT '客户（FK → customer）',
    amount      DECIMAL(12,2) NOT NULL COMMENT '订单金额（违约金计费依据）',
    urgent      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '加急（权重 +30）',
    priority    INT          NOT NULL DEFAULT 0 COMMENT '订单权重分（§3.8 公式计算落库）',
    order_date  DATE         NOT NULL DEFAULT '2026-08-01' COMMENT '下单日（预测聚合维度，M5a）',
    due_date    DATE         NOT NULL COMMENT '交期（截止日 23:59 完成）',
    status      ENUM('待排队','已审核','打印中','完成') NOT NULL DEFAULT '待排队' COMMENT '状态模型',
    tenant_id   VARCHAR(32)  NOT NULL DEFAULT 'default' COMMENT 'R8',
    PRIMARY KEY (id),
    KEY idx_orders_customer (customer_id),
    KEY idx_orders_status (status),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customer (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='订单（所有权：seed + B 层）';

-- 零件（写方：seed + 模拟器 B 层；读方：solver/tools/forecast）
CREATE TABLE IF NOT EXISTS parts (
    id         CHAR(10)     NOT NULL COMMENT '零件号',
    order_id   CHAR(8)      NOT NULL COMMENT '所属订单（FK → orders）',
    product_id VARCHAR(32)  DEFAULT NULL COMMENT '款型（跨材料拆款 id 不同）',
    name       VARCHAR(64)  DEFAULT NULL COMMENT '零件名',
    quantity   INT          NOT NULL DEFAULT 1 COMMENT '件数',
    material   ENUM('SLA','MJS','SLM') NOT NULL COMMENT '材料 = part 身份',
    length     DECIMAL(6,2) NOT NULL COMMENT '包络盒长 mm（允许旋转）',
    width      DECIMAL(6,2) NOT NULL COMMENT '包络盒宽 mm',
    height     DECIMAL(6,2) NOT NULL COMMENT '包络盒高 mm',
    weight     DECIMAL(6,2) NOT NULL COMMENT '件重 kg（承重约束）',
    tenant_id  VARCHAR(32)  NOT NULL DEFAULT 'default' COMMENT 'R8',
    PRIMARY KEY (id),
    KEY idx_parts_order (order_id),
    KEY idx_parts_material (material),
    CONSTRAINT fk_parts_order FOREIGN KEY (order_id) REFERENCES orders (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='零件（所有权：seed + B 层）';

-- 工艺参数（写方：seed；读方：solver/tools）
CREATE TABLE IF NOT EXISTS material (
    process            ENUM('SLA','MJS','SLM') NOT NULL COMMENT '工艺',
    rate_mm_h          DECIMAL(8,2) NOT NULL COMMENT '打印速率 mm/h（SLA50/MJS25/SLM15）',
    post_process_hours DECIMAL(8,2) NOT NULL COMMENT '后处理延时 h（SLA1/MJS3/SLM12）',
    PRIMARY KEY (process)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='工艺参数（所有权：seed）';

-- 设备（写方：seed + 模拟器 B 层；读方：solver/tools/forecast）
-- current_batch_id 仅索引不设 FK（与 batches.machine_id 避免循环依赖，批次分配由应用层保证）
CREATE TABLE IF NOT EXISTS machines (
    id               CHAR(6)  NOT NULL COMMENT '设备编号',
    name             VARCHAR(64) NOT NULL COMMENT '型号',
    process          ENUM('SLA','MJS','SLM') NOT NULL COMMENT '工艺分群',
    model_type       ENUM('600','450') NOT NULL COMMENT '机型（正方体舱）',
    cabin_size       INT      NOT NULL COMMENT '舱边长 mm（600/450）',
    max_weight       DECIMAL(6,2) NOT NULL COMMENT '舱承重 kg',
    status           ENUM('空闲','打印中','故障','维修中','静置中') NOT NULL DEFAULT '空闲' COMMENT '运行状态（模拟器维护）',
    current_batch_id VARCHAR(20) DEFAULT NULL COMMENT '当前批次（可空）',
    tenant_id        VARCHAR(32) NOT NULL DEFAULT 'default' COMMENT 'R8',
    PRIMARY KEY (id),
    KEY idx_machines_process (process),
    KEY idx_machines_batch (current_batch_id),
    KEY idx_machines_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='设备（所有权：seed + 模拟器 B 层）';

-- 库存（用户确认新增：独立表，写方 seed + B 层 restock；读方 query_inventory）
-- 列名与 inventory.csv 表头一致，保证 load_inventory 的 mysql 路径返回结构不变。
CREATE TABLE IF NOT EXISTS inventory (
    id            CHAR(8)       NOT NULL COMMENT '库存编号（沿用 MAT001...）',
    `名称`        VARCHAR(64)   NOT NULL COMMENT '名称（如 AlSi10Mg铝合金粉末）',
    `材料名`      VARCHAR(32)   NOT NULL COMMENT '材料名（如 铝合金粉末）',
    `库存量`      DECIMAL(12,2) NOT NULL COMMENT '库存量',
    `单位`        VARCHAR(16)   NOT NULL DEFAULT 'kg' COMMENT '单位',
    `安全库存`    DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '安全库存',
    `采购周期天`  INT           NOT NULL DEFAULT 0 COMMENT '采购周期天',
    `单价`        DECIMAL(10,2) NOT NULL DEFAULT 0 COMMENT '单价',
    tenant_id     VARCHAR(32)   NOT NULL DEFAULT 'default' COMMENT 'R8',
    PRIMARY KEY (id),
    KEY idx_inventory_material (`材料名`),
    KEY idx_inventory_tenant (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='库存（所有权：seed + B 层 restock）';

-- 人员（写方：seed + 模拟器 leave 事件 + 前端状态切换；读方：resources/前端）
CREATE TABLE IF NOT EXISTS personnel (
    id     VARCHAR(16) NOT NULL COMMENT '人员编号（P001...）',
    name   VARCHAR(32) NOT NULL COMMENT '姓名',
    role   VARCHAR(32) NOT NULL COMMENT '工种（前道工人/调机员/排版员）',
    status ENUM('上班','请假') NOT NULL DEFAULT '上班' COMMENT '状态（leave 联动 + 前端可改）',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='人员（所有权：seed + 模拟器 B 层 leave + 前端）';

-- ---------------- 求解输出 ----------------

-- 排产表版本（写方：solver run_scheduling；读方：tools/simulator）
CREATE TABLE IF NOT EXISTS schedule_versions (
    id           INT AUTO_INCREMENT COMMENT '版本号（自增）',
    created_at   DATETIME     NOT NULL COMMENT '生成时刻',
    triggered_by VARCHAR(32)  NOT NULL COMMENT '触发源（initial/agent/urgent_order/machine_failure/...）',
    params_json  JSON         DEFAULT NULL COMMENT '求解参数快照',
    result_json  JSON         DEFAULT NULL COMMENT '排产表全文（可回溯对比）',
    status       ENUM('待审核','已审核','已驳回') NOT NULL DEFAULT '待审核' COMMENT '审批状态',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='排产表版本（所有权：solver）';

-- 批次（写方：solver；approval_status → approve_schedule；读方：tools/simulator）
-- machine_id 仅索引不设 FK（与 machines.current_batch_id 避免循环依赖）
CREATE TABLE IF NOT EXISTS batches (
    id                  VARCHAR(20) NOT NULL COMMENT '批次号',
    schedule_version_id INT         NOT NULL COMMENT '所属版本（FK → schedule_versions）',
    order_ids           VARCHAR(512) DEFAULT NULL COMMENT '批内订单 id（JSON 数组）',
    parts_json          JSON        DEFAULT NULL COMMENT '批内零件明细（同材料）',
    process             ENUM('SLA','MJS','SLM') NOT NULL COMMENT '工艺',
    model_type          ENUM('600','450') NOT NULL COMMENT '机型',
    machine_id          CHAR(6)     DEFAULT NULL COMMENT '设备分配（索引，不设 FK）',
    start_time          DATETIME    DEFAULT NULL COMMENT '开工（sim 时间）',
    end_time            DATETIME    DEFAULT NULL COMMENT '完成（sim 时间）',
    post_process_end    DATETIME    DEFAULT NULL COMMENT '静置完成时刻（C6）',
    status              ENUM('前道','待上机','打印中','静置中','完成') NOT NULL DEFAULT '前道' COMMENT '批次状态',
    approval_status     ENUM('待审核','通过','驳回') NOT NULL DEFAULT '待审核' COMMENT '审批状态',
    source              ENUM('整批','拆批') NOT NULL DEFAULT '整批' COMMENT '拆批来源',
    PRIMARY KEY (id),
    KEY idx_batches_version (schedule_version_id),
    KEY idx_batches_machine (machine_id),
    CONSTRAINT fk_batches_version FOREIGN KEY (schedule_version_id) REFERENCES schedule_versions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='批次（所有权：solver；approval_status：approve_schedule）';

-- 前道任务（写方：solver；读方：simulator 推进）
CREATE TABLE IF NOT EXISTS preprocess_tasks (
    id               INT          AUTO_INCREMENT COMMENT '前道任务 id',
    batch_id         VARCHAR(20)  NOT NULL COMMENT '关联批次（FK → batches）',
    part_count       INT          NOT NULL COMMENT '件数',
    man_hours        DECIMAL(8,2) NOT NULL COMMENT '人时 = 件数÷(人×件人效)+方案审核分摊',
    assigned_workers INT          NOT NULL COMMENT '分配人数',
    start_time       DATETIME     DEFAULT NULL COMMENT '开始（sim 时间）',
    end_time         DATETIME     DEFAULT NULL COMMENT '结束（sim 时间，≤ 打印开始 C9）',
    PRIMARY KEY (id),
    KEY idx_preprocess_batch (batch_id),
    CONSTRAINT fk_preprocess_batch FOREIGN KEY (batch_id) REFERENCES batches (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='前道任务（所有权：solver）';

-- ---------------- 配置 ----------------

-- 系统配置（写方：运维/配置 API；读方：所有层启动读一次缓存）
CREATE TABLE IF NOT EXISTS system_config (
    id          INT AUTO_INCREMENT COMMENT '行 id',
    category    VARCHAR(32)  NOT NULL COMMENT '分组（工艺/机型/权重/前道/产能/模拟）',
    `key`       VARCHAR(64)  NOT NULL COMMENT '参数名',
    value       VARCHAR(128) DEFAULT NULL COMMENT '值（VARCHAR，按需转换）',
    unit        VARCHAR(16)  DEFAULT NULL COMMENT '单位',
    description VARCHAR(255) DEFAULT NULL COMMENT '说明 + 默认值来源',
    PRIMARY KEY (id),
    UNIQUE KEY uk_system_config (category, `key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='系统配置（所有权：运维/配置 API）';

-- ---------------- 模拟/审计 ----------------

-- 模拟事件流水（写方：simulator；读方：tools query_sim_events）
CREATE TABLE IF NOT EXISTS sim_events (
    id          INT AUTO_INCREMENT COMMENT '事件 id',
    sim_time    DATETIME     NOT NULL COMMENT '触发时刻（sim）',
    event_type  ENUM('machine_failure','repair_done','new_order','order_change','leave','restock','scrap') NOT NULL COMMENT '事件类型',
    payload_json JSON        DEFAULT NULL COMMENT '事件明细（设备/订单/时长...）',
    status      ENUM('scheduled','fired','handled') NOT NULL DEFAULT 'scheduled' COMMENT '状态',
    handled_by  VARCHAR(32)  DEFAULT NULL COMMENT '已处理 agent',
    PRIMARY KEY (id),
    KEY idx_sim_events_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='模拟事件流水（所有权：simulator）';

-- 坏件记录（写方：simulator B 层 scrap 落库；读方：query_yield/query_kpi；M5a）
CREATE TABLE IF NOT EXISTS bad_parts (
    id                BIGINT AUTO_INCREMENT COMMENT '坏件记录 id',
    batch_id          VARCHAR(32)  NOT NULL COMMENT '批次（根因维度）',
    machine_id        CHAR(6)      NOT NULL COMMENT '设备（根因维度）',
    material          ENUM('SLA','MJS','SLM') NOT NULL COMMENT '材料（根因维度）',
    part_count        INT          NOT NULL DEFAULT 1 COMMENT '坏件数',
    related_event_id  INT          DEFAULT NULL COMMENT '关联 sim_events 事件 id（scrap/MTBF 故障）',
    sim_time          DATETIME     NOT NULL COMMENT 'sim 时间',
    tenant_id         VARCHAR(32)  NOT NULL DEFAULT 'default' COMMENT 'R8',
    PRIMARY KEY (id),
    KEY idx_badparts_machine (machine_id),
    KEY idx_badparts_batch (batch_id),
    KEY idx_badparts_material (material)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='坏件记录（所有权：simulator）';

-- 状态变更日志（写方：simulator；读方：agent 回答"为什么"的依据）
CREATE TABLE IF NOT EXISTS state_change_log (
    id          BIGINT AUTO_INCREMENT COMMENT '日志 id',
    sim_time    DATETIME     NOT NULL COMMENT 'sim 时间',
    real_time   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '现实时间',
    entity_type VARCHAR(32)  NOT NULL COMMENT '对象（machine/order/batch/personnel）',
    entity_id   VARCHAR(32)  NOT NULL COMMENT '对象 id',
    `field`     VARCHAR(64)  NOT NULL COMMENT '变更字段',
    old_value   VARCHAR(255) DEFAULT NULL COMMENT '变更前',
    new_value   VARCHAR(255) DEFAULT NULL COMMENT '变更后',
    source      ENUM('simulator','solver','agent','user') NOT NULL COMMENT '来源',
    PRIMARY KEY (id),
    KEY idx_statelog_entity (entity_type, entity_id),
    KEY idx_statelog_simtime (sim_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='状态变更日志（所有权：simulator）';

-- 审批记录（写方：approve_schedule；读方：审计查询）
CREATE TABLE IF NOT EXISTS approvals (
    id                  INT AUTO_INCREMENT COMMENT '审批 id',
    schedule_version_id INT         NOT NULL COMMENT '关联排产版本（FK → schedule_versions）',
    approver            VARCHAR(64) NOT NULL COMMENT '排版人',
    action              ENUM('通过','驳回') NOT NULL COMMENT '审批动作',
    time                DATETIME    NOT NULL COMMENT '审批时间',
    note                VARCHAR(255) DEFAULT NULL COMMENT '审批意见',
    PRIMARY KEY (id),
    KEY idx_approvals_version (schedule_version_id),
    CONSTRAINT fk_approvals_version FOREIGN KEY (schedule_version_id) REFERENCES schedule_versions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='审批记录（所有权：approve_schedule）';

-- 模拟时钟（写方：simulator A 层；单行表）
CREATE TABLE IF NOT EXISTS sim_clock (
    id               TINYINT     NOT NULL COMMENT '单行约束',
    current_sim_time DATETIME    NOT NULL COMMENT '当前 sim 时间',
    real_ratio       INT         NOT NULL DEFAULT 1 COMMENT '1 现实分钟 = N 模拟小时（默认 1）',
    running          TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '是否运行中',
    PRIMARY KEY (id),
    CONSTRAINT chk_sim_clock_single CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='模拟时钟（所有权：simulator）';

-- ---------------- 看板（M5b，写方：simulator tick + api /ask；读方：dashboard 只读端点） ----------------

-- KPI 快照（写方：simulator tick；读方：dashboard；与 query_kpi 同源）
CREATE TABLE IF NOT EXISTS kpi_snapshot (
    id           BIGINT AUTO_INCREMENT COMMENT '快照 id',
    sim_time     DATETIME     NOT NULL COMMENT 'sim 时间（tick 落点）',
    metrics_json TEXT         NOT NULL COMMENT 'kpi_metrics 全量（与 query_kpi 同源，M5b）',
    tenant_id    VARCHAR(32)  NOT NULL DEFAULT 'default' COMMENT 'R8',
    PRIMARY KEY (id),
    KEY idx_kpisnapshot_time (sim_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='KPI 快照（所有权：simulator tick，M5b）';

-- 成本记录（写方：api /ask；读方：dashboard 成本分模型）
CREATE TABLE IF NOT EXISTS cost_record (
    id           BIGINT AUTO_INCREMENT COMMENT '记录 id',
    trace_id     VARCHAR(32)   NOT NULL COMMENT '关联 trace（M5b）',
    created_at   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '落盘时刻',
    total_cost   DECIMAL(12,6) NOT NULL COMMENT '本次 query 总费用（¥）',
    total_tokens INT           NOT NULL COMMENT '本次 query 总 token',
    total_calls  INT           NOT NULL COMMENT '本次 query LLM 调用数',
    by_provider  JSON          DEFAULT NULL COMMENT '按 provider 分组统计',
    by_model     JSON          DEFAULT NULL COMMENT '按 model 分组统计',
    PRIMARY KEY (id),
    KEY idx_cost_trace (trace_id),
    KEY idx_cost_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='成本记录（所有权：api /ask，M5b）';

-- trace 记录（写方：api /ask；读方：dashboard trace 摘要）
CREATE TABLE IF NOT EXISTS trace_record (
    id         BIGINT AUTO_INCREMENT COMMENT '记录 id',
    trace_id   VARCHAR(32)   NOT NULL COMMENT 'trace id',
    created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '落盘时刻',
    total_ms   DECIMAL(12,1) NOT NULL COMMENT '本轮总耗时 ms',
    span_count INT           NOT NULL COMMENT 'span 数',
    by_kind    JSON          DEFAULT NULL COMMENT '按类型分组计数',
    spans      JSON          DEFAULT NULL COMMENT 'span 明细（落盘限 50 条）',
    PRIMARY KEY (id),
    KEY idx_trace_trace (trace_id),
    KEY idx_trace_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='trace 记录（所有权：api /ask，M5b）';
