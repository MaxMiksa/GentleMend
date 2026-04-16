# 数据流详细设计

> Round 4 — 浅愈(GentleMend) 系统完整数据流设计
> 覆盖：评估全链路、审计、事件、协同请求、历史查询、规则热更新、时序图

---

## 1. 主数据流：评估全链路

这是系统最核心的数据流。从患者在前端输入症状，到最终看到评估结果。

### 1.1 全链路总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          前端 (Next.js)                                 │
│                                                                         │
│  [症状录入页]                                                           │
│   ├─ 用户填写表单 + 自由文本                                            │
│   ├─ 前端校验 (zod schema)                                              │
│   └─ POST /api/v1/assessments ──────────────────────────┐               │
│                                                          │               │
│  [结果页]                                                │               │
│   ├─ 轮询/SSE 等待结果                                   │               │
│   └─ 渲染风险等级 + 建议 + 依据                           │               │
└───────────────────────────────────────────────────────────┼──────────────┘
                                                            │
                        HTTPS / JSON                        │
                        Authorization: Bearer <token>       │
                                                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     FastAPI 网关层                                       │
│                                                                         │
│  ① AuthMiddleware ── 验证 Bearer Token                                  │
│  ② RateLimiter ──── 10次/分钟/用户                                      │
│  ③ RequestLogger ── structlog 记录 request_id                           │
│  ④ CORS ─────────── 校验 Origin                                        │
│  ⑤ REST Adapter ─── Pydantic 反序列化 + 校验                            │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
                    AssessmentRequest (Pydantic DTO)
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  应用服务层 (AssessmentApplicationService)                │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ STEP 1: 构建聚合根                                              │    │
│  │   DTO → Assessment 领域模型 (patient_id, symptoms, free_text)   │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │ STEP 2: LLM 症状提取 [async, 允许降级]                          │    │
│  │   free_text → Claude API → list[SymptomEntry]                   │    │
│  │   超时10s → 降级: 仅使用表单结构化数据                            │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │ STEP 3: 规则引擎分级 [sync逻辑, 必须成功]                       │    │
│  │   list[SymptomEntry] → RuleSnapshot → GradingResult             │    │
│  │   失败 → 返回 500 RULE_ENGINE_ERROR, 不返回任何结果              │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │ STEP 4: LLM 输出增强 [async, 允许降级]                          │    │
│  │   GradingResult → Claude API → 患者可读的自然语言解释             │    │
│  │   超时10s → 降级: 使用规则模板生成基础解释                        │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │ STEP 5: 生成不可变快照 + 持久化 [同一DB事务]                     │    │
│  │   Assessment.create() → 不可变聚合根                             │    │
│  │   ├─ AssessmentRepo.save()    → assessments 表                  │    │
│  │   ├─ Evidence 写入             → evidences 表                    │    │
│  │   ├─ Advice 写入               → advices 表                     │    │
│  │   └─ AuditLogger.log()        → audit_logs 表 (同一事务)        │    │
│  └──────────────────────────────┬──────────────────────────────────┘    │
│                                 │                                       │
│  ┌──────────────────────────────▼──────────────────────────────────┐    │
│  │ STEP 6: 发布领域事件 [事务提交后, 异步]                          │    │
│  │   EventBus.publish(AssessmentCompleted)                          │    │
│  │   if high_risk → EventBus.publish(HighRiskDetected)              │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
                    AssessmentResponse (Pydantic DTO)
                               │
                               ▼
                    HTTP 201 Created + JSON Body
                               │
                               ▼
                    前端渲染评估结果页
```

### 1.2 数据格式转换链（逐层变换）

```
层级              数据格式                    转换动作
─────────────────────────────────────────────────────────────────────

前端 (React)      TypeScript Interface        用户交互 → 表单状态
                  {                            zod.parse() 前端校验
                    description: string,
                    symptoms: SymptomItem[],
                    session_id: string
                  }
                         │
                         │  JSON.stringify()
                         │  fetch POST + Bearer Token
                         ▼
FastAPI Router    Pydantic DTO                 自动反序列化 + 校验
                  AssessmentRequest(           field_validator 执行
                    description: str,          str_strip_whitespace
                    symptoms: list[SymptomItem] | None,
                    session_id: str | None
                  )
                         │
                         │  DTO → Domain Model
                         │  手动映射 (application/service.py)
                         ▼
领域层            Domain Entity (纯Python)     Assessment.__init__()
                  Assessment(                  SymptomEntry 值对象构建
                    id: AssessmentId,          RiskLevel 枚举映射
                    patient_id: PatientId,
                    symptoms: list[SymptomEntry],
                    risk_level: RiskLevel,
                    grading_result: GradingResult,
                    evidences: list[Evidence],
                    advices: list[Advice],
                    audit_meta: AuditMeta,
                    created_at: datetime
                  )
                         │
                         │  Domain → ORM Model
                         │  repository.py 中映射
                         ▼
ORM层             SQLAlchemy Model             mapped_column 定义
                  AssessmentORM(               JSONB 序列化症状详情
                    id: UUID (PK),
                    patient_id: UUID (FK),
                    description: Text,
                    symptoms_json: JSONB,
                    risk_level: VARCHAR(10),
                    summary: Text,
                    should_contact_team: Boolean,
                    ai_enhanced: Boolean,
                    ai_degraded: Boolean,
                    audit_meta_json: JSONB,
                    engine_version: VARCHAR(20),
                    version: Integer,
                    created_at: TIMESTAMP WITH TZ
                  )
                         │
                         │  SQLAlchemy → SQL
                         │  session.add() + flush()
                         ▼
PostgreSQL        SQL INSERT                   单事务写入
                  INSERT INTO assessments (...) VALUES (...);
                  INSERT INTO evidences (...) VALUES (...);   -- 批量
                  INSERT INTO advices (...) VALUES (...);      -- 批量
                  INSERT INTO audit_logs (...) VALUES (...);   -- 同事务
                  COMMIT;
