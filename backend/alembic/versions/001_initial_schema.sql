-- ============================================================
-- 浅愈(GentleMend) — 初始数据库迁移
-- PostgreSQL 15+
-- 创建所有 9 个核心表 + 枚举类型 + 索引 + 约束 + 权限控制
-- ============================================================

BEGIN;

-- ============================================================
-- 1. 枚举类型
-- ============================================================

CREATE TYPE gender_enum AS ENUM ('male', 'female', 'other');
CREATE TYPE assessment_status_enum AS ENUM ('pending', 'processing', 'completed', 'failed');
CREATE TYPE risk_level_enum AS ENUM ('low', 'medium', 'high');
CREATE TYPE advice_source_type_enum AS ENUM ('rule', 'ai', 'hybrid');
CREATE TYPE rule_status_enum AS ENUM ('active', 'deprecated', 'draft');
CREATE TYPE event_type_enum AS ENUM (
    'assessment_started', 'assessment_submitted',
    'result_viewed', 'contact_team_clicked', 'assessment_closed'
);
CREATE TYPE actor_type_enum AS ENUM ('patient', 'clinician', 'system');
CREATE TYPE contact_status_enum AS ENUM ('pending', 'acknowledged', 'resolved');

-- ============================================================
-- 2. patients 表
-- ============================================================

CREATE TABLE patients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,
    age             INTEGER NOT NULL,
    gender          gender_enum NOT NULL,
    diagnosis       VARCHAR(500),
    treatment_regimen VARCHAR(500),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_patients_age CHECK (age >= 0 AND age <= 150)
);

CREATE INDEX ix_patients_created_at ON patients (created_at);

-- ============================================================
-- 3. assessments 表（核心，不可变 — 无 updated_at）
-- ============================================================

CREATE TABLE assessments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id          UUID NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
    status              assessment_status_enum NOT NULL DEFAULT 'pending',
    risk_level          risk_level_enum,
    free_text_input     TEXT NOT NULL,
    symptoms_structured JSONB,
    ctcae_grades        JSONB,
    overall_risk_score  DOUBLE PRECISION,

    -- AI 相关
    ai_extraction_used  BOOLEAN NOT NULL DEFAULT FALSE,
    ai_enhancement_used BOOLEAN NOT NULL DEFAULT FALSE,
    ai_model_version    VARCHAR(100),
    prompt_version      VARCHAR(50),
    ai_raw_output       JSONB,

    -- 规则引擎
    rule_engine_version VARCHAR(50),

    -- 可读解释
    patient_explanation TEXT,
    grading_rationale   TEXT,

    -- 精确到毫秒的创建时间
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_assessments_risk_score
        CHECK (overall_risk_score IS NULL OR (overall_risk_score >= 0 AND overall_risk_score <= 1))
);

CREATE INDEX ix_assessments_patient_id ON assessments (patient_id);
CREATE INDEX ix_assessments_status ON assessments (status);
CREATE INDEX ix_assessments_risk_level ON assessments (risk_level);
CREATE INDEX ix_assessments_created_at ON assessments (created_at);
CREATE INDEX ix_assessments_patient_created ON assessments (patient_id, created_at);

-- 不可变保护: 禁止 UPDATE（应用层也不应调用，数据库层兜底）
CREATE OR REPLACE FUNCTION prevent_assessment_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'assessments 表不可变，禁止 UPDATE 操作。请创建新版本。';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_assessments_immutable
    BEFORE UPDATE ON assessments
    FOR EACH ROW EXECUTE FUNCTION prevent_assessment_update();

-- ============================================================
-- 4. advices 表
-- ============================================================

CREATE TABLE advices (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id   UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    content         TEXT NOT NULL,
    advice_type     VARCHAR(50) NOT NULL,
    priority        INTEGER NOT NULL DEFAULT 0,
    source_type     advice_source_type_enum NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_advices_priority CHECK (priority >= 0)
);

CREATE INDEX ix_advices_assessment_id ON advices (assessment_id);
CREATE INDEX ix_advices_source_type ON advices (source_type);

-- ============================================================
-- 5. evidences 表
-- ============================================================

