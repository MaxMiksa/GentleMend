# 更新日志

## v1.0.0 – 首个正式版本 (2026-04-15)

### 功能 1：规则引擎 + AI 增强的双轨架构
- **总结**: 实现了基于 CTCAE 标准的规则引擎作为确定性底线，AI 作为增强层的医疗决策辅助系统。
- **解决痛点**: 乳腺癌患者在治疗过程中遇到副作用时，往往不知道严重程度和是否需要就医，导致延误治疗或过度焦虑。传统系统要么完全依赖规则（缺乏灵活性），要么完全依赖 AI（缺乏可靠性）。
- **功能细节**:
  - 用户输入症状描述（自由文本或结构化表单）
  - 系统通过三级级联提取（关键词匹配 → 规则 NLP → LLM 语义提取）识别症状
  - 规则引擎基于 44 条 CTCAE 规则进行风险分级（低/中/高）
  - AI 增强层提供结构化解读报告（主诉概要 + 需要重视 + 无需过虑 + 个性化建议）
  - 高风险场景自动触发"联系医疗团队"建议
- **技术实现**:
  - 后端：FastAPI + SQLAlchemy ORM + PostgreSQL/SQLite 双模式
  - 规则引擎：`backend/app/rules/engine.py` 实现 CTCAE 决策表 + 加权评分
  - AI 集成：`backend/app/ai/extractor.py` 支持 DeepSeek/OpenAI 兼容接口，含降级策略
  - 感知层：`backend/app/perception/` 实现三级级联症状提取
  - 决策层：`backend/app/decision/` 实现风险评分、冲突消解、置信度计算
  - 执行层：`backend/app/execution/` 实现建议生成、优先级排序

### 功能 2：完整的智能体闭环（感知-决策-执行-学习）
- **总结**: 实现了从用户输入到评估结果，再到反馈收集的完整智能体闭环。
- **解决痛点**: 传统医疗辅助系统缺乏学习能力，无法根据用户反馈持续优化。
- **功能细节**:
  - 感知层：接收非结构化描述，转化为标准化医疗术语
  - 决策层：多维度推理，风险分层，安全守护
  - 执行层：生成行动建议，AI 温和润色避免恐慌
  - 学习层：收集显式反馈（有用/无用）+ 隐式埋点（停留时间、点击行为）
  - 5 个事件埋点：页面访问、评估提交、结果查看、联系团队、反馈提交
- **技术实现**:
  - 事件追踪：`frontend/src/lib/event-tracker.ts` 实现前端埋点 SDK
  - 事件存储：`backend/app/models/models.py` 中的 `EventLog` 模型
  - 反馈收集：`backend/app/api/feedback.py` 实现幂等反馈 API
  - 审计追踪：`backend/app/observability/audit.py` 记录完整决策链

### 功能 3：中英文双语支持
- **总结**: 实现了完整的国际化支持，用户可在中英文之间无缝切换。
- **解决痛点**: 医疗系统往往只支持单一语言，限制了用户群体。
- **功能细节**:
  - 前端界面完全双语（导航栏、表单、结果页、历史页）
  - 症状名称、严重程度、风险等级全部中文化显示
  - AI 解读报告支持中英文输出
  - 语言切换按钮位于导航栏右上角
- **技术实现**:
  - i18n 框架：`frontend/src/lib/i18n/` 使用 React Context + JSON 翻译文件
  - 翻译文件：`zh.json` 和 `en.json` 包含所有界面文本
  - 语言切换：`frontend/src/app/components/Nav.tsx` 实现切换逻辑

### 功能 4：完全可审计的评估结果
- **总结**: 每次评估结果都包含完整的审计追踪信息，确保医疗决策的可追溯性。
- **解决痛点**: 医疗 AI 系统的"黑盒"问题导致医生和患者无法信任其决策。
- **功能细节**:
  - 每条建议都关联到具体的 CTCAE 规则
  - 记录命中规则、生成时间、版本号、置信度
  - 评估结果不可变，只能追加新版本
  - 完整的证据链：症状 → 规则 → 风险等级 → 建议