```

### 1.3 数据库写入明细

一次完整评估在同一个数据库事务中写入以下表：

```
┌─────────────────────────────────────────────────────────────────┐
│                    单次评估 DB 事务                               │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ assessments 表 (1行)                                     │    │
│  │ ─────────────────────────────────────────────────────── │    │
│  │ id            │ UUID PK, gen_random_uuid()              │    │
│  │ patient_id    │ UUID FK → patients.id                   │    │
│  │ description   │ TEXT, 患者原始输入                       │    │
│  │ symptoms_json │ JSONB, 结构化症状列表                    │    │
│  │ risk_level    │ VARCHAR(10), low/medium/high             │    │
│  │ summary       │ TEXT, 风险评估摘要                       │    │
│  │ should_contact│ BOOLEAN                                  │    │
│  │ ai_enhanced   │ BOOLEAN                                  │    │
│  │ ai_degraded   │ BOOLEAN                                  │    │
│  │ audit_json    │ JSONB, AuditMeta完整快照                 │    │
│  │ version       │ INTEGER DEFAULT 1                        │    │
│  │ created_at    │ TIMESTAMPTZ DEFAULT now()                │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ evidences 表 (N行, 每条命中规则一行)                      │    │
│  │ ─────────────────────────────────────────────────────── │    │
│  │ id             │ UUID PK                                 │    │
│  │ assessment_id  │ UUID FK → assessments.id                │    │
│  │ rule_id        │ VARCHAR(50), e.g. "RULE-GI-001"        │    │
│  │ rule_version   │ VARCHAR(20), e.g. "1.0.0"              │    │
│  │ rule_name      │ VARCHAR(100)                            │    │
│  │ description    │ TEXT, 规则命中原因                       │    │
│  │ confidence     │ FLOAT, 0.0-1.0                          │    │
│  │ source         │ VARCHAR(20), rule_engine/ai_enhanced    │    │
│  │ created_at     │ TIMESTAMPTZ                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ advices 表 (M行, 每条建议一行)                            │    │
│  │ ─────────────────────────────────────────────────────── │    │
│  │ id             │ UUID PK                                 │    │
│  │ assessment_id  │ UUID FK → assessments.id                │    │
│  │ action         │ TEXT, 建议的具体行动                     │    │
│  │ urgency        │ VARCHAR(10), low/medium/high            │    │
│  │ rationale      │ TEXT, 建议理由                           │    │
│  │ reference      │ TEXT, 临床指南引用                       │    │
│  │ sort_order     │ INTEGER, 显示顺序                       │    │
│  │ created_at     │ TIMESTAMPTZ                             │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ audit_logs 表 (1行, 同事务写入)                           │    │
│  │ ─────────────────────────────────────────────────────── │    │
│  │ id             │ BIGSERIAL PK (自增, 保证顺序)           │    │
│  │ action         │ VARCHAR(50), "assessment_completed"     │    │
│  │ actor_id       │ UUID, 操作者(患者ID)                    │    │
│  │ target_type    │ VARCHAR(50), "assessment"               │    │
│  │ target_id      │ UUID, assessment.id                     │    │
│  │ detail_json    │ JSONB, 完整审计快照                     │    │
│  │ request_id     │ VARCHAR(64), 请求追踪ID                 │    │
│  │ created_at     │ TIMESTAMPTZ DEFAULT now()               │    │
│  │                                                          │    │
│  │ ⚠ REVOKE UPDATE, DELETE ON audit_logs                   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  COMMIT; ← 四张表原子提交                                        │
└─────────────────────────────────────────────────────────────────┘
```

### 1.4 同步/异步标注

```
步骤                    同步/异步        理由
────────────────────────────────────────────────────────────────
① 前端校验              同步(前端)       zod 本地校验, 即时反馈
② Pydantic 反序列化     同步(网关层)     FastAPI 自动执行
③ LLM 症状提取          异步(await)      IO密集, Claude API ~1-3s
④ 规则引擎分级          同步(CPU)        纯内存计算, ~5ms
⑤ LLM 输出增强          异步(await)      IO密集, Claude API ~1-3s
⑥ DB ��久化             异步(await)      asyncpg 异步驱动, ~10ms
⑦ 审计日志写入          同步(同事务)     与⑥在同一DB事务中
⑧ 领域事件发布          异步(fire)       事务提交后异步发布
⑨ 事件处理(通知等)      异步(后台)       不阻塞响应返回
```

### 1.5 错误处理分支（降级策略）

```
                    AssessmentApplicationService.submit()
                                │
                                ▼
                    ┌───────────────────────┐
                    │ STEP 2: LLM 症状提取   │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │ Claude API 调用        │
                    │ timeout=10s            │
                    └───────────┬───────────┘
                       ┌────────┴────────┐
                       │                 │
                  [成功]                [失败/超时]
                       │                 │
                       ▼                 ▼
              合并NLP提取的         仅使用表单结构化数据
              症状到症状列表        标记 ai_degraded=True
                       │                 │
                       └────────┬────────┘
                                │
                    ┌───────────▼───────────┐
                    │ STEP 3: 规则引擎分级   │
                    │ (确定性底线, 必须成功)  │
                    └───────────┬───────────┘
                       ┌────────┴────────┐
                       │                 │
                  [成功]                [异常]
                       │                 │
                       ▼                 ▼
                  继续流程          ┌──────────────────┐
                       │           │ 返回 HTTP 500     │
                       │           │ RULE_ENGINE_ERROR  │
                       │           │ 不返回任何评估结果  │
                       │           │ 记录错误审计日志    │
                       │           └──────────────────┘
                       │
                    ┌───────────▼───────────┐
                    │ STEP 4: LLM 输出增强   │
                    │ timeout=10s            │
                    └───────────┬───────────┘
                       ┌────────┴────────┐
                       │                 │
                  [成功]                [失败/超时]
                       │                 │
                       ▼                 ▼
              使用AI增强的          使用规则模板生成
              自然语言解释          基础解释文案
              ai_enhanced=True     ai_degraded=True
                       │                 │
                       └────────┬────────┘
                                │
                    ┌───────────▼───────────┐
                    │ STEP 5: 持久化         │
                    │ (同一DB事务)           │
                    └───────────┬───────────┘
                       ┌────────┴────────┐
                       │                 │
                  [成功]                [DB异常]
                       │                 │
                       ▼                 ▼
                  HTTP 201          ┌──────────────────┐
                  返回结果          │ 事务回滚           │
                                   │ 返回 HTTP 500     │
                                   │ INTERNAL_ERROR    │
                                   └──────────────────┘