CREATE TABLE evidences (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id       UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    rule_id             VARCHAR(100) NOT NULL,
    rule_version        VARCHAR(20) NOT NULL,
    confidence          DOUBLE PRECISION NOT NULL,
    matched_conditions  JSONB,
    evidence_text       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_evidences_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX ix_evidences_assessment_id ON evidences (assessment_id);
CREATE INDEX ix_evidences_rule_id ON evidences (rule_id);

-- ============================================================
-- 6. rule_sources 表（版本化规则定义）
-- ============================================================

CREATE TABLE rule_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id         VARCHAR(100) NOT NULL,
    version         VARCHAR(20) NOT NULL,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    category        VARCHAR(50) NOT NULL,
    ctcae_term      VARCHAR(100),
    ctcae_grade     INTEGER,
    priority        INTEGER NOT NULL DEFAULT 0,
    conditions      JSONB NOT NULL,
    actions         JSONB NOT NULL,
    status          rule_status_enum NOT NULL DEFAULT 'draft',
    effective_from  TIMESTAMPTZ,
    effective_until TIMESTAMPTZ,
    created_by      VARCHAR(100),
    reviewed_by     VARCHAR(100),
    review_date     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_rule_sources_rule_version UNIQUE (rule_id, version),
    CONSTRAINT ck_rule_sources_ctcae_grade
        CHECK (ctcae_grade IS NULL OR (ctcae_grade >= 1 AND ctcae_grade <= 5)),
    CONSTRAINT ck_rule_sources_priority CHECK (priority >= 0)
);

CREATE INDEX ix_rule_sources_rule_id ON rule_sources (rule_id);
CREATE INDEX ix_rule_sources_status ON rule_sources (status);
CREATE INDEX ix_rule_sources_category ON rule_sources (category);
CREATE INDEX ix_rule_sources_ctcae_term ON rule_sources (ctcae_term);

-- ============================================================
-- 7. event_logs 表（可观测性事件）
-- ============================================================

CREATE TABLE event_logs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type        event_type_enum NOT NULL,
    session_id        VARCHAR(64) NOT NULL,
    assessment_id     UUID REFERENCES assessments(id) ON DELETE SET NULL,
    patient_id        UUID REFERENCES patients(id) ON DELETE SET NULL,
    payload           JSONB,
    client_timestamp  TIMESTAMPTZ NOT NULL,
    server_timestamp  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ip_address        INET,
    user_agent        VARCHAR(500)
);

CREATE INDEX ix_event_logs_event_type ON event_logs (event_type);
CREATE INDEX ix_event_logs_session_id ON event_logs (session_id);
CREATE INDEX ix_event_logs_assessment_id ON event_logs (assessment_id);
CREATE INDEX ix_event_logs_server_timestamp ON event_logs (server_timestamp);
CREATE INDEX ix_event_logs_patient_timestamp ON event_logs (patient_id, server_timestamp);

-- ============================================================
-- 8. audit_logs 表（append-only，REVOKE UPDATE/DELETE）
-- ============================================================

CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    event_id    UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    event_type  VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id   VARCHAR(100) NOT NULL,
    actor_id    VARCHAR(100),
    actor_type  actor_type_enum,
    old_value   JSONB,
    new_value   JSONB,
    metadata    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_audit_logs_event_type ON audit_logs (event_type);
CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX ix_audit_logs_actor_id ON audit_logs (actor_id);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

-- append-only 保护: 触发器禁止 UPDATE 和 DELETE
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs 表为 append-only，禁止 UPDATE/DELETE 操作。';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_logs_no_update
    BEFORE UPDATE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_modification();

CREATE TRIGGER trg_audit_logs_no_delete
    BEFORE DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_modification();

-- 权限控制: 对应用角色 REVOKE UPDATE/DELETE
-- 注意: 需要根据实际部署的数据库角色名替换 gentlemend_app
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gentlemend_app') THEN
        EXECUTE 'REVOKE UPDATE, DELETE ON audit_logs FROM gentlemend_app';
        EXECUTE 'GRANT SELECT, INSERT ON audit_logs TO gentlemend_app';
        EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE audit_logs_id_seq TO gentlemend_app';
    END IF;
END $$;

-- ============================================================
-- 9. contact_requests 表
-- ============================================================

CREATE TABLE contact_requests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assessment_id   UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    patient_id      UUID NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
    urgency         risk_level_enum NOT NULL,
    message         TEXT,
    status          contact_status_enum NOT NULL DEFAULT 'pending',
    resolved_at     TIMESTAMPTZ,
    resolved_by     VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_contact_requests_assessment_id ON contact_requests (assessment_id);
CREATE INDEX ix_contact_requests_patient_id ON contact_requests (patient_id);
CREATE INDEX ix_contact_requests_status ON contact_requests (status);

-- ============================================================
-- 10. prompt_registry 表
-- ============================================================

CREATE TABLE prompt_registry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_name     VARCHAR(200) NOT NULL,
    version         VARCHAR(20) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    file_hash       VARCHAR(64) NOT NULL,
    activated_at    TIMESTAMPTZ,
    activated_by    VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_prompt_registry_name_version UNIQUE (prompt_name, version)
);

CREATE INDEX ix_prompt_registry_active ON prompt_registry (prompt_name, is_active);

-- ============================================================
-- 11. 种子数据 — 初始规则
-- ============================================================

