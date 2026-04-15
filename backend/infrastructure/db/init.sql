-- ============================================================
-- 浅愈(GentleMend) — PostgreSQL 初始化脚本
-- 首次 docker-compose up 时自动执行
-- ============================================================

-- 启用扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";      -- UUID 生成
CREATE EXTENSION IF NOT EXISTS "pgcrypto";        -- 加密函数
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"; -- 查询统计
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- 模糊搜索 (症状文本)

-- WAL 归档目录 (PITR)
-- 注意: 容器内需要手动创建, 或通过 volume 挂载
-- mkdir -p /var/lib/postgresql/wal_archive

-- ============================================================
-- 1. 核心表
-- ============================================================

-- 1.1 患者表
CREATE TABLE patients (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id     VARCHAR(64) UNIQUE,               -- 外部系统患者ID
    name_encrypted  BYTEA,                            -- AES-256 加密存储
    phone_encrypted BYTEA,                            -- AES-256 加密存储
    metadata        JSONB NOT NULL DEFAULT '{}',      -- 治疗方案、用药等半结构化数据
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- 1.2 评估表 (核心 — 不可变, 只追加新版本)
CREATE TABLE assessments (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id          UUID NOT NULL REFERENCES patients(id),
    version             INTEGER NOT NULL DEFAULT 1,
    -- 输入
    description         TEXT NOT NULL,                 -- 患者原始描述
    symptoms            JSONB NOT NULL DEFAULT '[]',   -- 结构化症状列表
    -- 评估结果
    risk_level          VARCHAR(10) NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    summary             TEXT NOT NULL,                 -- 风险评估摘要
    should_contact_team BOOLEAN NOT NULL DEFAULT FALSE,
    evidences           JSONB NOT NULL DEFAULT '[]',   -- 命中规则/依据列表
    advices             JSONB NOT NULL DEFAULT '[]',   -- 处置建议列表
    -- AI 标记
    ai_enhanced         BOOLEAN NOT NULL DEFAULT FALSE,
    ai_degraded         BOOLEAN NOT NULL DEFAULT FALSE,
    -- 审计元数据 (嵌入式, 每条评估自包含)
    audit_meta          JSONB NOT NULL,
    -- 时间戳
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 同一患者同一评估的版本唯一
    UNIQUE (patient_id, id, version)
);

-- 1.3 协同请求表
CREATE TABLE contact_requests (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    assessment_id   UUID NOT NULL REFERENCES assessments(id),
    patient_id      UUID NOT NULL REFERENCES patients(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'acknowledged', 'resolved')),
    urgency         VARCHAR(10) NOT NULL CHECK (urgency IN ('low', 'medium', 'high')),
    message         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 1.4 规则版本注册表
CREATE TABLE rule_versions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id         VARCHAR(64) NOT NULL,              -- e.g. RULE-NAUSEA-G3-001
    version         VARCHAR(20) NOT NULL,              -- semver: 1.0.0
    rule_body       JSONB NOT NULL,                    -- 完整规则定义
    file_hash       VARCHAR(64) NOT NULL,              -- SHA-256, 与 Git 校验一致性
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'deprecated', 'draft')),
    created_by      VARCHAR(64) NOT NULL,
    reviewed_by     VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (rule_id, version)
);

-- 1.5 Prompt 版本注册表
CREATE TABLE prompt_versions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prompt_key      VARCHAR(64) NOT NULL,              -- e.g. symptom_extraction
    version         VARCHAR(20) NOT NULL,
    file_hash       VARCHAR(64) NOT NULL,
    model_target    VARCHAR(64) NOT NULL,              -- e.g. claude-sonnet-4-20250514
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,    -- 运行时激活标记
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (prompt_key, version)
);

-- ============================================================
-- 2. 分区表 — 事件日志 (按月分区)
-- ============================================================