降级状态矩阵:
┌──────────────┬──────────────┬──────────────┬─────────────────────┐
│ LLM提取      │ 规则引擎      │ LLM增强      │ 最终状态             │
├──────────────┼──────────────┼──────────────┼─────────────────────┤
│ OK           │ OK           │ OK           │ 完整结果             │
│              │              │              │ enhanced=T degraded=F│
├──────────────┼──────────────┼──────────────┼─────────────────────┤
│ FAIL         │ OK           │ OK           │ 部分降级             │
│              │              │              │ enhanced=T degraded=T│
├──────────────┼──────────────┼──────────────┼─────────────────────┤
│ OK           │ OK           │ FAIL         │ 部分降级             │
│              │              │              │ enhanced=F degraded=T│
├──────────────┼──────────────┼──────────────┼─────────────────────┤
│ FAIL         │ OK           │ FAIL         │ 纯规则引擎           │
│              │              │              │ enhanced=F degraded=T│
├──────────────┼──────────────┼──────────────┼─────────────────────┤
│ ANY          │ FAIL         │ ANY          │ HTTP 500 错误        │
│              │              │              │ 不返回评估结果        │
└──────────────┴──────────────┴──────────────┴─────────────────────┘
```

---

## 2. 审计数据流

### 2.1 审计写入时机与内容

```
审计事件触发点 (应用层中间件自动写入, 业务代码不感知):

  触发事件                    写入时机                  事务关系
  ─────────────────────────────────────────────────────────────────
  assessment_completed        评估持久化时              与主数据同事务
  assessment_error            规则引擎/DB异常时         独立事务
  contact_request_created     协同请求创建时            与请求同事务
  rule_updated                规则热更新时              独立事务
  rule_reload                 规则缓存重载时            独立事务

每条审计记录的数据结构:
┌─────────────────────────────────────────────────────────────────┐
│ audit_logs 表                                                    │
│                                                                  │
│ {                                                                │
│   id:            BIGSERIAL,          // 自增, 保证顺序           │
│   action:        "assessment_completed",                         │
│   actor_id:      UUID,               // 操作者(患者ID)           │
│   target_type:   "assessment",       // 操作对象类型             │
│   target_id:     UUID,               // assessment.id            │
│   detail_json: {                     // JSONB, 完整审计快照      │
│     matched_rule_ids: ["RULE-GI-001", "RULE-GI-003"],           │
│     rule_versions: {"RULE-GI-001": "1.0.0", ...},              │
│     engine_version: "0.1.0",                                     │
│     risk_level: "medium",                                        │
│     ai_model_version: "claude-sonnet-4-20250514" | null,        │
│     ai_prompt_version: "1.2.0" | null,                          │
│     ai_raw_output: "..." | null,     // AI原始输出(审计用)       │
│     ai_enhanced: true,                                           │
│     ai_degraded: false,                                          │
│     symptom_count: 3,                                            │
│     rule_snapshot_hash: "sha256:abc...",                         │
│     processing_time_ms: 2350                                     │
│   },                                                             │
│   request_id:    "req_abc123",       // HTTP请求追踪ID           │
│   created_at:    TIMESTAMPTZ         // DB时间戳(非应用时间)     │
│ }                                                                │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 审计与主数据流的事务关系

```
┌─────────────────────────────────────────────────────────────────┐
│                    PostgreSQL 事务边界                            │
│                                                                  │
│  BEGIN;                                                          │
│    INSERT INTO assessments (...)  VALUES (...);                  │
│    INSERT INTO evidences (...)    VALUES (...), (...);           │
│    INSERT INTO advices (...)      VALUES (...), (...);           │
│    INSERT INTO audit_logs (...)   VALUES (...);  ← 同一事务     │
│  COMMIT;  ← 原子提交                                            │
│                                                                  │
│  设计决策:                                                        │
│  - 审计日志与主数据在同一事务 (非异步)                             │
│  - 理由: 医疗场景不允许"有评估结果但无审计记录"                    │
│  - 代价: 审计写入增加约2-5ms延迟, 可接受                         │
│  - 如果审计写入失败 → 整个事务回滚 → 评估结果也不保存             │
│  - 宁可评估失败, 也不允许无审计记录的评估结果存在                  │
└───────────────────────────────────────────────────────────────���─┘
```

### 2.3 审计链完整性保证

```
四层保证机制:

1. 数据库层 ── REVOKE UPDATE/DELETE
   ┌─────────────────────────────────────────────────────┐
   │ REVOKE UPDATE, DELETE ON audit_logs FROM app_user;   │
   │ 应用账号只有 INSERT + SELECT 权限                     │
   │ 即使应用层被攻破也无法篡改历史审计记录                 │
   └─────────────────────────────────────────────────────┘

2. 应用层 ── 中间件自动注入
   ┌─────────────────────────────────────────────────────┐
   │ AuditLogger 作为 UnitOfWork 的一部分自动注入          │
   │ 业务代码无法绕过审计写入                              │
   └─────────────────────────────────────────────────────┘

3. 连续性校验 ── BIGSERIAL 自增ID
   ┌─────────────────────────────────────────────────────┐
   │ 定期检查 id 连续性 (无gap = 无删除)                   │
   │ assessment 表每条记录必有对应 audit_log               │
   └─────────────────────────────────────────────────────┘

4. 可重建性 ── 快照hash
   ┌─────────────────────────────────────────────────────┐
   │ 给定 assessment_id, 可完整重建评估上下文:             │
   │                                                       │
   │ assessment_id                                         │
   │   → audit_logs.detail_json.matched_rule_ids           │
   │     → rule_sources (按 rule_id + version 查询)        │
   │       → 当时生效的完整规则定义                         │
   │   → audit_logs.detail_json.ai_raw_output              │
   │     → AI 当时的原始输出                                │
   │   → audit_logs.detail_json.rule_snapshot_hash          │
   │     → 验证规则集是否被篡改                             │
   └─────────────────────────────────────────────────────┘
```