INSERT INTO rule_sources (rule_id, version, name, description, category, ctcae_term, ctcae_grade, priority, conditions, actions, status, effective_from, created_by) VALUES
(
    'RULE-NAUSEA-G1-001', '1.0.0',
    '轻度恶心', '化疗后轻度恶心，不影响进食',
    'gastrointestinal', '恶心', 1, 10,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "nausea"}, {"fact": "severity", "operator": "lessThanInclusive", "value": 1}]}'::jsonb,
    '{"risk_level": "low", "advices": ["少量多餐，避免油腻食物", "保持充足水分摄入"], "should_contact_team": false}'::jsonb,
    'active', now(), 'system'
),
(
    'RULE-NAUSEA-G2-001', '1.0.0',
    '中度恶心', '化疗后中度恶心，进食减少但能维持',
    'gastrointestinal', '恶心', 2, 20,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "nausea"}, {"fact": "severity", "operator": "equal", "value": 2}]}'::jsonb,
    '{"risk_level": "low", "advices": ["遵医嘱服用止吐药", "清淡饮食，少量多餐", "记录呕吐次数和时间"], "should_contact_team": false}'::jsonb,
    'active', now(), 'system'
),
(
    'RULE-NAUSEA-G3-001', '1.0.0',
    '重度恶心呕吐', '化疗后严重恶心呕吐，无法进食或脱水',
    'gastrointestinal', '恶心', 3, 80,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "nausea"}, {"fact": "severity", "operator": "greaterThanInclusive", "value": 3}]}'::jsonb,
    '{"risk_level": "high", "advices": ["立即联系医疗团队", "可能需要静脉补液", "暂停口服药物直到医生评估"], "should_contact_team": true}'::jsonb,
    'active', now(), 'system'
),
(
    'RULE-FATIGUE-G1-001', '1.0.0',
    '轻度疲劳', '化��后轻度疲劳，不影响日常活动',
    'constitutional', '疲劳', 1, 10,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "fatigue"}, {"fact": "severity", "operator": "lessThanInclusive", "value": 1}]}'::jsonb,
    '{"risk_level": "low", "advices": ["适当休息，保持规律作息", "轻度运动如散步有助于缓解疲劳"], "should_contact_team": false}'::jsonb,
    'active', now(), 'system'
),
(
    'RULE-FATIGUE-G3-001', '1.0.0',
    '重度疲劳', '严重疲劳，无法进行日常活动',
    'constitutional', '疲劳', 3, 70,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "fatigue"}, {"fact": "severity", "operator": "greaterThanInclusive", "value": 3}]}'::jsonb,
    '{"risk_level": "medium", "advices": ["联系医疗团队评估是否需要调整治疗方案", "检查血常规排除贫血", "合理安排活动和休息时间"], "should_contact_team": true}'::jsonb,
    'active', now(), 'system'
),
(
    'RULE-DERM-G2-001', '1.0.0',
    '中度皮疹', '化疗相关皮疹，覆盖体表面积<30%',
    'dermatological', '皮疹', 2, 30,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "rash"}, {"fact": "severity", "operator": "equal", "value": 2}]}'::jsonb,
    '{"risk_level": "low", "advices": ["使用温和无刺激的护肤品", "避免阳光直射", "遵医嘱使用外用药物"], "should_contact_team": false}'::jsonb,
    'active', now(), 'system'
),
(
    'RULE-FEVER-G3-001', '1.0.0',
    '化疗后发热', '体温>=38.3°C 或持续>=38°C超过1小时（粒缺性发热风险）',
    'constitutional', '发热', 3, 95,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "fever"}, {"fact": "severity", "operator": "greaterThanInclusive", "value": 3}]}'::jsonb,
    '{"risk_level": "high", "advices": ["立即联系医疗团队或前往急诊", "这可能是粒缺性发热，需要紧急处理", "不要自行服用退烧药"], "should_contact_team": true}'::jsonb,
    'active', now(), 'system'
),
(
    'RULE-DIARRHEA-G3-001', '1.0.0',
    '重度腹泻', '每日排便>=7次或需要住院治疗',
    'gastrointestinal', '腹泻', 3, 85,
    '{"all": [{"fact": "symptom_name", "operator": "equal", "value": "diarrhea"}, {"fact": "severity", "operator": "greaterThanInclusive", "value": 3}]}'::jsonb,
    '{"risk_level": "high", "advices": ["立即联系医疗团队", "注意补充水分和电解质", "记录排便次数和性状"], "should_contact_team": true}'::jsonb,
    'active', now(), 'system'
);

-- ============================================================
-- 12. 初始 Prompt 注册
-- ============================================================

INSERT INTO prompt_registry (prompt_name, version, is_active, file_hash, activated_at, activated_by) VALUES
(
    'symptom_extraction', '1.0.0', TRUE,
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    now(), 'system'
),
(
    'risk_assessment_enhancement', '1.0.0', TRUE,
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    now(), 'system'
);

-- ============================================================
-- 13. updated_at 自动更新触发器（仅用于 patients 等可变表）
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

COMMIT;
