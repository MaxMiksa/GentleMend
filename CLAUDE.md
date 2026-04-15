# GentleMend (浅愈) — 乳腺癌副作用智能评估系统

## 项目概述
这是一道高级AI全栈开发师岗位的笔试项目。目标是构建一个最小可运行原型(MVP)，支持乳腺癌用户输入副作用描述，系统返回风险等级、下一步建议、是否建议联系团队、简单依据说明。

## 项目命名
- 中文名：浅愈
- 英文名：GentleMend
- 含义：温和陪伴康复，轻盈助愈身心

## 核心设计原则
1. **医疗安全优先** — 规则引擎作为确定性底线，AI作为增强层，绝不让AI单独做高风险决策
2. **完全可审计** — 每次评估结果必须可追溯：命中规则、生成时间、版本号
3. **数据不可变** — assessment结果一旦生成不可修改，只能追加新版本
4. **可解释性** — 每条建议必须关联到具体规则/依据来源
5. **架构完整，功能精简** — MVP但体现生产级架构思维

## 技术约束
- 这是笔试项目，需要展示架构能力和工程化水平
- 必须是可运行的原型，不是纯设计文档
- 需要体现"感知-决策-执行-学习"智能体闭环

## 文档结构
- `docs/PRD.md` — 产品需求文档
- `docs/SDD.md` — 系统设计文档（架构、技术选型、数据流等）
- `docs/architecture/` — 架构图相关资源
- `docs/architecture/rule-engine-design.md` — 规则引擎详细架构设计（Round 2.5）
- `docs/architecture/data-flow-design.md` — 数据流详细设计（Round 4）

## 工作流程
- 每轮讨论(Round)结束后，将研究结论写入SDD.md对应章节
- Round 2: 横向调研（规则引擎、AI Agent架构模式）
- Round 3: 后端架构设计（模块划分、技术选型、API设计）
- Round 4: 数据模型 + 数据流设计
- Round 5: 智能体闭环设计
- Round 6: 可观测性 + 工程化细节

## Round 6 产出
- `backend/app/monitoring/` — 监控告警模块 (指标收集、健康检查、告警规则、中间件)
- `backend/app/main.py` — FastAPI 入口 (集成健康检查 + 指标端点)
- `docker-compose.yml` — 完整服务编排 (backend + frontend + postgres + redis)
- `docker-compose.dev.yml` — 开发环境覆盖配置
- `backend/Dockerfile` / `frontend/Dockerfile` — 多阶段构建
- `.github/workflows/ci.yml` — CI/CD 流水线
- `Makefile` — 项目管理命令
- `.env.example` — 环境变量模板
- `README.md` — 项目说明

## Round 7 实现阶段（代码编写）

### Phase 1 完成 — 最小闭环跑通
- 后端全部API可运行，SQLite本地开发 + PostgreSQL生产双模式
- 已验证的完整链路：创建患者 → 提交评估 → 规则引擎CTCAE分级 → 建议+依据+审计日志
- 高风险场景正确触发（发热Grade 3 → high → "请立即就医"）
- 自由文本症状提取（"吃不下东西"→anorexia, "呼吸困难"→dyspnea）

### Phase 2 完成 — 补全后端功能
- 事件埋点端到端调通：前端EventTracker → 后端events API → event_logs表，5个事件全部验证
- AI增强层：`app/ai/extractor.py` 用OpenAI兼容接口（DeepSeek），无API key时自动降级到关键词匹配
- 患者反馈API：`POST /assessments/{id}/feedback`，幂等（UNIQUE约束），前端结果页已集成反馈按钮
- RuleSource种子数据：启动时自动导入44条CTCAE规则到rule_sources表，规则持久化完成

### Phase 3 完成 — 前端三页
- Next.js 16 + Tailwind v4，三页全部编译通过并验证
- 输入页(/)、结果页(/result/[id])、历史页(/history)
- 风险等级视觉区分（绿/橙/红）、高风险联系团队按钮、评估依据展示、反馈收集

### Phase 4 完成 — 打磨与增强
- 品牌改名：深知(ShenZhi) → 浅愈(GentleMend)
- i18n国际化：React Context + JSON翻译文件，中英文切换，导航栏语言切换按钮
- AI结构化解读：prompt重写为结构化输出（主诉概要→需要重视→无需过虑→个性化建议）
- 输入页增强：新增"用药与手术"和"既往病史"输入框，数据传给AI增强分析
- 症状严重程度：从滑块改为三级描述按钮（轻/中/重），每条描述30-40字
- 风险评分：从固定0/50/100改为加权真实计算（最高分60%+平均分40%）
- 评估依据中文化：症状名、严重程度、风险等级全部中文显示
- 结果页AI内容结构化渲染：按【主诉概要】【需要重视】【无需过虑】分卡片展示
- Logo替换：自定义品牌logo

### 实际后端目录结构
```
backend/app/
├── ai/               # AI增强层 (OpenAI兼容接口，支持DeepSeek/Claude/OpenAI，含降级策略)
├── api/              # API路由 (patients, assessments, events, contact_requests, feedback)
├── db/               # 数据库配置 + 规则种子数据 (seed.py)
├── models/           # ORM模型 (Patient, Assessment, Advice, Evidence, AuditLog, EventLog, PatientFeedback, RuleSource等)
├── rules/            # 规则引擎 (CTCAE决策表 + 加权评分 + 冲突消解 + 中文化证据)
├── perception/       # 感知层（架构预留）
├── decision/         # 决策层（架构预留）
├── execution/        # 执行层（架构预留）
├── observability/    # 可观测性
├── monitoring/       # 监控告警
└── main.py           # FastAPI入口 (dotenv加载 + 规则种子)
```

### AI配置说明
- 环境变量：`AI_API_KEY`（必需）、`AI_API_BASE_URL`（可选，默认OpenAI）、`AI_MODEL`（可选，默认deepseek-chat）
- 也兼容 `ANTHROPIC_API_KEY`（向后兼容）
- 无key时自动降级到关键词匹配，系统功能完整可用
- AI增强包含两步：(1) 症状提取 (2) 结构化解读报告（主诉+重点+安心+建议）

### SQLite兼容说明
- `db/base.py` 中通过 `DATABASE_URL` 环境变量自动切换：未设置时用SQLite，设置postgres://时用PostgreSQL
- `models/models.py` 中UUID/JSONB/INET等PG特有类型已做兼容适配
- API层不使用 `uuid.UUID()` 对象，统一用字符串传递ID

## 代码规范
- 语言：Python 3.11+ (FastAPI + Pydantic v2) / TypeScript (Next.js)
- 所有代码必须包含审计字段
- 事件埋点覆盖题目要求的5个事件
- 规则引擎必须支持版本化