---

## 3. 事件数据流（5个可观测性事件）

### 3.1 事件采集全链路

```
┌─────────────────────────────────────────────────────────────────────┐
│                     前端事件采集层 (Next.js)                          │
│                                                                      │
│  EventTracker (单例, 页面级)                                         │
│  ├─ 自动生成 session_id (页面加载时)                                 │
│  ├─ 事件队列 (内存缓冲, 批量上报)                                    │
│  ├─ 失败重试 (最多3次, 指数退避)                                     │
│  └─ 离开页面时 navigator.sendBeacon() 兜底                           │
│                                                                      │
│  采集点:                                                             │
│  ┌──────────────────────┬────────────────────────────────────────┐  │
│  │ assessment_started   │ 用户首次聚焦输入框 / 选择症状类型       │  │
│  │ assessment_submitted │ 用户点击"提交评估"按钮                  │  │
│  │ result_viewed        │ 结果页渲染完成 (useEffect)              │  │
│  │ contact_team_clicked │ 用户点击"联系医疗团队"按钮              │  │
│  │ assessment_closed    │ 用户离开结果页 (beforeunload/路由切换)  │  │
│  └──────────────────────┴────────────────────────────────────────┘  │
│                                                                      │
│  上报方式: POST /api/v1/events                                       │
│  上报策略: 即时上报 (不等批量, 医疗场景需要实时性)                    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                    EventReport (JSON)
                    {
                      event_type: "assessment_submitted",
                      timestamp: "2025-01-15T10:30:00Z",
                      session_id: "sess_abc123",
                      assessment_id: "550e8400-...",
                      payload: { input_length: 120 }
                    }
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     后端事件接收层                                    │
│                                                                      │
│  POST /api/v1/events                                                 │
│  ├─ Pydantic 校验 EventReport                                       │
│  ├─ 生成 event_id (UUID)                                            │
│  ├─ 立即返回 202 Accepted (不阻塞前端)                               │
│  └─ 异步写入 event_logs 表 (fire-and-forget)                        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ event_logs 表                                                │    │
│  │                                                              │    │
│  │ id             │ UUID PK                                     │    │
│  │ event_type     │ VARCHAR(50)                                 │    │
│  │ session_id     │ VARCHAR(64), 关联同一用户会话               │    │
│  │ assessment_id  │ UUID FK → assessments.id (可空)             │    │
│  │ payload_json   │ JSONB, 事件附加数据                         │    │
│  │ client_ts      │ TIMESTAMPTZ, 前端时间戳                     │    │
│  │ server_ts      │ TIMESTAMPTZ DEFAULT now(), 服务端时间戳     │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 五个事件的触发时机与数据流向

```
用户操作时间线:
═══════════════════════════════════════════════════════════════════

  打开输入页          填写症状          点击提交         查看结果
      │                  │                │                │
      ▼                  │                ▼                ▼
  ┌────────┐             │          ┌──────────┐    ┌──────────┐
  │ EVENT 1│             │          │ EVENT 2  │    │ EVENT 3  │
  │ started│             │          │ submitted│    │ viewed   │
  └────┬───┘             │          └────┬─────┘    └────┬─────┘
       │                 │               │               │
       │                 │               │               │
       ▼                 │               ▼               ▼
  session_id             │          assessment_id   assessment_id
  timestamp              │          input_length    risk_level
                         │                               │
                         │                          ┌────┴────┐
                         │                          │         │
                         │                     [低/中风险]  [高风险]
                         │                          │    点击联系
                         │                          │         │
                         │                          │    ┌────▼────┐
                         │                          │    │ EVENT 4 │
                         │                          │    │ clicked │
                         │                          │    └────┬────┘
                         │                          │         │
                         │                     离开结果页  离开结果页
                         │                          │         │
                         │                     ┌────▼─────────▼────┐
                         ��                     │     EVENT 5       │
                         │                     │     closed        │
                         │                     └────┬──────────────┘
                         │                          │
                         │                     assessment_id
                         │                     duration (停留时长)
                         │
                         ▼
                    所有事件通过 session_id 串联成完整用户旅程

事件与Assessment的关联:
┌──────────────────────┬──────────────┬──────────────────────────┐
│ 事件                  │ assessment_id│ 关联方式                  │
├──────────────────────┼──────────────┼──────────────────────────┤
│ assessment_started   │ null         │ 仅 session_id 关联       │
│ assessment_submitted │ 有值         │ 提交后获得 assessment_id │
│ result_viewed        │ 有值         │ 直接关联                  │
│ contact_team_clicked │ 有值         │ 直接关联                  │
│ assessment_closed    │ 有值         │ 直接关联                  │
└──────────────────────┴──────────────┴──────────────────────────┘

通过 session_id 可将 assessment_started (无assessment_id)
与后续事件 (有assessment_id) 串联, 重建完整用户旅程。
```

---

## 4. 协同请求数据流

### 4.1 触发链路

协同请求有两个触发路径：自动触发（高风险评估）和手动触发（用户点击联系团队）。

```
路径A: 自动触发 (领域事件驱动)
══════════════════════════════════════════════════════════════

  评估完成 (STEP 6)
       │
       ▼
  assessment.is_high_risk() == true
       │
       ▼
  EventBus.publish(HighRiskDetected {
    assessment_id,
    patient_id,
    risk_level: "high",
    matched_rules: [...],
    timestamp
  })
       │
       │  异步, 事务提交后
       ▼
  HighRiskEventHandler.handle()
       │
       ├─→ ContactService.auto_create_request()
       │     │
       │     ▼
       │   ┌─────────────────────────────────────────────┐
       │   │ contact_requests 表 (1行)                    │
       │   │                                              │
       │   │ id             │ UUID PK                     │
       │   │ assessment_id  │ UUID FK → assessments.id    │
       │   │ patient_id     │ UUID FK → patients.id       │
       │   │ status         │ "pending"                   │
       │   │ urgency        │ "high" (继承评估风险等级)    │
       │   │ message        │ null (自动触发无患者附言)    │
       │   │ trigger_type   │ "auto" / "manual"           │
       │   │ created_at     │ TIMESTAMPTZ                 │
       │   └─────────────────────────────────────────────┘
       │
       └─→ NotificationPort.notify_team()
             │
             ├─ 进程内: 写入通知队列
             ├─ MVP实现: 结构化日志输出 (structlog)
             └─ 生产扩展: 邮件/短信/企业微信 webhook