CREATE TABLE event_logs (
    id              UUID NOT NULL DEFAULT uuid_generate_v4(),
    event_type      VARCHAR(50) NOT NULL,
    session_id      VARCHAR(64) NOT NULL,
    assessment_id   UUID,
    patient_id      UUID,
    payload         JSONB,
    client_ts       TIMESTAMPTZ NOT NULL,              -- 前端事件时间
    server_ts       TIMESTAMPTZ NOT NULL DEFAULT NOW(),-- 服务端接收时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 预创建 12 个月分区 (2025-07 ~ 2026-06)
CREATE TABLE event_logs_2025_07 PARTITION OF event_logs
    FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE event_logs_2025_08 PARTITION OF event_logs
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE event_logs_2025_09 PARTITION OF event_logs
    FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE event_logs_2025_10 PARTITION OF event_logs
    FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE event_logs_2025_11 PARTITION OF event_logs
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE event_logs_2025_12 PARTITION OF event_logs
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE event_logs_2026_01 PARTITION OF event_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE event_logs_2026_02 PARTITION OF event_logs
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE event_logs_2026_03 PARTITION OF event_logs
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE event_logs_2026_04 PARTITION OF event_logs
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE event_logs_2026_05 PARTITION OF event_logs
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE event_logs_2026_06 PARTITION OF event_logs
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- 默认分区 (兜底, 防止插入失败)
CREATE TABLE event_logs_default PARTITION OF event_logs DEFAULT;

-- ============================================================
-- 3. 分区表 — 审计日志 (按月分区, append-only)
-- ============================================================

CREATE TABLE audit_logs (
    id              UUID NOT NULL DEFAULT uuid_generate_v4(),
    -- who
    actor_id        VARCHAR(64) NOT NULL,              -- 操作人 (user_id / system)
    actor_type      VARCHAR(20) NOT NULL               -- user / system / ai
                    CHECK (actor_type IN ('user', 'system', 'ai')),
    -- what
    action          VARCHAR(100) NOT NULL,             -- e.g. assessment_completed
    -- target
    target_type     VARCHAR(50) NOT NULL,              -- e.g. assessment
    target_id       UUID NOT NULL,
    -- change
    old_value       JSONB,                             -- 变更前 (创建时为 null)
    new_value       JSONB,                             -- 变更后
    -- context
    metadata        JSONB NOT NULL DEFAULT '{}',       -- 请求ID、IP、规则版本等
    -- when
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- 预创建 12 个月分区
CREATE TABLE audit_logs_2025_07 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE audit_logs_2025_08 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE audit_logs_2025_09 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE audit_logs_2025_10 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE audit_logs_2025_11 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE audit_logs_2025_12 PARTITION OF audit_logs
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE audit_logs_2026_01 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE audit_logs_2026_02 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE audit_logs_2026_03 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE audit_logs_2026_04 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
CREATE TABLE audit_logs_2026_05 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE audit_logs_2026_06 PARTITION OF audit_logs
    FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

CREATE TABLE audit_logs_default PARTITION OF audit_logs DEFAULT;

-- ============================================================
-- 4. 索引策略
-- ============================================================

-- ---- patients ----
CREATE INDEX idx_patients_external_id ON patients (external_id) WHERE external_id IS NOT NULL;
CREATE INDEX idx_patients_active ON patients (is_active) WHERE is_active = TRUE;
-- GIN: metadata 内的治疗方案查询 (低频, 但需要时不能全表扫描)
CREATE INDEX idx_patients_metadata ON patients USING GIN (metadata jsonb_path_ops);

-- ---- assessments (高频查询核心表) ----
-- 查询模式1: 按 patient_id 查历史评估 (高频) — 覆盖索引含 created_at 支持排序
CREATE INDEX idx_assessments_patient_time ON assessments (patient_id, created_at DESC);
-- 查询模式2: 按 risk_level 筛选 (中频) — 部分索引只索引高风险
CREATE INDEX idx_assessments_risk_level ON assessments (risk_level, created_at DESC);
CREATE INDEX idx_assessments_high_risk ON assessments (created_at DESC)
    WHERE risk_level = 'high';
-- 查询模式3: 按时间范围查询 (中频) — BRIN 索引, 适合时间序列追加写入
CREATE INDEX idx_assessments_created_brin ON assessments USING BRIN (created_at)
    WITH (pages_per_range = 32);
-- 查询模式4: JSONB 字段内条件查询 (低频)
CREATE INDEX idx_assessments_symptoms ON assessments USING GIN (symptoms jsonb_path_ops);
CREATE INDEX idx_assessments_evidences ON assessments USING GIN (evidences jsonb_path_ops);
-- 审计元数据中的规则ID查询
CREATE INDEX idx_assessments_audit_meta ON assessments USING GIN (audit_meta jsonb_path_ops);

-- ---- contact_requests ----
CREATE INDEX idx_contact_requests_assessment ON contact_requests (assessment_id);
CREATE INDEX idx_contact_requests_patient ON contact_requests (patient_id, created_at DESC);
CREATE INDEX idx_contact_requests_pending ON contact_requests (created_at DESC)
    WHERE status = 'pending';

-- ---- event_logs (分区表, 索引自动继承到子分区) ----
CREATE INDEX idx_event_logs_session ON event_logs (session_id, created_at DESC);
CREATE INDEX idx_event_logs_type ON event_logs (event_type, created_at DESC);
CREATE INDEX idx_event_logs_assessment ON event_logs (assessment_id, created_at DESC)
    WHERE assessment_id IS NOT NULL;

-- ---- audit_logs (分区表) ----
CREATE INDEX idx_audit_logs_target ON audit_logs (target_type, target_id, created_at DESC);
CREATE INDEX idx_audit_logs_actor ON audit_logs (actor_id, created_at DESC);
CREATE INDEX idx_audit_logs_action ON audit_logs (action, created_at DESC);

-- ---- rule_versions ----
CREATE INDEX idx_rule_versions_active ON rule_versions (rule_id, created_at DESC)
    WHERE status = 'active';

-- ---- prompt_versions ----
CREATE INDEX idx_prompt_versions_active ON prompt_versions (prompt_key)
    WHERE is_active = TRUE;

-- ============================================================
-- 5. 审计表权限锁定 — REVOKE UPDATE/DELETE
-- ============================================================

-- 创建应用专用角色 (非 superuser)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gentlemend_app') THEN
        CREATE ROLE gentlemend_app LOGIN PASSWORD 'gentlemend_app_2025';
    END IF;
END
$$;

-- 授予基本权限
GRANT CONNECT ON DATABASE gentlemend TO gentlemend_app;
GRANT USAGE ON SCHEMA public TO gentlemend_app;

-- 普通表: 完整 CRUD
GRANT SELECT, INSERT, UPDATE, DELETE ON patients TO gentlemend_app;
GRANT SELECT, INSERT ON assessments TO gentlemend_app;          -- 评估不可变: 无 UPDATE/DELETE
GRANT SELECT, INSERT, UPDATE ON contact_requests TO gentlemend_app;
GRANT SELECT, INSERT, UPDATE ON rule_versions TO gentlemend_app;
GRANT SELECT, INSERT, UPDATE ON prompt_versions TO gentlemend_app;

-- 审计表: 只允许 INSERT + SELECT (append-only)
GRANT SELECT, INSERT ON audit_logs TO gentlemend_app;
REVOKE UPDATE, DELETE ON audit_logs FROM gentlemend_app;

-- 事件日志: 只允许 INSERT + SELECT
GRANT SELECT, INSERT ON event_logs TO gentlemend_app;
REVOKE UPDATE, DELETE ON event_logs FROM gentlemend_app;

-- 分区子表继承权限 (对已创建的子表显式授权)
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT tablename FROM pg_tables
        WHERE tablename LIKE 'audit_logs_%' OR tablename LIKE 'event_logs_%'
    LOOP
        EXECUTE format('GRANT SELECT, INSERT ON %I TO gentlemend_app', tbl);
        EXECUTE format('REVOKE UPDATE, DELETE ON %I FROM gentlemend_app', tbl);
    END LOOP;
END
$$;

-- ============================================================
-- 6. 自动分区管理函数
-- ============================================================

-- 自动创建下个月分区 (由 pg_cron 或应用层定时调用)
CREATE OR REPLACE FUNCTION create_monthly_partition(
    parent_table TEXT,
    target_date DATE DEFAULT (CURRENT_DATE + INTERVAL '1 month')
)
RETURNS TEXT AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    start_date := DATE_TRUNC('month', target_date);
    end_date := start_date + INTERVAL '1 month';
    partition_name := parent_table || '_' || TO_CHAR(start_date, 'YYYY_MM');

    -- 幂等: 分区已存在则跳过
    IF EXISTS (
        SELECT 1 FROM pg_class WHERE relname = partition_name
    ) THEN
        RETURN partition_name || ' already exists';
    END IF;

    EXECUTE format(
        'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
        partition_name, parent_table, start_date, end_date
    );

    RETURN partition_name || ' created';
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 7. 数据生命周期管理函数
-- ============================================================

-- 归档冷数据: 将 >12 个月的事件日志分区 DETACH 后可独立备份/删除
CREATE OR REPLACE FUNCTION archive_old_partitions(
    parent_table TEXT,
    months_to_keep INTEGER DEFAULT 12
)
RETURNS TABLE(partition_name TEXT, action TEXT) AS $$
DECLARE
    cutoff_date DATE;
    rec RECORD;
BEGIN
    cutoff_date := DATE_TRUNC('month', CURRENT_DATE - (months_to_keep || ' months')::INTERVAL);

    FOR rec IN
        SELECT c.relname, pg_get_expr(c.relpartbound, c.oid) AS bound_expr
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        WHERE p.relname = parent_table
          AND c.relname != parent_table || '_default'
        ORDER BY c.relname
    LOOP
        -- 解析分区名中的日期 (格式: parent_YYYY_MM)
        DECLARE
            part_date DATE;
        BEGIN
            part_date := TO_DATE(
                SUBSTRING(rec.relname FROM length(parent_table) + 2),
                'YYYY_MM'
            );
            IF part_date < cutoff_date THEN
                partition_name := rec.relname;
                action := 'detached (ready for archive/drop)';
                EXECUTE format('ALTER TABLE %I DETACH PARTITION %I', parent_table, rec.relname);
                RETURN NEXT;
            END IF;
        EXCEPTION WHEN OTHERS THEN
            -- 跳过无法解析的分区名 (如 _default)
            NULL;
        END;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 8. updated_at 自动更新触发器
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_contact_requests_updated_at
    BEFORE UPDATE ON contact_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- 9. 查询统计视图 (运维用)
-- ============================================================

-- 分区大小监控
CREATE OR REPLACE VIEW v_partition_sizes AS
SELECT
    parent.relname AS parent_table,
    child.relname AS partition_name,
    pg_size_pretty(pg_relation_size(child.oid)) AS size,
    pg_relation_size(child.oid) AS size_bytes
FROM pg_inherits
JOIN pg_class parent ON pg_inherits.inhparent = parent.oid
JOIN pg_class child ON pg_inherits.inhrelid = child.oid
ORDER BY parent.relname, child.relname;