- **技术实现**:
  - 审计模型：`backend/app/models/models.py` 中的 `AuditLog` 模型
  - 审计构建器：`backend/app/decision/audit_trail.py` 生成审计记录
  - 证据模型：`Evidence` 模型记录每条建议的依据
  - 不可变性：数据库约束 + API 层校验确保评估结果不可修改

### 功能 5：生产级工程化
- **总结**: 实现了完整的 Docker 部署、CI/CD 流水线、监控告警等生产级特性。
- **解决痛点**: MVP 项目往往缺乏工程化支持，难以部署和维护。
- **功能细节**:
  - Docker Compose 一键启动（backend + frontend + postgres + redis）
  - GitHub Actions CI/CD 流水线（测试 + 构建 + 部署）
  - 健康检查端点（`/health`）
  - Prometheus 指标收集（`/metrics`）
  - 结构化日志（JSON 格式）
- **技术实现**:
  - Docker：`backend/Dockerfile` 和 `frontend/Dockerfile` 多阶段构建
  - 编排：`docker-compose.yml` 和 `docker-compose.dev.yml`
  - CI/CD：`.github/workflows/ci.yml` 实现自动化测试和部署
  - 监控：`backend/app/monitoring/` 实现指标收集、健康检查、告警规则
  - Makefile：`Makefile` 提供项目管理命令（setup, dev, test, clean）

### 功能 6：AI 降级策略
- **总结**: 当 AI API 不可用时，系统自动降级到纯规则引擎模式，确保功能完整可用。
- **解决痛点**: 依赖外部 AI API 的系统在 API 故障时完全不可用。
- **功能细节**:
  - 未配置 AI API 时，使用关键词匹配提取症状
  - AI API 调用失败时，自动降级到规则引擎
  - 降级后仍能提供完整的风险评估和建议
  - 用户无感知切换
- **技术实现**:
  - 降级逻辑：`backend/app/ai/extractor.py` 中的 `extract_symptoms_with_fallback()`
  - 关键词匹配：`backend/app/perception/dictionary.py` 维护症状关键词字典
  - 错误处理：捕获 API 异常并记录日志，不影响主流程

### 功能 7：前端三页完整实现
- **总结**: 实现了输入页、结果页、历史页三个核心页面，提供完整的用户体验。
- **解决痛点**: MVP 项目往往只有后端 API，缺乏可用的前端界面。
- **功能细节**:
  - 输入页（`/`）：症状描述、用药信息、既往病史输入
  - 结果页（`/result/[id]`）：风险等级、AI 解读、建议列表、评估依据、反馈按钮
  - 历史页（`/history`）：评估历史列表、分页、筛选
  - 响应式设计，支持移动端
- **技术实现**:
  - Next.js 16 App Router：`frontend/src/app/` 目录结构
  - 共享组件：`frontend/src/app/components/` (Nav, RiskBadge, Footer)
  - API 客户端：`frontend/src/lib/api.ts` 封装后端 API 调用
  - Tailwind CSS v4：样式系统

### 功能 8：规则种子数据自动导入
- **总结**: 系统启动时自动导入 44 条 CTCAE 规则到数据库，无需手动配置。
- **解决痛点**: 规则引擎依赖大量规则数据，手动导入容易出错且效率低。
- **功能细节**:
  - 启动时检查 `rule_sources` 表是否为空
  - 如果为空，自动导入 44 条 CTCAE 规则
  - 规则包含：症状名称、严重程度、风险等级、建议文本、依据说明
  - 支持规则版本化和热更新
- **技术实现**:
  - 种子数据：`backend/app/db/seed.py` 定义规则数据
  - 自动导入：`backend/app/main.py` 启动时调用 `seed_rules()`
  - 规则模型：`backend/app/models/models.py` 中的 `RuleSource` 模型