路径B: 手动触发 (用户点击)
══════���═══════════════════════════════════════════════════════

  前端结果页
       │
       │  用户点击"联系医疗团队"
       │
       ├─→ 上报 EVENT 4: contact_team_clicked (异步)
       │
       └─→ POST /api/v1/contact-requests
             │
             ▼
       ContactRequestCreate {
         assessment_id: UUID,
         message: "呕吐越来越严重，很担心",
         urgency: "medium"
       }
             │
             ▼
       ContactService.create()
             │
             ├─ 校验: assessment_id 存在
             ├─ 校验: 无重复 pending 请求 (防重复提交, 否则409)
             │
             ▼
       ┌─ DB事务 ─────────────────────────────────────────┐
       │  INSERT INTO contact_requests (...) VALUES (...); │
       │  INSERT INTO audit_logs (...) VALUES (...);       │
       │  COMMIT;                                          │
       └───────────────────────────────────────────────────┘
             │
             ▼
       EventBus.publish(ContactRequestCreated)
             │
             ▼
       NotificationPort.notify_team()
             │
             ▼
       HTTP 201 + ContactRequestResponse
```

### 4.2 通知团队的异步链路

```
EventBus (进程内, 异步)
       │
       │  publish(HighRiskDetected / ContactRequestCreated)
       ▼
┌─────────────────────────────────────────────────────────────┐
│ NotificationHandler                                          │
│                                                              │
│  async def handle(event):                                    │
│    notification = build_notification(event)                  │
│    # MVP: 结构化日志                                         │
│    logger.warning("team_notification",                       │
│      patient_id=event.patient_id,                            │
│      assessment_id=event.assessment_id,                      │
│      risk_level=event.risk_level,                            │
│      urgency=event.urgency)                                  │
│                                                              │
│    # 生产扩展 (通过 NotificationPort 适配器):                │
│    # await email_adapter.send(notification)                  │
│    # await sms_adapter.send(notification)                    │
│    # await wechat_adapter.send(notification)                 │
│                                                              │
│  失败处理:                                                    │
│    通知失败不影响评估结果 (已持久化)                           │
│    记录失败日志, 后台重试队列                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. 历史查询数据流

### 5.1 列表查询链路

```
前端历史记录页
       │
       │  GET /api/v1/assessments?page=1&page_size=20
       │      &risk_level=high&sort_by=created_at&sort_order=desc
       │      &date_from=2025-01-01&date_to=2025-01-31
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI Router                                                   │
│                                                                  │
│  AssessmentListParams (Pydantic, via Depends):                   │
│  {                                                               │
│    page: 1,           // ge=1                                    │
│    page_size: 20,     // ge=1, le=100                            │
│    risk_level: "high",// 可选筛选                                │
│    sort_by: "created_at",                                        │
│    sort_order: "desc",                                           │
│    date_from: datetime | None,                                   │
│    date_to: datetime | None                                      │
│  }                                                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ AssessmentApplicationService.list()                               │
│                                                                  │
│  → AssessmentRepository.find_by_patient(                         │
│      patient_id,                                                 │
│      filters={risk_level, date_from, date_to},                   │
│      sort_by, sort_order,                                        │
│      offset=(page-1)*page_size,                                  │
│      limit=page_size                                             │
│    )                                                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ SQL 查询 (列表页 — 轻量查询, 不JOIN子表)                         │
│                                                                  │
│  -- 计数查询 (分页元数据)                                        │
│  SELECT COUNT(*) FROM assessments                                │
│  WHERE patient_id = :pid                                         │
│    AND (:risk_level IS NULL OR risk_level = :risk_level)         │
│    AND (:date_from IS NULL OR created_at >= :date_from)          │
│    AND (:date_to IS NULL OR created_at <= :date_to);             │
│                                                                  │
│  -- 数据查询 (仅主表字段, 不JOIN)                                │
│  SELECT id, risk_level, summary, should_contact_team,            │
│         created_at, ai_enhanced,                                 │
│         jsonb_array_length(symptoms_json) AS symptom_count       │
│  FROM assessments                                                │
│  WHERE patient_id = :pid                                         │
│    AND (:risk_level IS NULL OR risk_level = :risk_level)         │
│    AND (:date_from IS NULL OR created_at >= :date_from)          │
│    AND (:date_to IS NULL OR created_at <= :date_to)              │
│  ORDER BY created_at DESC                                        │
│  LIMIT :page_size OFFSET :offset;                                │
│                                                                  │
│  索引: CREATE INDEX idx_assessments_patient_created               │
│        ON assessments(patient_id, created_at DESC);              │
│                                                                  │
│  索引: CREATE INDEX idx_assessments_risk_level                    │
│        ON assessments(patient_id, risk_level, created_at DESC);  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                  AssessmentListResponse {
                    items: [AssessmentListItem, ...],
                    pagination: {
                      total: 42,
                      page: 1,
                      page_size: 20,
                      total_pages: 3
                    }
                  }
```

### 5.2 详情查询链路（数据聚合）

```
前端结果页 / 历史记录展开详情
       │
       │  GET /api/v1/assessments/{id}
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ SQL 查询 (详情页 — 需要JOIN子表)                                 │
│                                                                  │
│  策略: 主查询 + 两次子查询 (避免笛卡尔积)                        │
│                                                                  │
│  -- 查询1: 主表                                                  │
│  SELECT * FROM assessments WHERE id = :id AND patient_id = :pid; │
│                                                                  │
│  -- 查询2: 依据列表                                              │
│  SELECT * FROM evidences                                         │
│  WHERE assessment_id = :id                                       │
│  ORDER BY confidence DESC;                                       │
│                                                                  │
│  -- 查询3: 建议列表                                              │
│  SELECT * FROM advices                                           │
│  WHERE assessment_id = :id                                       │
│  ORDER BY sort_order ASC;                                        │
│                                                                  │
│  为什么不用单次JOIN:                                              │
│  - evidences × advices 会产生笛卡尔积                            │
│  - 3条evidence × 4条advice = 12行, 数据膨胀                     │
│  - 三次简单查询总耗时 < 5ms, 代码更清晰                          │
│                                                                  │
│  SQLAlchemy 实现:                                                │
│  - selectinload(Assessment.evidences)                            │
│  - selectinload(Assessment.advices)                              │
│  - 自动生成上述三次查询                                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
                  ORM → Domain Model → DTO
                           │
                  AssessmentResponse {
                    id, risk_level, summary,
                    should_contact_team,
                    evidences: [...],    // 从 evidences 表
                    advices: [...],      // 从 advices 表
                    audit: {...},        // 从 assessments.audit_json
                    original_description,
                    symptoms,            // 从 assessments.symptoms_json
                    created_at, version,
                    ai_enhanced, ai_degraded,
                    disclaimer
                  }
```

---

## 6. 规则热更新数据流

### 6.1 规则版本切换链路

```
规则更新入口 (管理API / 后台轮询)
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 方式A: 管理API主动触发                                           │
│                                                                  │
│  POST /admin/rules/reload                                        │
│  {                                                               │
│    "rule_ids": ["RULE-GI-001"],  // 增量更新                    │
│    "reason": "CTCAE v5.0 恶心分级条件调整"                       │
│  }                                                               │
│       │                                                          │
│       ▼                                                          │
│  RuleStore.hot_reload(changed_rule_ids=["RULE-GI-001"])          │
│                                                                  │
│ 方式B: 后台轮询自动检测                                          │
│                                                                  │
│  BackgroundTask (每60秒):                                        │
│    SELECT rule_id, version, updated_at                           │
│    FROM rule_sources                                             │
│    WHERE updated_at > :last_check_time;                          │
│       │                                                          │
│       │  有变更                                                  │
│       ▼                                                          │
│  RuleStore.hot_reload(changed_rule_ids=[...])                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ RuleStore.hot_reload() 内部流程                                  │
│                                                                  │
│  with self._lock:  ← RLock, 保证线程安全                        │
│    │                                                             │
│    ├─ 增量模式: 从DB加载指定 rule_ids 的最新版本                 │
│    │  new_rules = await repo.get_rules_by_ids(rule_ids)          │
│    │  for rule in new_rules:                                     │
│    │      self._rules_by_id[rule.rule_id] = rule                 │
│    │                                                             │
│    ├─ 全量模式: 从DB加载所有 active 规则                         │
│    │  all_rules = await repo.get_all_active_rules()              │
│    │  self._rules_by_id = {r.rule_id: r for r in all_rules}     │
│    │                                                             │
│    ├─ 重建索引                                                   │
│    │  self._rebuild_indexes()  // category索引, priority排序     │
│    │                                                             │
│    ├─ 更新元数据                                                 │
│    │  self._version_hash = compute_hash(self._rules_by_id)       │
│    │  self._loaded_at = datetime.now(UTC)                        │
│    │                                                             │
│    └─ 写入审计日志                                               │
│       audit_log: action="rule_reload",                           │
│                  detail={old_hash, new_hash, changed_ids}        │
│                                                                  │
│  注意: 持有锁期间, 正在执行的评估使用的是之前获取的 snapshot     │
│  新评估请求会等待锁释放后获取新 snapshot                         │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Copy-on-Write 快照保证评估一致性

```
这是规则热更新的核心设计: 评估过程中规则不会变化。

时间线:
═══════════════════════════════════════════════════════════════

  T0          T1              T2              T3          T4
  │           │               │               │           │
  ▼           ▼               ▼               ▼           ▼
评估A开始   规则热更新      评估A规则匹配   评估A完成   评估B开始
  │         触发             │               │           │
  │                          │               │           │
  │  snapshot_v1 ◄───────────┘               │           │
  │  (T0时刻获取)                            │           │
  │  hash: "abc..."                          │           │
  │                                          │           │
  │         RuleStore 内存                   │           │
  │         已更新为 v2                       │           │
  │         hash: "def..."                   │           │
  │                                          │           │
  │  评估A全程使用 v1 规则 ──────────────────┘           │
  │  audit_log 记录 rule_snapshot_hash="abc..."          │
  │                                                      │
  │                                          snapshot_v2 ◄┘
  │                                          (T4时刻获取)
  │                                          hash: "def..."

实现机制:
┌─────────────────────────────────────────────────────────────┐
│  class RuleStore:                                            │
│    def snapshot(self) -> RuleSnapshot:                        │
│      with self._lock:                                        │
│        return RuleSnapshot(                                   │
│          rules=dict(self._rules_by_id),  # 浅拷贝dict        │
│          version_hash=self._version_hash,                    │
│          timestamp=self._loaded_at,                          │
│        )                                                     │
│      # 返回后, 即使 hot_reload 更新了 _rules_by_id,          │
│      # snapshot 中的 rules 引用不变                           │
│      # Rule 对象本身是不可变的 (frozen dataclass)             │
│                                                              │
│  class RuleSnapshot:  # 不可变规则集快照                      │
│    rules: dict[str, Rule]     # 不可变                       │
│    version_hash: str          # 用于审计追溯                  │
│    timestamp: datetime        # 快照时间                      │
└─────────────────────────────────────────────────────────────┘

关键保证:
  1. 评估开始时获取 snapshot, 全程使用该 snapshot
  2. 热更新修改的是 RuleStore 内部状态, 不影响已发出的 snapshot
  3. Rule 对象是 frozen dataclass, 不可变
  4. 审计日志记录 version_hash, 可追溯当时使用的规则集
```

---

## 7. 数据流时序图

### 7.1 一次完整评估的组件交互时序

```
参与者:
  Patient    = 患者浏览器
  Frontend   = Next.js 前端
  Gateway    = FastAPI 网关层 (中间件链)
  AppSvc     = AssessmentApplicationService
  LLM_Ext    = SymptomExtractor (Claude API)
  RuleEng    = GradingEngine (规则引擎)
  LLM_Enh    = ExplanationEnhancer (Claude API)
  DB         = PostgreSQL
  EventBus   = 进程内事件总线
  Notifier   = NotificationHandler

Patient     Frontend      Gateway       AppSvc        LLM_Ext      RuleEng      LLM_Enh       DB          EventBus    Notifier
  │            │             │             │             │             │            │            │             │            │
  │ 填写症状    │             │             │             │             │            │            │             │            │
  │──────────>│             │             │             │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │ EVENT: assessment_started (async, fire-and-forget)   │            │            │             │            │
  │            │─ ─ ─ ─ ─ ─>│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─>│             │            │
  │            │             │             │             │             │            │  ~2ms      │             │            │
  │            │             │             │             │             │            │  INSERT    │             │            │
  │            │             │             │             │             │            │  event_logs│             │            │
  │            │             │             │             │             │            │            │             │            │
  │ 点击提交    │             │             │             │             │            │            │             │            │
  │──────────>│             │             │             │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │ POST /api/v1/assessments  │             │             │            │            │             │            │
  │            │────────────>│             │             │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │ ①Auth ②Rate │             │             │            │            │             │            │
  │            │             │ ③Log ④CORS  │             │             │            │            │             │            │
  │            │             │ ⑤Pydantic   │             │             │            │            │             │            │
  │            │             │  ~5ms       │             │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │ submit(req) │             │             │            │            │             │            │
  │            │             │────────────>│             │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ 构建Assessment聚合根      │            │            │             │            │
  │            │             │             │  ~1ms       │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ extract()   │             │            │            │             │            │
  │            │             │             │────────────>│             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │             │ Claude API  │            │            │             │            │
  │            │             │             │             │ 症状提取     │            │            │             │            │
  │            │             │             │             │ ~1000-3000ms│            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ Result<Ok>  │             │            │            │             │            │
  │            │             │             │<────────────│             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ 合并NLP症状到列表          │            │            │             │            │
  │            │             │             │  ~1ms       │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ snapshot()  │             │            │            │             │            │
  │            │             │             │─────────────────────────>│            │            │             │            │
  │            │             │             │             │  ~0.1ms    │            │            │             │            │
  │            │             │             │ RuleSnapshot│             │            │            │             │            │
  │            │             │             │<─────────────────────────│            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ grade(symptoms)           │            │            │             │            │
  │            │             │             ���─────────────────────────>│            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │             │ 条件求值     │            │            │             │            │
  │            │             │             │             │ 冲突解决     │            │            │             │            │
  │            │             │             │             │ ~3-5ms      │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ GradingResult│            │            │            │             │            │
  │            │             │             │<─────────────────────────│            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ enhance()   │             │            │            │             │            │
  │            │             │             │──────────────────────────────────────>│            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │             │             │  Claude API│            │             │            │
  │            │             │             │             │             │  输出增强   │            │             │            │
  │            │             │             │             │             │  ~1000-3000ms           │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ Result<Ok>  │             │            │            │             │            │
  │            │             │             │<──────────────────────────────────────│            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ BEGIN TRANSACTION         │            │            │             │            │
  │            │             │             │─────────────────────────────────────────────────>│             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ INSERT assessments, evidences, advices, audit_logs │             │            │
  │            │             │             │─────────────────────────────────────────────────>│             │            │
  │            │             │             │             │             │            │  ~10ms    │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ COMMIT      │             │            │            │             │            │
  │            │             │             │─────────────────────────────────────────────────>│             │            │
  │            │             │             │             │             │            │  ~2ms     │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ publish(AssessmentCompleted)           │            │             │            │
  │            │             │             │──────────────────────────────────────────────────────────────>│            │
  │            │             │             │             │             │            │            │             │            │
  │            │             │             │ if high_risk: publish(HighRiskDetected)│            │             │            │
  │            │             │             │─��────────────────────────────────────────────────────────────>│            │
  │            │             │             │             │             │            │            │             │ notify()  │
  │            │             │             │             │             │            │            │             │──────────>│
  │            │             │             │             │             │            │            │             │            │
  │            │ HTTP 201    │             │             │             │            │            │             │            │
  │            │<────────────│<────────────│             │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │ 渲染结果页  │             │             │             │             │            │            │             │            │
  │<──────────│             │             │             │             │            │            │             │            │
  │            │             │             │             │             │            │            │             │            │
  │            │ EVENT: result_viewed (async)            │             │            │            │             │            │
  │            │─ ─ ─ ─ ─ ─>│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─>│             │            │
  │            │             │             │             │             │            │            │             │            │
```

### 7.2 各步骤预期延迟

```
步骤                          预期延迟        占比      备注
──────────────────────────────────────────────────────────────────────
① 网关中间件链                 ~5ms           0.2%     Auth+Rate+Log+CORS+Pydantic
② 构建聚合根                   ~1ms           <0.1%    纯内存操作
③ LLM 症状提取                 ~1000-3000ms   40-60%   Claude API, IO密集
④ 获取规则快照                 ~0.1ms         <0.1%    内存读取+浅拷贝
⑤ 规则引擎分级                 ~3-5ms         0.2%     纯CPU, 内存计算
⑥ LLM 输出增强                 ~1000-3000ms   40-60%   Claude API, IO密集
⑦ DB 持久化 (4表)              ~10-15ms       0.5%     asyncpg, 单事务
⑧ 领域事件发布                 ~1ms           <0.1%    进程内, 异步
──────────────────────────────────────────────────────────────────────
总计 (正常)                    ~2000-6000ms            主要瓶颈: 两次LLM调用
总计 (AI降级)                  ~20-30ms                纯规则引擎, 极快
──────────────────────────────────────────────────────────────────────

优化策略:
  - ③和⑥可考虑并行化 (如果LLM增强不依赖提取结果)
    但当前设计中⑥依赖③的结果, 所以是串行
  - 设置AI调用总超时 15s, 超时后降级为纯规则引擎
  - 规则引擎 ~5ms 是确定性底线, 保证最差情况也能快速响应
```

### 7.3 降级场景时序 (AI不可用)

```
Patient     Frontend      Gateway       AppSvc        LLM_Ext      RuleEng       DB
  │            │             │             │             │             │            │
  │ 点击提交    │             │             │             │             │            │
  │──────────>│             │             │             │             │            │
  │            │ POST        │             │             │             │            │
  │            │────────────>│             │             │             │            │
  │            │             │ 中间件 ~5ms │             │             │            │
  │            │             │────────────>│             │             │            │
  │            │             │             │             │             │            │
  │            │             │             │ extract()   │             │            │
  │            │             │             │────────────>│             │            │
  │            │             │             │             │ TIMEOUT     │            │
  │            │             │             │             │ 10s...      │            │
  │            │             │             │ Err(timeout)│             │            │
  │            │             │             │<────────────│             │            │
  │            │             │             │             │             │            │
  │            │             │             │ 降级: 仅用表单数据         │            │
  │            │             │             │ ai_degraded=True          │            │
  │            │             │             │             │             │            │
  │            │             │             │ grade()     │             │            │
  │            │             │             │─────────────────────────>│            │
  │            │             │             │             │  ~5ms      │            │
  │            │             │             │ GradingResult│            │            │
  │            │             │             │<─────────────────────────│            │
  │            │             │             │             │             │            │
  │            │             │             │ 跳过LLM增强, 用规则模板   │            │
  │            │             │             │             │             │            │
  │            │             │             │ DB写入 ~12ms│             │            │
  │            │             │             │────────────────────────────────────>│
  │            │             │             │             │             │            │
  │            │ HTTP 201    │             │             │             │            │
  │            │ ai_degraded │             │             │             │            │
  │            │ =true       │             │             │             │            │
  │            │<────────────│<────────────│             │             │            │
  │            │             │             │             │             │            │
  │ 渲染结果    │             │             │             │             │            │
  │ (标注AI降级)│             │             │             │             │            │
  │<──────────│             │             │             │             │            │

降级场景总延迟: ~10s(超时等待) + ~22ms(规则+DB) ≈ 10s
优化: 可将AI超时缩短到5s, 降级总延迟 ≈ 5s
```

---

## 8. 数据流总览：所有表的读写关系

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        数据库表读写矩阵                                  │
│                                                                         │
│  表名              │ 写入场景              │ 读取场景                    │
│  ─────────────────┼──────────────────────┼───────────────────────────  │
│  assessments      │ 评估完成时(主事务)    │ 详情查询, 列表查询          │
│  evidences        │ 评估完成时(主事务)    │ 详情查询(selectinload)      │
│  advices          │ 评估完成时(主事务)    │ 详情查询(selectinload)      │
│  audit_logs       │ 每次写操作(同事务)    │ 审计追溯查询                │
│  event_logs       │ 前端事件上报(异步)    │ 可观测性分析                │
│  contact_requests │ 协同请求创建(同事��)  │ 请求状态查询                │
│  rule_sources     │ 规则管理(独立事务)    │ 规则加载, 热更新检测        │
│  patients         │ 用户注册(MVP固定)     │ 鉴权, 关联查询              │
│                                                                         │
│  事务边界:                                                               │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 事务1 (评估主事务):                                              │   │
│  │   assessments + evidences + advices + audit_logs                 │   │
│  │   原子提交, 全部成功或全部回滚                                    │   │
│  ├─────────────────────────────────────────────────────────────────┤   │
│  │ 事务2 (协同请求):                                                │   │
│  │   contact_requests + audit_logs                                  │   │
│  ├─────────────────────────────────────────────────────────────────┤   │
│  │ 事务3 (事件上报):                                                │   │
│  │   event_logs (独立, fire-and-forget)                             │   │
│  ├─────────────────────────────────────────────────────────────────┤   │
│  │ 事务4 (规则更新):                                                │   │
│  │   rule_sources + audit_logs                                      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. 数据流安全边界

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        安全边界标注                                      │
│                                                                         │
│  前端 → 网关:                                                           │
│    - TLS 1.2+ 加密传输                                                  │
│    - Bearer Token 认证                                                  │
│    - CORS 限制 Origin                                                   │
│    - Rate Limiting (10次/分钟/用户 for POST /assessments)               │
│                                                                         │
│  网关 → 应用层:                                                         │
│    - Pydantic v2 严格校验 (类型+长度+格式)                              │
│    - description: strip + 2-5000字符                                    │
│    - symptoms: 最多20条                                                 │
│    - request_id 注入 (全链路追踪)                                       │
│                                                                         │
│  应用层 → AI:                                                           │
│    - 超时10s + 重试1次                                                  │
│    - 降级策略 (不阻塞主流程)                                            │
│    - AI输出经 Pydantic schema 校验                                      │
│    - AI原始输出存入审计日志 (不对外暴露)                                │
│                                                                         │
│  应用层 → DB:                                                           │
│    - ORM 参数化查询 (防SQL注入)                                         │
│    - 审计表 REVOKE UPDATE/DELETE                                        │
│    - Assessment 不可变 (只INSERT, 不UPDATE)                             │
│    - 敏感字段 AES-256 加密存储 (生产环境)                               │
│                                                                         │
│  数据不可变性:                                                           │
│    - Assessment 一旦创建不可修改, 只能追加新版本                         │
│    - audit_logs 只能INSERT, 不能UPDATE/DELETE                           │
│    - evidences/advices 跟随 assessment, 同样不可变                      │
└───────────────────────────────────────────────────────────────────���─────┘
```
