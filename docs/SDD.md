# SDD — 浅愈(GentleMend) 系统设计文档

> 本文档随每轮讨论(Round)逐步填充，每轮结束后将研究结论写入对应章节。

---

## 1. 横向调研与技术对比（Round 2）

### 1.1 规则引擎方案对比

#### 方案总览

| 方案 | 规则版本化 | 热更新 | 审计追溯 | 可解释性 | 学习曲线 | 医疗适配度 |
|------|-----------|--------|---------|---------|---------|-----------|
| 硬编码 (if-else) | 差（依赖git） | 不支持 | 需手动埋点 | 差 | 低 | 低 |
| JSON/YAML DSL | 好 | 支持 | 较好 | 较好 | 低 | 中 |
| json-rules-engine (JS/TS) | 好（规则即JSON） | 支持 | 内置events机制 | 好 | 低-中 | 中-高 |
| Drools (Java) | 优（KIE Workbench） | 原生支持 | 完善 | 好 | 高 | 高 |
| 决策表 (Decision Table) | 天然支持 | 支持 | 极好 | 极好 | 低 | 高 |
| FHIR CDS Hooks | N/A（集成标准） | 支持 | 需自建 | 好 | 中-高 | 高（集成层） |

#### 各方案详细分析

**硬编码规则** — 规则少时开发快，但医疗场景致命问题是：乳腺癌副作用涉及多种药物×多种副作用×多个严重程度×患者个体因素，组合爆炸后不可维护。更关键的是临床专家无法直接审核代码逻辑，这在医疗合规上是硬伤。仅适用于规则<20条的原型验证。

**JSON/YAML DSL** — 每条规则可独立标注版本号，支持热更新。局限在于纯JSON难以表达复杂逻辑（嵌套条件、跨规则依赖、时序判断），如"过去3个周期内连续出现2级以上恶心且伴有肝功能异常"这类规则表达困难。

**json-rules-engine** — JS/TS生态中唯一值得认真考虑的选项（nools已停止维护，node-rules太弱）。规则是纯JSON可存数据库，内置almanac机制支持fact动态计算，执行结果直接返回命中events列表，审计追溯开箱即用。不支持Rete算法，但医疗副作用评估场景规则量通常在几百条级别，不是性能瓶颈。

**Drools** — 行业级规则引擎标杆，在医疗行业有大量落地案例（如OpenMRS）。决策表功能可让临床专家通过Excel维护规则。代价是学习曲线陡峭、Java生态绑定。

**决策表** — 在医疗场景中价值极高，因为CTCAE本身就是表格形式的分级标准，决策表与之天然匹配。临床专家可直接参与规则编写和审核，对医疗合规至关重要。局限是条件维度增多时表格庞大，需拆分子表或与规则引擎结合。

**FHIR CDS Hooks** — 解决的是"如何将决策支持嵌入临床工作流"的集成标准问题，不替代规则引擎本身。如果系统需要与医院HIS/EHR对接，是值得考虑的对外接口标准。

#### 选型结论

**推荐：自建轻量规则引擎（Python）+ 决策表混合方案**

考虑到后端选型为Python + FastAPI（见1.4节），Python生态的规则引擎框架整体偏弱（durable-rules低活跃度、business-rules基本停滞、pyke已停止维护），更合理的做法是：

1. **决策表作为规则的主要载体** — CTCAE分级映射天然适合决策表，存储为JSON格式，临床专家可通过管理界面维护
2. **自建轻量规则执行引擎** — 基于Python实现条件匹配和规则执行，代码量可控（几百行），完全掌控审计和版本化逻辑
3. **规则间冲突解决** — 多条规则同时命中时取最高风险等级，优先级排序：安全规则 > 指南明确规定 > 专家共识 > 经验性规则

架构示意：
```
┌─────────────────────────────────────────────┐
│              规则管理层                       │
│  ┌──────────────┐  ┌─────────────────────┐  │
│  │ 决策表管理    │  │ 复杂规则管理         │  │
│  │ (CTCAE分级表) │  │ (条件组合引擎)      │  │
│  └──────┬───────┘  └──────────┬──────────┘  │
│         │                     │              │
│  ┌──────▼─────────────────────▼──────────┐  │
│  │         规则执行引擎                    │  │
│  │  1. 先查决策表（简单匹配）              │  │
│  │  2. 再跑复杂规则（条件组合）            │  │
│  │  3. 合并结果，取最高风险等级            │  │
│  │  4. 记录完整命中规则链                  │  │
│  └──────────────────┬────────────────────┘  │
│                     │                        │
│  ┌──────────────────▼────────────────────┐  │
│  │         审计与解释层                    │  │
│  │  - 记录每次评估命中的规则ID+版本        │  │
│  │  - 生成可读的评估依据说明              │  │
│  │  - 关联临床指南引用                    │  │
│  └───────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

### 1.2 AI Agent 架构模式对比

#### 五种Agent架构模式在医疗场景的适用性

| 模式 | 核心思路 | 医疗适用度 | 优势 | 劣势 |
|------|---------|-----------|------|------|
| ReAct | LLM交替推理+行动 | 中 | 推理过程透明可审计 | 多轮调用延迟高，推理链可能跑偏 |
| Plan-and-Execute | 先制定计划再逐步执行 | 较高 | 与临床路径天然契合，计划可人工审核 | 对中途新信息适应性差 |
| LLM-as-Router | LLM做分诊/路由，不做决策 | 高 | 风险可控，可为不同严重程度设计不同通道 | 路由错误可能导致严重症状走非紧急通道 |
| Tool-augmented LLM | LLM调用外部工具完成任务 | 高 | 工具可独立验证测试，可封装确定性规则 | LLM决定调用时机仍有不确定性 |
| Multi-Agent协作 | 多个专业Agent各司其职 | 中 | 职责分离，安全审查Agent可做兜底 | 系统复杂度高，对聚焦场景可能过度设计 |

**推荐混合架构：**
```
LLM-as-Router（入口层，做分诊）
  → Tool-augmented LLM（核心处理层，工具为规则引擎）
  → Plan-and-Execute（复杂多症状场景的处理策略）
```

#### 规则引擎 + LLM 协作模式

调研了四种协作模式：

| 模式 | 描述 | 安全性 | 适用性 |
|------|------|--------|--------|
| A: LLM理解 + 规则决策（串行） | LLM做NLP结构化，规则引擎做医疗决策 | 最高 | 首选 |
| B: 并行取交集/并集 | 两者同时评估，安全相关取并集 | 高（冗余设计） | 复杂度翻倍 |
| C: 规则为主，LLM为辅 | 规则引擎做核心决策，LLM增强解释 | 高 | 推荐 |
| D: LLM为主，规则兜底 | LLM综合评估，规则引擎做安全校验 | 中 | 不推荐 |

**选型结论：模式A（输入处理）+ 模式C（核心架构）**

```
患者自然语言输入
    │
    ▼
┌──────────────┐
│ LLM: NLP理解  │  ← 模式A：症状提取+结构化
│ 症状提取+结构化│
└──────┬───────┘
       │ 结构化数据
       ▼
┌──────────────┐
│ 规则引擎: 决策 │  ← 模式C核心：确定性决策
│ CTCAE分级     │
│ 风险评分      │
│ 处置路径选择   │
└──────┬───────┘
       │ 决策结果
       ▼
┌──────────────┐
│ LLM: 输出增强  │  ← 模式C辅助：自然语言解释
│ 个性化建议     │
│ 患者教育内容   │
└──────────────┘
```

选择理由：
1. **监管合规** — 核心决策由规则引擎完成，可追溯、可审计、可版本管理，满足FDA/NMPA对算法透明性的要求
2. **安全性** — 规则引擎输出确定性结果，同样输入永远产生同样输出，不存在LLM"幻觉"风险
3. **用户体验** — LLM在前端做理解、后端做解释，系统既能接受自然语言输入，又能输出人性化建议
4. **可维护性** — 医学指南更新时只需更新规则，不需要重新训练或微调LLM
5. **责任边界清晰** — 出问题可明确定位是NLP理解错误、规则错误还是解释生成错误

#### 医疗AI安全约束

**Human-in-the-loop分级介入策略：**

| 风险等级 | AI自主度 | 人工介入方式 |
|---------|---------|------------|
| 低风险 (Grade 1-2) | AI自主处理 | 事后抽检审核 |
| 中风险 (Grade 3) | AI处理+通知医生 | 医生24h内确认 |
| 高风险 (Grade 4) | AI初步评估+暂停 | 医生实时审核后执行 |
| 紧急 (Grade 5) | AI触发告警 | 立即通知+人工接管 |

关键原则：永远不让AI在高风险场景下自主执行；审核超时自动升级；所有AI输出和人工修改都留痕。

**AI置信度与规则确定性结合：**

| 场景 | LLM置信度 | 规则匹配 | 处理策略 |
|------|----------|---------|---------|
| 最佳情况 | 高 | 匹配 | 直接输出，最高可信度 |
| 冲突 | 高 | 不匹配 | 标记冲突，人工审核 |
| 规则主导 | 低 | 匹配 | 采用规则结果，标记LLM不确定 |
| 兜底 | 低 | 不匹配 | 转人工处理 |

**可解释性（XAI）四层设计：**
1. 输入解释 — "系统从您的描述中识别了以下症状: ..."
2. 推理解释 — "根据CTCAE v5.0标准，您的恶心症状被评为3级，因为..."
3. 结果解释 — "建议您立即联系医生，原因是..."
4. 不确定性解释 — "系统对此评估的置信度为75%，建议咨询医生确认"

输出双版本：患者版（简洁通俗）+ 医生版（详细专业）。

**FDA/NMPA监管要求对架构的影响：**
- 规则引擎为主的架构更容易通过审批（算法可解释、可验证）
- LLM部分需明确界定为"辅助功能"而非"决策功能"
- 需要完整的版本管理和变更控制流程
- 数据本地化存储（NMPA要求）
- 需建立上市后监测和不良事件报告机制

### 1.3 同类产品与学术参考

#### 国际同类产品分析

| 产品 | 核心架构 | 决策机制 | 对本系统的参考价值 |
|------|---------|---------|------------------|
| Ada Health | 概率推理引擎（贝叶斯网络）+ 人工维护知识库 | 结构化问答，信息增益最大化 | "概率推理+结构化问答"模式适合副作用分级 |
| Buoy Health | 决策树 → NLP+ML演进 | 对话式症状检查 | 对话式交互降低患者使用门槛 |
| Babylon Health | 知识图谱+NLU+规则引擎混合 | AI分诊+远程问诊闭环 | "AI评估+人工兜底"分层设计是标准模式 |
| K Health | 基于大规模真实临床数据的统计模型 | "类似患者实际发生了什么" | 真实副作用报告数据可补充规则引擎不足 |

**国内平台：** 微医（平台化AI辅助）、好大夫（轻量AI分类）、蚂蚁阿福（推测基于蚂蚁大模型+隐私计算积累）。

**决策机制对比结论：** 采用混合架构——规则引擎处理CTCAE标准分级（确定性强），LLM负责自然语言交互和患者沟通。

#### 乳腺癌副作用专业知识

**按治疗方式分类的常见副作用：**

- **化疗（蒽环类、紫杉类）**：中性粒细胞减少（发热性中性粒细胞减少是急症）、恶心呕吐、周围神经病变、脱发、手足综合征、疲劳、心脏毒性（蒽环类累积剂量相关）
- **放疗**：放射性皮炎、乳房水肿、放射性肺炎、疲劳、远期臂丛神经损伤
- **靶向治疗**：曲妥珠单抗心脏毒性、CDK4/6抑制剂中性粒细胞减少、PARP抑制剂贫血
- **内分泌治疗**：他莫昔芬潮热/血栓风险、芳香化酶抑制剂关节痛/骨质疏松

**CTCAE v5.0 分级标准（系统核心参考）：**

| 等级 | 定义 | 系统映射 |
|------|------|---------|
| 1级（轻度） | 无症状或轻微，仅需观察 | 低风险 — 继续观察与记录 |
| 2级（中度） | 需最低限度干预，影响工具性ADL | 低-中风险 — 观察或联系团队 |
| 3级（重度） | 有重要医学意义，需住院，影响自理性ADL | 中-高风险 — 联系团队 |
| 4级（危及生命） | 需紧急干预 | 高风险 — 立即就医/24h联系团队 |
| 5级（死亡） | 与不良事件相关的死亡 | — |

**PRO-CTCAE（患��自报版本）：** 覆盖78个症状项，每个症状从频率、严重程度、对日常活动影响三个维度评估，使用患者能理解的语言，回忆期7天，已有中文验证版本。其问题措辞可直接作为系统问卷模板。

**需要紧急处理的高风险副作用：**

红色警报（立即就医）：
- 发热≥38.3°C（化疗期间，提示粒缺性发热）
- 严重呼吸困难、胸痛
- 严重出血、意识改变
- 严重过敏反应（面部/喉咙肿胀）

橙色警报（24h内联系医生）：
- 持续呕吐（24h内≥4次）
- 腹泻≥7次/天或伴血便
- 体温37.5-38.3°C
- 新发皮疹伴水疱
- 肢体肿胀/疼痛（提示深静脉血栓）

#### 学术参考与循证依据

**核心循证依据：**
- Basch et al. (2016, 2017) JAMA/JCO — 里程碑研究：电子化PRO监测癌症患者症状可显著改善生存期（中位OS延长5个月）、减少急诊就诊。这是本系统价值的最核心循证依据。
- Denis et al. (2017) JAMA Oncology — 基于web的症状随访系统早期发现复发，改善总生存。
- Absolom et al. (2021) BMJ — eRAPID系统在化疗患者中的RCT研究。

**CDSS架构模式：**
- 知识驱动型：规则+指南+推理引擎，可解释可审计，但有知识获取瓶颈
- 数据驱动型：ML模型从历史数据学习，能发现隐藏模式，但可解释性差
- 混合型（本系统采用）：规则层（CTCAE分级，确定性高）+ ML层（症状模式识别）+ LLM层（交互和内容生成）+ 人工层（最终决策）

**医疗数据合规对架构的影响：**
- 《个人信息保护法》：医疗健康数据属"敏感个人信息"，需单独同意
- 数据本地化：医疗数据原则上不出境
- 加密要求：传输TLS 1.2+，存储AES-256，字段级加密（姓名、身份证号、诊断信息）
- 访问控制：RBAC + ABAC，最小权限原则
- 数据架构对齐FHIR CN Core，为未来与医院系统对接预留接口

### 1.4 技术选型初步结论

基于横向调研，Round 2阶段确定以下技术方向（详细设计在Round 3展开）：

| 层 | 选型 | 核心理由 |
|----|------|---------|
| 后端 | Python + FastAPI | AI生态最强，Pydantic数据校验天然适合医疗数据完整性，自带OpenAPI文档 |
| 数据库 | PostgreSQL | JSONB支持半结构化数据，pg_audit审计能力，MVP到生产无缝过渡 |
| 前端 | React + Next.js | 生态最大，组件库丰富（Shadcn/ui），面试官认知度最高 |
| AI集成 | Claude/OpenAI API 直接调用 | 不用LangChain（过度抽象），Pydantic + Tool Use强制结构化输出 |
| 规则引擎 | 自建Python规则引擎 + 决策表 | Python生态规则引擎框架偏弱，自建可完全掌控审计和版本化 |
| 可观测性 | structlog + OpenTelemetry埋点 | 代码中体现意识，MVP不需要部署Grafana全套 |
| 项目结构 | Monorepo + 模块化单体 | 展示分层能力（六边形架构），不引入微服务复杂度 |
| 部署 | Docker Compose | 一条命令跑起来，评审体验好 |

**技术选型横向对比摘要：**

后端框架：FastAPI > NestJS > Django > Spring Boot > Go（AI生态+开发速度权衡）
数据库：PostgreSQL > MySQL > MongoDB > SQLite（审计能力+JSONB+生产级信号）
前端：React+Next.js ≈ Vue3+Nuxt > Svelte > HTMX（生态+认知度权衡）
AI集成：直接调用API > LangChain > 本地模型（简单性+可控性权衡）

### 1.5 审计存储方案

对比了三种方案：

| 方案 | 实现复杂度 | 审计完整性 | MVP适用性 |
|------|-----------|-----------|----------|
| Event Sourcing | 高（事件存储+投影重建+快照） | 最高 | 差 |
| Append-Only审计表 | 低（触发器或应用层拦截） | 高 | 好 |
| CDC (Debezium/Canal) | 中（需运维中间件） | 中（异步有延迟窗口） | 中 |

**选型：Append-Only审计表**

理由：核心实体不多，Event Sourcing过度设计；CDC引入中间件运维负担重且异步特性在医疗审计场景有隐患。Append-Only审计表实现简单、审计完整性有保障，后期可平滑演进。

关键设计：
- 审计表禁止UPDATE和DELETE（REVOKE权限）
- 应用层中间件写入（非��据库触发器），可测试、可控制粒度、能捕获业务上下文
- 字段：who/what/when/target/old_value/new_value/metadata

### 1.6 Prompt工程化管理

**版本化方案：Git管理 + 数据库版本注册表（混合方案）**

- Prompt内容在Git中走Code Review + 医学审核流程
- 数据库只负责"哪个版本当前在用"的运行时切换
- 两者通过file_hash（SHA-256）校验一致性

Prompt模板结构：
```yaml
metadata:
  version: "1.2.0"
  reviewed_by: "dr-wang"          # 医学审核人
  model_target: "claude-sonnet-4-20250514"

system_prompt: |
  ## 硬性约束
  - 不能做诊断或开处方
  - 信息不足时必须标注"信息不足"而非猜测
  - 禁止输出非CTCAE标准中的分级
  - critical级别必须建议立即联系医疗团队

output_schema:
  # Pydantic模型定义的JSON Schema
```

**结构化输出：Pydantic模型 + Anthropic Tool Use + 应用层校验**

三层防护：幻觉防护（强制"信息不足"输出）、输出格式强制（schema校验失败则重试）、安全边界（免责声明+角色边界声明）。

### 1.7 前端交互模式

| 模式 | 优点 | 缺点 | 适用性 |
|------|------|------|--------|
| 纯对话式 | 交互自然 | 对体弱患者负担大，数据标准化困难 | 低 |
| 结构化表单 | 操作简单，数据天然结构化 | 僵化，无法捕获量表外症状 | 高 |
| 混合式 | 兼顾标准化和灵活性 | 实现复杂度最高 | 最高 |

**选型：结构化表单为主体 + 轻量对话补充**

理由：
1. 化疗患者常伴疲劳、恶心、手足麻木、"化疗脑"，打字是高负担操作，点选完成率显著更高
2. PRO-CTCAE本身是结构化量表，天然适合表单呈现
3. 每个症状结构化采集后提供可选自由输入框（支持语音），补充量表未覆盖信息
4. AI不直接面对患者做对话，而是在后端分析结构化数据+自由文本，避免幻觉风险

交互设计原则：一屏一问、大号字体（≥18px）、大面积可点击区域、条件展开（频率选0则跳过后续）、语音输入支持、进度条、中途保存。

---

## 2. 系统架构设计（Round 3）

### 2.1 整体架构图

采用六边形架构（端口与适配器），领域层零外部依赖。

```
┌─────────────────────────────────────────────────────────────────┐
│                      展示层 (Presentation)                       │
│   Next.js / React SPA                                           │
│   [症状录入页] [评估结果页] [历史记录页]                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS / JSON
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API 网关层 (FastAPI)                           │
│  [Router] [AuthMiddleware] [RateLimit] [CORS] [RequestLogger]   │
│  ┌────────────────────────────────────────────────────────┐     │
│  │  入站适配器 (Inbound/Driving Adapters)                  │     │
│  │  [REST Adapter]  [Event Receiver]  [Future: HL7/FHIR]  │     │
│  └────────────────────────┬───────────────────────────────┘     │
└───────────────────────────┼─────────────────────────────────────┘
                            │
                    ┌───────▼───────┐
                    │  入站端口      │
                    │ (Protocols)   │
                    └───────┬───────┘
                            │
┌───────────────────────────▼──────────────────────────────────────┐
│                   应用服务层 (Application)                        │
│                                                                  │
│  AssessmentService (评估编排器)                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  1. 接收症状输入                                           │  │
│  │  2. 调用 SymptomExtractor → LLM提取自由文本症状            │  │
│  │  3. 调用 GradingEngine → 规则引擎CTCAE分级 (必须成功)      │  │
│  │  4. 调用 ExplanationEnhancer → LLM增强解释 (允许降级)      │  │
│  │  5. 生成不可变Assessment快照                                │  │
│  │  6. 写入审计日志 + 发布领域事件                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│  PatientService │ AuditQueryService │ ContactService             │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                      领域层 (Domain Core)                        │
│                                                                  │
│  聚合根: Assessment(不可变) │ Patient │ ContactRequest           │
│  实体:   SymptomEntry │ SideEffect │ Recommendation             │
│  值对象: CTCAEGrade │ RiskLevel │ RuleRef │ Severity             │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  规则引擎 (领域服务)                                   │       │
│  │  [DecisionTable] → CTCAE分级匹配                      │       │
│  │  [RuleChain]     → 优先级排序 + 短路评估              │       │
│  │  [RuleEngine]    → 统一执行入口                        │       │
│  │  规则定义: YAML/JSON (版本化, 可热更新)                │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                  │
│  领域事件: AssessmentCompleted │ HighRiskDetected                │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  出站端口 (Outbound Ports / Protocols)                │       │
│  │  AssessmentRepo │ AuditLogPort │ AIEnhancementPort   │       │
│  │  NotificationPort │ PatientRepo                       │       │
│  └──────────────────────┬───────────────────────────────┘       │
└─────────────────────────┼───────────────────────────────────────┘
                          │ 依赖倒置：领域定义接口，基础设施实现
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│               基础设施层 (Infrastructure / Outbound Adapters)    │
│                                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐  │
│  │ PostgreSQL   │ │ LLM Adapter  │ │ Audit Adapter          │  │
│  │ Adapter      │ │              │ │                        │  │
│  │ - SQLAlchemy │ │ - Claude API │ │ - append-only表        │  │
│  │ - Alembic    │ │ - 超时/重试  │ │ - REVOKE UPDATE/DELETE │  │
│  │ - 仓储实现   │ │ - 降级策略   │ │ - 应用层写入           │  │
│  └──────┬───────┘ └──────┬───────┘ └────────────┬───────────┘  │
│         │                │                       │               │
│  ┌──────┴───────┐ ┌──────┴───────┐ ┌───────────┴────────────┐  │
│  │ PostgreSQL   │ │ Claude/OpenAI│ │ PostgreSQL audit_log   │  │
│  │ (主数据库)   │ │ API (外部)   │ │ (审计专用)             │  │
│  └──────────────┘ └──────────────┘ └───────────────────────┘  │
│                                                                  │
│  可观测性: [structlog] [OpenTelemetry] [HealthCheck]             │
└─────────────────────────────────────────────────────────────────┘
```

**依赖方向（编译时）：**
```
adapter.inbound ──→ application ──→ domain ←── adapter.outbound
                                      ▲
                                      │
                    所有箭头指向domain，domain不依赖任何外层
```

**核心数据流（一次完整评估）：**
```
Patient → [症状录入] → REST Adapter → AssessmentService(编排器)
    ├─→ SymptomExtractor.extract()     ← LLM提取(允许降级)
    ├─→ GradingEngine.grade()          ← 规则引擎(必须成功)
    ├─→ ExplanationEnhancer.enhance()  ← LLM增强(允许降级)
    ├─→ Assessment.create()            ← 不可变快照
    ├─→ AssessmentRepo.save()          ← 持久化
    ├─→ AuditLogPort.append()          ← 审计(append-only)
    └─→ EventBus.publish()             ← 领域事件(高风险→通知)
```

#### 关键架构决策记录 (ADR)

**ADR-001: 六边形架构 vs 传统三层**

采纳六边形架构。理由：
1. 可测试性 — 规则引擎和分级逻辑可纯单元测试，无需mock数据库。医疗规则正确性验证是生命线
2. 可替换性 — LLM供应商变更时只需新增出站适配器，领域层零改动
3. 领域纯净性 — CTCAE标准等确定性知识不应被框架代码污染，domain层不import任何框架
4. 合规友好 — 审计追溯链在领域层天然清晰

**ADR-002: 模块化单体 vs 微服务**

采纳模块化单体。理由：
1. 事务一致性 — 评估结果+审计日志在同一数据库事务中完成，微服务需Saga/2PC
2. 延迟敏感 — 一次评估：规则引擎(~5ms) + AI调用(~2s) + 持久化(~10ms)，进程内调用避免网络开销
3. 运维简单 — Docker Compose单命令启动，适合笔试演示
4. 演进路径 — 模块边界通过Python包+端口接口定义，未来沿端口边界切割即可拆分

**ADR-003: 规则引擎隔离策略**

规则引擎位于领域层，是确定性底线：
- 规则引擎不依赖AI服务，AI不可用时独立工作
- 规则引擎通过Protocol接口与AI层交互，无直接依赖
- 三级降级：AI全功能 → AI部分降级(仅规则+基础解释) → 纯规则引擎

**ADR-004: 审计链架构级保证**

- 审计表REVOKE UPDATE/DELETE权限，数据库层面不可篡改
- 应用层中间件自动写入，业务代码不感知
- 每条审计记录包含：who/what/when/target/old_value/new_value
- Assessment实体设计为不可变（创建后不可修改，只能追加新版本）

### 2.2 模块划分与职责

#### 项目目录结构

```
GentleMend/
├── docker-compose.yml
├── Makefile                              # 一键启动/测试/迁移
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── src/gentlemend/
│   │   ├── __init__.py
│   │   ├── main.py                       # FastAPI app工厂
│   │   ├── config.py                     # pydantic-settings
│   │   ├── container.py                  # DI容器组装
│   │   │
│   │   ├── shared/                       # 跨模块共享内核
│   │   │   ├── types.py                  # PatientId, AssessmentId (NewType)
│   │   │   ├── base_entity.py            # Entity/AggregateRoot基类
│   │   │   ├── domain_event.py           # DomainEvent基类
│   │   │   ├── result.py                 # Result[T, E] 单子
│   │   │   └── clock.py                  # Clock Protocol(可测试时间)
│   │   │
│   │   ├── assessment/                   # ── 评估(核心模块) ──
│   │   │   ├── domain/
│   │   │   │   ├── models.py             # Assessment, SymptomEntry, RiskLevel
│   │   │   │   ├── ports.py              # AssessmentRepository Protocol
│   │   │   │   ├── events.py             # AssessmentCompleted, HighRiskDetected
│   │   │   │   └── errors.py
│   │   │   ├── application/
│   │   │   │   ├── service.py            # AssessmentApplicationService(编排)
│   │   │   │   ├── dtos.py               # Request/Response DTO
│   │   │   │   ├── commands.py           # SubmitAssessment
│   │   │   │   └── queries.py            # GetAssessment, ListAssessments
│   │   │   └── infrastructure/
│   │   │       ├── repository.py         # SQLAlchemy实现
│   │   │       └── api.py                # FastAPI Router
│   │   │
│   │   ├── rules/                        # ── 规则引擎 ──
│   │   │   ├── domain/
│   │   │   │   ├── models.py             # GradingResult, RuleDecision
│   │   │   │   ├── ports.py              # GradingEngine, RuleRepository Protocol
│   │   │   │   └── decision_tables/
│   │   │   │       └── ctcae_v5_breast.yaml
│   │   │   ├── application/service.py
│   │   │   └── infrastructure/
│   │   │       ├── engine.py             # Python规则引擎实现
│   │   │       └── loader.py             # YAML决策表加载器
│   │   │
│   │   ├── ai/                           # ── LLM集成 ──
│   │   │   ├── domain/
│   │   │   │   ├── models.py             # ExtractionResult, EnhancedExplanation
│   │   │   │   ├── ports.py              # SymptomExtractor, ExplanationEnhancer Protocol
│   │   │   │   └── errors.py
│   │   │   └── infrastructure/
│   │   │       ├── llm_client.py         # LLM HTTP客户端
│   │   │       ├── extractor.py          # SymptomExtractor实现
│   │   │       ├── enhancer.py           # ExplanationEnhancer实现
│   │   │       └── prompts/              # Prompt模板(版本化)
│   │   │
│   │   ├── audit/                        # ── 审计日志 ──
│   │   │   ├── domain/ports.py           # AuditLogger Protocol
│   │   │   └── infrastructure/logger.py  # Append-only持久化
│   │   │
│   │   ├── events/                       # ── 可观测性事件 ──
│   │   │   ├── domain/ports.py           # EventBus Protocol
│   │   │   └── infrastructure/
│   │   │       ├── bus.py                # 进程内EventBus
│   │   │       └── handlers.py           # 事件处理器(高风险→通知)
│   │   │
│   │   ├── patient/                      # ── 患者管理(MVP简化) ──
│   │   │   ├── domain/{models,ports}.py
│   │   │   └── infrastructure/{repository,api}.py
│   │   │
│   │   └── contact/                      # ── 协同请求 ──
│   │       ├── domain/{models,ports}.py
│   │       └── infrastructure/notifier.py
│   │
│   └── tests/
│       ├── unit/                         # 领域层纯单元测试(无IO)
│       ├── integration/                  # 含数据库的集成测试
│       └── fakes/                        # 测试替身(FakeLLM, FakeRepo等)
│
├── frontend/                             # Next.js标准结构
│   ├── package.json
│   ├── src/app/                          # App Router
│   ├── src/components/
│   └── src/lib/api/                      # API client
│
└── docs/
    ├── PRD.md
    ├── SDD.md
    ├── api_schemas.py                    # Pydantic模型定义
    └── architecture/
        └── rule-engine-design.md         # 规则引擎详细设计
```

#### 模块职责矩阵

| 模块 | 职责边界 | 聚合根 | 对外暴露的Protocol |
|------|---------|--------|-------------------|
| assessment | 编排整个评估流程(调ai→rules→contact)，持久化结果 | Assessment | AssessmentRepository |
| rules | CTCAE分级、风险判定、建议生成。不知道LLM存在 | GradingResult | GradingEngine, RuleRepository |
| ai | 封装所有LLM交互：症状提取、自然语言增强 | ExtractionResult | SymptomExtractor, ExplanationEnhancer |
| audit | 不可变审计日志写入 | AuditEntry | AuditLogger |
| events | 进程内事件总线，解耦模块间副作用 | 无 | EventBus |
| patient | 患者基本信息CRUD(MVP简化) | Patient | PatientRepository |
| contact | 高风险时触发协同通知 | ContactRequest | ContactNotifier |

关键原则：`assessment`是编排者，通过Protocol接口调用其他模块，不直接依赖任何infrastructure实现。

#### 核心接口契约（Protocol定义）

```python
# 规则引擎端口
class GradingEngine(Protocol):
    async def grade(self, symptoms: list[SymptomEntry]) -> GradingResult: ...

# AI端口 — 领域层定义，基础设施层实现
class SymptomExtractor(Protocol):
    async def extract(self, text: str) -> Result[list[SymptomEntry], str]: ...

class ExplanationEnhancer(Protocol):
    async def enhance(self, symptoms, rationale, recommendations) -> Result[str, str]: ...

# 审计端口
class AuditLogger(Protocol):
    async def log(self, action: str, detail: str) -> None: ...

# 事件总线端口
class EventBus(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...
    def subscribe(self, event_type: type, handler: Callable) -> None: ...
```

#### 编排流程（AssessmentApplicationService核心逻辑）

```python
async def submit(self, req: AssessmentRequest) -> Result[AssessmentResponse, str]:
    # 1. 构建聚合根
    assessment = Assessment(patient_id=req.patient_id, symptoms=req.symptoms)

    # 2. LLM提取自由文本症状（允许降级）
    if assessment.free_text:
        extraction = await self._extractor.extract(assessment.free_text)
        if isinstance(extraction, Ok):
            assessment.add_nlp_symptoms(extraction.value)

    # 3. 规则引擎分级（必须成功）
    grading = await self._grading.grade(assessment.symptoms)
    assessment.apply_grading(grading)

    # 4. LLM增强输出（允许降级）
    enhancement = await self._enhancer.enhance(...)
    if isinstance(enhancement, Ok):
        assessment.apply_enhancement(enhancement.value)

    # 5. 持久化 + 审计 + 事件发布
    await self._repo.save(assessment)
    await self._audit.log("assessment_completed", ...)
    await self._event_bus.publish(AssessmentCompleted(...))

    if assessment.is_high_risk():
        await self._event_bus.publish(HighRiskDetected(...))

    return Ok(AssessmentResponse.from_domain(assessment))
```

### 2.3 技术选型详细设计

> Round 2已确定技术方向（见1.4节），本节补充实现细节。

#### 后端框架：FastAPI

- 异步支持：原生async/await，适合AI API调用的IO密集场景
- Pydantic v2集成：请求/响应自动校验，医疗数据完整性保证
- OpenAPI自动生成：`/docs`端点即API文档，评审体验好
- 依赖注入：`Depends`机制天然支持六边形架构的端口注入

#### 数据库：PostgreSQL + SQLAlchemy + Alembic

- SQLAlchemy 2.0 async模式，配合asyncpg驱动
- Alembic管理数据库迁移，版本化schema变更
- JSONB字段存储半结构化数据（症状详情、规则命中记录）
- 审计表REVOKE UPDATE/DELETE，数据库层面保证不可篡改

#### AI集成：直接调用API + Pydantic结构化输出

- 使用anthropic SDK直接调用Claude API（不用LangChain）
- Tool Use强制结构化输出，Pydantic模型做应用层校验
- 超时10s + 降级策略：AI不可用时返回纯规则引擎结果
- Prompt版本化：Git管理 + 数据库注册表运行时切换

#### 规则引擎：自建Python引擎

> 详细设计见 `docs/architecture/rule-engine-design.md`

- 决策表(YAML)覆盖20种乳腺癌常见副作用
- 5条红色警报紧急规则（高热/呼吸困难/过敏/出血/DVT）
- 6类药物关联规则（蒽环类/紫杉类/曲妥珠单抗/CDK4-6i/AI/他莫昔芬）
- 语义化版本：MAJOR=风险等级变更 / MINOR=条件调整 / PATCH=文案修改
- Copy-on-write快照保证评估过程中规则一致性

### 2.4 API 设计

> 完整 Pydantic 模型定义见 `docs/api_schemas.py`，可直接用于 FastAPI 路由。

#### 2.4.1 版本化策略

所有接口统一前缀 `/api/v1/`。版本号在 URL 路径中体现，不使用 Header 版本协商。当需要破坏性变更时新增 `/api/v2/`，旧版本保留至少 6 个月。

#### 2.4.2 接口总览

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/v1/assessments` | 提交副作用描述，触发评估 | Bearer Token |
| GET | `/api/v1/assessments/{id}` | 获取单次评估结果 | Bearer Token |
| GET | `/api/v1/assessments` | 获取历史评估列表（分页） | Bearer Token |
| POST | `/api/v1/contact-requests` | 创建协同请求（联系团队） | Bearer Token |
| POST | `/api/v1/events` | 前端事件上报 | Bearer Token |
| GET | `/api/v1/health` | 健康检查 | 无 |
| GET | `/api/v1/health/ready` | 就绪检查（含依赖连通性） | 无 |

#### 2.4.3 接口详细设计

**POST /api/v1/assessments — 提交评估**

请求体（`AssessmentRequest`）：
```json
{
  "description": "最近三天一直恶心，吃不下东西，今天吐了两次",
  "symptoms": [
    {
      "category": "gastrointestinal",
      "name": "恶心",
      "severity": 3,
      "frequency": "每天3-4次",
      "duration": "持续3天"
    }
  ],
  "session_id": "sess_abc123"
}
```

响应 `201 Created`（`AssessmentResponse`）：
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "risk_level": "medium",
  "summary": "您报告的恶心呕吐症状评估为中等风险，建议联系医疗团队。",
  "should_contact_team": true,
  "evidences": [
    {
      "rule_id": "RULE-GI-001",
      "rule_version": "1.0.0",
      "rule_name": "化疗期间持续呕吐",
      "description": "持续呕吐超过24小时，符合CTCAE 3级标准",
      "confidence": 0.95,
      "source": "rule_engine"
    }
  ],
  "advices": [
    {
      "action": "建议24小时内联系您的医疗团队，报告呕吐情况",
      "urgency": "medium",
      "rationale": "CTCAE v5.0: 恶心3级需要医疗干预",
      "reference": "CTCAE v5.0 恶心分级标准"
    }
  ],
  "disclaimer": "本评估结果仅供参考，不构成医疗诊断。如有紧急情况请立即就医。",
  "original_description": "最近三天一直恶心，吃不下东西，今天吐了两次",
  "audit": {
    "matched_rule_ids": ["RULE-GI-001"],
    "rule_versions": {"RULE-GI-001": "1.0.0"},
    "engine_version": "0.1.0",
    "generated_at": "2025-01-15T10:30:00.123Z",
    "ai_model_version": "claude-sonnet-4-20250514",
    "ai_prompt_version": "1.2.0"
  },
  "created_at": "2025-01-15T10:30:00.123Z",
  "version": 1,
  "ai_enhanced": true,
  "ai_degraded": false
}
```

错误响应：
- `400` — 输入校验失败（`VALIDATION_ERROR`）
- `401` — 未认证（`UNAUTHORIZED`）
- `429` — 请求限流（`RATE_LIMITED`）
- `500` — 规则引擎异常（`RULE_ENGINE_ERROR`）
- `503` — AI 服务不可用时返回降级结果（`AI_DEGRADED`，HTTP 仍为 `201`，`ai_degraded=true`）

**GET /api/v1/assessments/{id} — 获取单次评估**

路径参数：`id`（UUID）

响应 `200 OK`：同 `AssessmentResponse`。

错误响应：
- `404` — 评估不存在（`NOT_FOUND`）

**GET /api/v1/assessments — 历史评估列表**

查询参数（`AssessmentListParams`）：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码（≥1） |
| `page_size` | int | 20 | 每页条数（1-100） |
| `risk_level` | string | — | 按风险等级筛选：low/medium/high |
| `sort_by` | string | created_at | 排序字段：created_at / risk_level |
| `sort_order` | string | desc | 排序方向：asc / desc |
| `date_from` | datetime | — | 起始时间 |
| `date_to` | datetime | — | 截止时间 |

响应 `200 OK`（`AssessmentListResponse`）：
```json
{
  "items": [
    {
      "id": "550e8400-...",
      "risk_level": "medium",
      "summary": "恶心呕吐，中等风险",
      "should_contact_team": true,
      "created_at": "2025-01-15T10:30:00Z",
      "symptom_count": 2,
      "ai_enhanced": true
    }
  ],
  "pagination": {
    "total": 42,
    "page": 1,
    "page_size": 20,
    "total_pages": 3
  }
}
```

**POST /api/v1/contact-requests — 创建协同请求**

请求体（`ContactRequestCreate`）：
```json
{
  "assessment_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "呕吐越来越严重，很担心",
  "urgency": "medium"
}
```

响应 `201 Created`（`ContactRequestResponse`）：
```json
{
  "id": "660e8400-...",
  "assessment_id": "550e8400-...",
  "status": "pending",
  "urgency": "medium",
  "message": "呕吐越来越严重，很担心",
  "created_at": "2025-01-15T10:35:00Z"
}
```

错误响应：
- `404` — 关联的评估不存在
- `409` — 该评估已有待处理的协同请求（防重复提交）

**POST /api/v1/events — 前端事件上报**

请求体（`EventReport`）：
```json
{
  "event_type": "assessment_submitted",
  "timestamp": "2025-01-15T10:30:00Z",
  "session_id": "sess_abc123",
  "assessment_id": "550e8400-...",
  "payload": {"input_length": 120}
}
```

响应 `202 Accepted`（`EventReportResponse`）：
```json
{
  "accepted": true,
  "event_id": "770e8400-..."
}
```

事件上报采用 fire-and-forget 模式，不阻塞前端。后端异步写入 EventLog 表。

**GET /api/v1/health — 健康检查**

响应 `200 OK`（`HealthResponse`）：
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 3600.5
}
```

**GET /api/v1/health/ready — 就绪检查**

响应 `200 OK`（`ReadinessResponse`）：
```json
{
  "status": "healthy",
  "components": [
    {"name": "database", "status": "healthy", "latency_ms": 2.3},
    {"name": "ai_service", "status": "healthy", "latency_ms": 150.0},
    {"name": "rule_engine", "status": "healthy", "latency_ms": 0.5}
  ]
}
```

任一组件 unhealthy 时整体状态为 `degraded` 或 `unhealthy`，HTTP 状态码返回 `503`。

#### 2.4.4 统一错误响应格式

所有错误统一使用 `ErrorResponse` 模型：

```json
{
  "error": "VALIDATION_ERROR",
  "message": "输入校验失败",
  "details": [
    {"field": "description", "message": "描述内容不能为空白"}
  ],
  "request_id": "req_abc123",
  "timestamp": "2025-01-15T10:30:00Z"
}
```

业务错误码定义：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `VALIDATION_ERROR` | 400 | 请求参数校验失败 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `UNAUTHORIZED` | 401 | 未认证或 Token 无效 |
| `RATE_LIMITED` | 429 | 请求频率超限 |
| `INTERNAL_ERROR` | 500 | 未预期的服务端错误 |
| `ASSESSMENT_TIMEOUT` | 504 | 评估处理超时（规则引擎+AI 总耗时超限） |
| `RULE_ENGINE_ERROR` | 500 | 规则引擎执行异常 |
| `AI_SERVICE_UNAVAILABLE` | 503 | AI 服务完全不可用 |
| `AI_DEGRADED` | — | AI 降级标记（非 HTTP 错误，嵌入响应体） |
| `INPUT_TOO_SHORT` | 400 | 输入描述过短，无法评估 |
| `INPUT_POTENTIALLY_HARMFUL` | 400 | 输入包含潜在有害内容 |

**医疗场景特殊错误处理：**

1. **AI 降级策略** — 当 AI 服务不可用或超时时，系统仍返回 `201` 和规则引擎结果，`ai_degraded=true`。规则引擎是确定性底线，不依赖 AI 服务。
2. **规则引擎异常** — 规则引擎是核心安全组件，如果规则引擎本身异常，返回 `500 RULE_ENGINE_ERROR`，不返回任何评估结果（宁可报错也不给出不可靠结果）。
3. **超时分级** — AI 调用超时（默认 10s）→ 降级为纯规则引擎；规则引擎超时（默认 5s）→ 返回错误。

#### 2.4.5 API 安全设计

**认证方案（MVP）：**
- Bearer Token 认证，Token 通过 `Authorization: Bearer <token>` 传递
- MVP 阶段使用固定 Token（配置文件管理），不实现完整的 OAuth2 流程
- 健康检查接口（`/api/v1/health`、`/api/v1/health/ready`）无需认证

**请求限流：**
- 评估接口（POST /assessments）：10 次/分钟/用户（防止滥用 AI 资源）
- 列表查询接口：60 次/分钟/用户
- 事件上报接口：120 次/分钟/用户（前端事件频率较高）
- 限流响应返回 `429` + `Retry-After` Header

**输入校验（防注入）：**
- Pydantic v2 严格模式校验所有输入字段类型和长度
- `description` 字段做 strip + 长度限制（2-5000 字符）
- 症状列表最多 20 条，防止超大 payload
- SQL 注入由 ORM 参数化查询防护
- XSS 由前端框架（React）自动转义 + 后端响应 `Content-Type: application/json`

**CORS 配置：**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # 前端开发地址
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
```

**请求追踪：**
- 每个请求分配唯一 `request_id`（中间件生成），贯穿日志和错误响应
- 响应 Header 返回 `X-Request-ID`

---

## 3. 数据模型与数据流（Round 4）

### 3.1 数据模型设计

> 完整ORM模型见 `backend/app/models/models.py`，完整迁移SQL见 `backend/alembic/versions/001_initial_schema.sql`

#### ER图

```
┌──────────────┐       1:N       ┌──────────────────┐
│   patients   │────────────────▶│   assessments    │  (不可变)
│              │                 │                  │
│  PK: id(UUID)│                 │  PK: id(UUID)    │
│  name        │                 │  FK: patient_id  │
│  age         │                 │  status          │
│  gender      │                 │  risk_level      │
│  diagnosis   │                 │  free_text_input │
│  treatment.. │                 │  symptoms(JSONB) │
│  created_at  │                 │  ctcae_grades    │
│  updated_at  │                 │  ai_* 字段       │
└──────┬───────┘                 │  created_at      │
       │                         └──┬───┬───┬───────┘
       │ 1:N                   1:N  │   │   │ 1:N
       │    ┌───────────────────────┘   │   └──────────────┐
       │    ▼                      1:N  ▼                  ▼
       │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
       │  │   advices    │  │  evidences   │  │ contact_requests │
       │  │ FK: assess.. │  │ FK: assess.. │  │ FK: assessment_id│
       │  │ content      │  │ rule_id      │  │ FK: patient_id   │
       │  │ source_type  │  │ rule_version │  │ urgency, status  │
       │  └──────────────┘  │ confidence   │  └──────────────────┘
       │                    │ matched_cond │
       │ 1:N                └──────────────┘
       └──▶ event_logs

┌──────────────────┐   ┌───────────────��──┐   ┌──────────────────┐
│  rule_sources    │   │   audit_logs     │   │ prompt_registry  │
│  (独立,版本化)    │   │  (append-only)   │   │  (独立)          │
│ rule_id + version│   │ REVOKE UPD/DEL   │   │ name + version   │
│ conditions(JSONB)│   │ entity_type+id   │   │ is_active        │
│ actions(JSONB)   │   │ old/new(JSONB)   │   │ file_hash(SHA256)│
│ UQ(rule_id,ver)  │   │ actor_id/type    │   │ UQ(name,version) │
└──────────────────┘   └──────────────────┘   └──────────────────┘
```

关系总结：
- Patient 1:N Assessment — 一个患者多次评估
- Assessment 1:N Advice — 一次评估多条建议
- Assessment 1:N Evidence — 一次评估多条依据（命中规则记录）
- Assessment 1:N ContactRequest — 一次评估可触发联系请求
- RuleSource — 独立表，通过rule_id+version被Evidence逻辑引用（非FK，规则版本化后不应级联删除证据）
- AuditLog — 独立表，通过entity_type+entity_id多态关联任意实体
- PromptRegistry — 独立表，通过prompt_name+version被Assessment的prompt_version逻辑引用

#### 核心实体字段定义

**assessments（核心，不可变）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 评估唯一标识 |
| patient_id | UUID FK | 关联患者 |
| status | VARCHAR(20) | pending→graded→enhanced→completed |
| risk_level | VARCHAR(20) | low/medium/high/critical |
| free_text_input | TEXT | 患者自由文本描述 |
| symptoms_structured | JSONB | 结构化症状数据 |
| ctcae_grades | JSONB | 各症状CTCAE分级 {symptom: grade} |
| overall_risk_score | FLOAT | 综合风险评分 |
| ai_extraction_used | BOOLEAN | 是否使用了AI提取 |
| ai_enhancement_used | BOOLEAN | 是否使用了AI增强 |
| ai_model_version | VARCHAR(100) | AI模型版本 |
| prompt_version | VARCHAR(50) | Prompt版本 |
| ai_raw_output | JSONB | AI原始输出（审计用） |
| rule_engine_version | VARCHAR(50) | 规则引擎版本 |
| patient_explanation | TEXT | 患者端解释文本 |
| grading_rationale | TEXT | 分级依据说明 |
| created_at | TIMESTAMPTZ | 创建时间（精确到毫秒，无updated_at） |

设计要点：无updated_at字段（不可变），数据库层BEFORE UPDATE触发器RAISE EXCEPTION强制不可变。

**evidences（审计核心）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 依据唯一标识 |
| assessment_id | UUID FK | 关联评估 |
| rule_id | VARCHAR(100) | 命中的规则业务ID |
| rule_version | VARCHAR(20) | 命中的规则版本号 |
| confidence | FLOAT | 匹配置信度 |
| matched_conditions | JSONB | 命中的具体条件 |
| evidence_text | TEXT | 依据说明文本 |
| created_at | TIMESTAMPTZ | 创建时间 |

**rule_sources（版本化规则定义）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 记录唯一标识 |
| rule_id | VARCHAR(100) | 业务规则ID（如RULE-NAUSEA-G3-001） |
| version | VARCHAR(20) | 语义化版本号 |
| name | VARCHAR(200) | 规则名称 |
| category | VARCHAR(50) | 分类（gastrointestinal/hematologic等） |
| ctcae_term | VARCHAR(100) | CTCAE术语 |
| ctcae_grade | SMALLINT | CTCAE等级 |
| priority | INTEGER | 优先级（越高越优先） |
| conditions | JSONB | 条件定义 |
| actions | JSONB | 动作定义（风险等级、建议模板） |
| status | VARCHAR(20) | active/deprecated/draft |
| effective_from | TIMESTAMPTZ | 生效时间 |
| effective_until | TIMESTAMPTZ | 失效时间（NULL=永久有效） |
| created_by | VARCHAR(100) | 创建人 |
| reviewed_by | VARCHAR(100) | 审核人 |
| created_at | TIMESTAMPTZ | 创建时间 |
| UNIQUE | (rule_id, version) | 同一规则不同版本唯一 |

**audit_logs（append-only）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGSERIAL PK | 自增保证顺序 |
| event_id | UUID | 事件唯一标识 |
| event_type | VARCHAR(100) | 操作类型 |
| entity_type | VARCHAR(50) | 表名 |
| entity_id | UUID | 记录ID |
| actor_id | UUID | 操作人 |
| actor_type | VARCHAR(20) | patient/clinician/system |
| old_value | JSONB | 变更前（INSERT时为null） |
| new_value | JSONB | 变更后 |
| metadata | JSONB | IP、设备、会话等上下文 |
| created_at | TIMESTAMPTZ | 时间戳 |

保护机制：REVOKE UPDATE/DELETE + BEFORE UPDATE/DELETE触发器双保险。

**event_logs（可观测性，按月分区）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID PK | 事件唯一标识 |
| event_type | VARCHAR(50) | 5种事件枚举 |
| session_id | UUID | 会话ID（串联用户旅程） |
| assessment_id | UUID (nullable) | 关联评估 |
| patient_id | UUID | 关联患者 |
| payload | JSONB | 事件数据 |
| client_timestamp | TIMESTAMPTZ | 前端时间戳 |
| server_timestamp | TIMESTAMPTZ | 服务端时间戳 |

#### 数据库层保护机制

- assessments表：BEFORE UPDATE触发器直接RAISE EXCEPTION，数据库层强制不可变
- audit_logs表：BEFORE UPDATE + BEFORE DELETE触发器 + REVOKE权限，双保险
- event_logs/audit_logs：按月分区，预建12个月 + DEFAULT兜底
- 种子数据：8条初始规��（恶心G1/G2/G3、疲劳G1/G3、皮疹G2、发热G3、腹泻G3）+ 2个初始prompt注册

### 3.2 数据流全链路

> 完整数据流设计文档见 `docs/architecture/data-flow-design.md`（1214行，含7条数据流+时序图）

#### 3.2.1 主数据流：评估全链路

```
┌─────────┐    POST /api/v1/assessments     ┌──────────┐
│  前端    │ ──────────────────────────────▶ │ FastAPI  │
│ Next.js  │    AssessmentRequest (JSON)     │ Router   │
└─────────┘                                 └────┬─────┘
                                                  │ Pydantic校验
                                                  ▼
                                          ┌──────────────┐
                                          │ Assessment   │
                                          │ AppService   │
                                          │ (编排器)      │
                                          └──┬───┬───┬───┘
                          ┌──────────────────┘   │   └──────────────────┐
                          ▼                      ▼                      ▼
                   ┌─────────────┐      ┌──────────────┐      ┌──────────────┐
                   │ Symptom     │      │ Grading      │      │ Explanation  │
                   │ Extractor   │      │ Engine       │      │ Enhancer     │
                   │ (LLM)      │      │ (规则引擎)    │      │ (LLM)       │
                   │ 允许降级    │      │ 必须成功      │      │ 允许降级     │
                   └──────┬──────┘      └──────┬───────┘      └──────┬───────┘
                          │                    │                      │
                          └────────┬───────────┘──────────────────────┘
                                   ▼
                          ┌──────────────┐
                          │ 合并结果     │
                          │ 生成不可变   │
                          │ Assessment   │
                          └──────┬───────┘
                                 │ 同一事务
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
             ┌───────────┐ ┌──────────┐ ┌──────────┐
             │assessments│ │ advices  │ │evidences │
             │   表      │ │   表    │ │   表     │
             └───────────┘ └──────────┘ └──────────┘
                    │
                    ▼ (同一事务)
             ┌───────────┐
             │audit_logs │
             │   表      │
             └───────────┘
                    │
                    ▼ (异步，事务提交后)
             ┌───────────┐     ┌──────────────────┐
             │ EventBus  │────▶│ HighRiskDetected? │
             └───────────┘     │ → ContactNotifier │
                               └──────────────────┘
```

**数据格式转换链：**
```
TypeScript (前端)
  → JSON (HTTP body)
    → Pydantic DTO (AssessmentRequest, 入参校验)
      → Domain Entity (Assessment聚合根, 业务逻辑)
        → ORM Model (SQLAlchemy Mapped, 持久化)
          → SQL (INSERT INTO assessments ...)
```

**降级状态矩阵：**

| AI提取 | 规则引擎 | AI增强 | 结果 | HTTP状态 |
|--------|---------|--------|------|---------|
| 成功 | 成功 | 成功 | 完整结果 | 201 |
| 失败 | 成功 | 成功 | 仅结构化数据+规则+增强 | 201, ai_degraded=true |
| 成功 | 成功 | 失败 | 规则结果+基础解释 | 201, ai_degraded=true |
| 失败 | 成功 | 失败 | 纯规则引擎结果 | 201, ai_degraded=true |
| 任意 | 失败 | 任意 | 系统错误 | 500 |

关键设计：规则引擎是唯一不允许降级的组件。AI挂了照样返回201+规则结果，但规则引擎挂了直接500。

#### 3.2.2 审计数据流

审计日志与主数据在同一数据库事务中写入（医疗合规硬性要求）：

```
AssessmentService.submit()
  │
  ├─ BEGIN TRANSACTION
  │   ├─ INSERT INTO assessments ...
  │   ├�� INSERT INTO advices ...
  │   ├─ INSERT INTO evidences ...
  │   └─ INSERT INTO audit_logs ...    ← 同一事务
  └─ COMMIT
```

5个审计触发点：
1. assessment_created — 评估记录创建
2. symptoms_extracted — AI提取完成（含提取结果）
3. grading_completed — 规则引擎分级完成（含命中规则链）
4. enhancement_completed — AI增强完成
5. contact_request_created — 协同请求创建

四层完整性保证：DB REVOKE → 应用层中间件注入 → BIGSERIAL连续性校验 → 快照hash可重建。

#### 3.2.3 事件数据流（5个可观测性事件）

```
前端 EventTracker
  │
  ├─ assessment_started    → 用户进入输入页
  ├─ assessment_submitted  → 用户点击提交
  ├─ result_viewed         → 结果页渲染完成
  ├─ contact_team_clicked  → 用户点击联系团队
  └─ assessment_closed     → 用户离开结果页
  │
  ▼ POST /api/v1/events (批量上报, 202 Accepted)
  │
  ▼ INSERT INTO event_logs (按月分区)
```

session_id串联同一用户旅程中的所有事件，支持漏斗分析。

#### 3.2.4 时序图（一次完整评估）

```
Patient    Frontend    FastAPI    AssessmentSvc    LLM(Extract)    RuleEngine    LLM(Enhance)    DB
  │           │           │            │               │               │              │           │
  │──输入症状─▶│           │            │               │               │              │           │
  │           │──POST────▶│            │               │               │              │           │
  │           │           │──validate─▶│               │               │              │           │
  │           │           │            │──extract()───▶│               │              │           │
  │           │           │            │               │──Claude API──▶│              │           │
  │           │           │            │◀──symptoms────│  (~1-2s)      │              │           │
  │           │           │            │──grade()─────────────────────▶│              │           │
  │           │           │            │◀──GradingResult───────────────│  (~5ms)      │           │
  │           │           │            │──enhance()───────────────────────────────────▶│          │
  │           │           │            │               │               │◀──explanation─│ (~1-2s)  │
  │           │           │            │──save()──────────────────────────────────────────────────▶│
  │           │           │            │               │               │              │  (~10ms)  │
  │           │           │◀──201──────│               │               │              │           │
  │           │◀──result──│            │               │               │              │           │
  │◀──展示────│           │            │               │               │              │           │
  │           │           │            │               │               │              │           │
  总延迟: 正常 2-4s, AI降级 ~20ms
```

### 3.3 存储方案

> 完整实现见 `backend/infrastructure/db/` 目录:
> - `init.sql` — DDL、索引、分区、权限、生命周期管理函数
> - `postgresql.conf` — PostgreSQL 参数调优
> - `database.py` — asyncpg 连接池 + Redis 缓存策略
> - `docker-compose.yml` (项目根目录) — PostgreSQL + Redis 容器编排

#### 3.3.1 PostgreSQL 配置与优化

**连接池 (asyncpg + SQLAlchemy 2.0 async):**

| 参数 | 值 | 理由 |
|------|-----|------|
| pool_size | 10 | 医疗系统并发不高但要求低延迟 |
| max_overflow | 10 | 突发高风险评估并发写入 |
| pool_pre_ping | True | 避免使用已断开的连接 |
| pool_recycle | 1800s | 防止 PG 端超时断开 |
| statement_cache_size | 100 | 查询模式固定，缓存命中率高 |

**关键参数调优 (针对医疗数据特点):**

| 参数 | 开发值 | 生产值 | 医疗场景考量 |
|------|--------|--------|-------------|
| shared_buffers | 256MB | 4GB | 评估结果+审计日志频繁读写 |
| work_mem | 8MB | 32MB | JSONB 字段排序/聚合需要更多内存 |
| synchronous_commit | on | on | 医疗数据零丢失，不可关闭 |
| fsync | on | on | 同上 |
| wal_level | replica | logical | 支持 PITR + 未来 CDC |
| archive_mode | on | on | WAL 归档，审计数据持久性保证 |
| random_page_cost | 1.1 | 1.1 | SSD 存储优化 |
| default_statistics_target | 200 | 500 | JSONB 查询需要更精确的统计 |

#### 3.3.2 索引策略

按查询频率分层设计:

| 查询模式 | 频率 | 索引类型 | 索引定义 |
|---------|------|---------|---------|
| patient_id 查历史评估 | 高频 | B-tree 复合 | `(patient_id, created_at DESC)` |
| risk_level 筛选 | 中频 | B-tree + 部分索引 | `(risk_level, created_at DESC)` + `WHERE risk_level='high'` |
| 时间范围查询 | 中频 | BRIN | `BRIN(created_at)` — 追加写入场景最优 |
| JSONB 字段条件 | 低频 | GIN | `GIN(symptoms jsonb_path_ops)` |

索引维护: autovacuum 缩短至 30s 间隔，5% 行变更触发 VACUUM/ANALYZE。

#### 3.3.3 分区策略

`event_logs` 和 `audit_logs` 按月分区 (RANGE on created_at):
- 预创建 12 个月分区 + DEFAULT 兜底分区
- `create_monthly_partition()` 函数自动创建新分区 (幂等)
- 分区裁剪: 按时间范围查询时 PG 自动跳过无关分区
- 索引自动继承到子分区

#### 3.3.4 数据生命周期

```
热数据 (近3个月)     → 主库，全索引，高性能查询
温数据 (3-12个月)    → 主库，保留索引，正常查询
冷数据 (>12个月)     → DETACH 分区 → pg_dump 归档 → 可选删除
```

医疗数据保留期限 (合规):
- 评估结果 (assessments): 永久保留 (不可变，医疗记录法定保存期 ≥30 年)
- 审计日志 (audit_logs): ≥5 年在线，之后归档
- 事件日志 (event_logs): ≥1 年在线，之后归档
- 患者数据 (patients): 随评估结果永久保留

`archive_old_partitions()` 函数: DETACH 超期分区，独立备份后可安全删除。

#### 3.3.5 备份与恢复

| 策略 | 频率 | 工具 | 保留期 |
|------|------|------|--------|
| 全量备份 | 每日 02:00 | pg_basebackup / pgBackRest | 30 天 |
| WAL 归档 (增量) | 持续 | archive_command → 对象存储 | 90 天 |
| 逻辑备份 (审计表) | 每周 | pg_dump --table=audit_logs* | 永久 |

PITR (时间点恢复): WAL 归档 + 全量备份，可恢复到任意时间点。审计数据的特殊要求: 逻辑备份独立存储，与主备份物理隔离，防止单点故障导致审计链断裂。

#### 3.3.6 缓存策略

| 数据类型 | 缓存位置 | TTL | 失效策略 |
|---------|---------|-----|---------|
| 规则快照 (copy-on-write) | Redis | 不过期 | key 含版本 hash，版本变更时写新 key |
| 患者基本信息 | Redis | 5 min | TTL + 更新时主动失效 |
| 评估结果 (不可变) | Redis | 1 hour | 不可变数据，TTL 仅控制内存 |
| 评估列表/分页 | 不缓存 | — | 实时查询 |
| 健康检查 | 不缓存 | — | 必须实时 |

规则缓存采用 copy-on-write 快照模式: 规则版本变更时生成新快照写入新 key，评估过程中引用的快照不受影响，保证单次评估内规则一致性。

---

## 4. 智能体闭环设计（Round 5）

### 4.1 感知层

> 完整实现见 `backend/app/perception/` 目录（8个模块 + 测试）

#### 架构总览

```
PerceptionInput (表单 + 自由文本)
  │
  ├─ FormProcessor ──────── PRO-CTCAE问卷 → SymptomEntry (置信度=1.0)
  │
  └─ 三级级联提取 (自由文本)
       │
       ├─ L1: KeywordExtractor ── 词典匹配 (<10ms, 置信度0.7-0.9)
       │     ↓ 置信度<0.8 或无结果
       ├─ L2: RuleNLPExtractor ── jieba分词+模式匹配 (<50ms, 置信度0.8-0.95)
       │     ↓ 置信度<0.85 或文本>50字
       └─ L3: LLMExtractor ────── Claude API + Tool Use (<3s, 置信度0.85-0.98)
             ↓ 超时10s → 降级
  │
  ▼
SymptomFuser ── 多来源融合 (FORM > LLM > RULE_NLP > KEYWORD)
  │
  ▼
PerceptionOutput → 决策层
```

#### 多模态输入处理

**结构化输入（PRO-CTCAE表单）：**
- 频率/严重程度/干扰程度三维度（各0-4分）
- 三维度取最大值映射到CTCAE Grade 1-4
- 置信度固定为1.0（患者直接选择，无歧义）

**自由文本输入（三级级联）：**

| 级别 | 技术 | 延迟 | 置信度 | 触发条件 |
|------|------|------|--------|---------|
| L1 | 症状词典+正则匹配 | <10ms | 0.7-0.9 | 始终执行 |
| L2 | jieba分词+医学词典+模式匹配 | <50ms | 0.8-0.95 | L1置信度<0.8或无结果 |
| L3 | Claude API + Tool Use | <3s | 0.85-0.98 | L2置信度<0.85或文本>50字 |

紧急关键词快速通道：发热/出血/呼吸困难/过敏等直接触发高风险标记，不等待级联完成。

**症状标准化映射（30+ CTCAE术语，150+口语化表达）：**
- "吃不下饭" → 食欲下降(Anorexia)
- "手脚发麻" → 周围神经病变(Peripheral neuropathy)
- "浑身没劲" → 疲劳(Fatigue)
- 否定表达识别："不恶心" → 排除恶心

**融合策略（SymptomFuser）：**
- 同一症状多来源时：严重程度取高优先级来源值，置信度取最高
- 紧急标记取并集（任一来源标记紧急即为紧急）
- 否定状态以高优先级来源为准
- 优先级排序：FORM > LLM > RULE_NLP > KEYWORD

#### LLM提取的关键设计

- Tool Use强制结构化输出：`tool_choice={"type":"tool","name":"extract_symptoms"}`
- Pydantic模型校验返回数据 + 医学术语标准化
- 超时10s → 降级返回L1+L2结果，不阻塞评估流程

### 4.2 决策层

> 完整实现见 `backend/app/decision/` 目录（6个模块）

#### 风险评分算法

**单症状CTCAE分级：** 基于决策表匹配，无命中时默认Grade 1 + 低置信度。

**多症状综合风险评分：**
```
risk_score = Σ(grade_i × weight_i × urgency_factor_i) × interaction_multiplier
```

症状权重表（反映临床严重性差异）：

| 症状 | 权重 | 理由 |
|------|------|------|
| 粒缺性发热 | 5.0 | 可致命，需紧急处理 |
| 心脏毒性 | 4.5 | 不可逆损伤风险 |
| 严重出血 | 4.0 | 危及生命 |
| 呼吸困难 | 4.0 | 可能提示肺栓塞 |
| 周围神经病变 | 2.5 | 影响生活质量，可能不可逆 |
| 恶心呕吐 | 2.0 | 常见但需关注脱水 |
| 疲劳 | 1.5 | 最常见，通常可管理 |
| 脱发 | 0.3 | 非危险性副作用 |

紧迫因子：急性发作×2.0, 进行性加重×1.5, 稳定×1.0, 好转×0.7

**多症状交互效应（8组）：**
- 中性粒细胞减少 + 发热 = ×2.0（粒缺性发热，紧急）
- 恶心 + 呕吐 + 腹泻 = ×1.5（脱水风险叠加）
- 心脏毒性 + 呼吸困难 = ×1.8（心衰可能）

**风险等级映射：** Sigmoid归一化到[0,1]，阈值：<0.3=LOW, 0.3-0.6=MEDIUM, >=0.6=HIGH

#### 多规则冲突解决

| 冲突类型 | 解决策略 |
|---------|---------|
| 同症状多规则匹配 | 取最高严重度 |
| 规则结论矛盾 | 优先级排序：SAFETY > GUIDELINE > CONSENSUS > EMPIRICAL |
| 多症状交互效应 | 预定义交互规则表，乘以交互因子 |
| 药物关联叠加 | 蒽环类用药时心脏毒性优先级+80 |

#### 决策置信度

综合置信度 = 0.7 × rule_confidence + 0.3 × llm_confidence

| 综合置信度 | 处理策略 |
|-----------|---------|
| >= 0.8 | 正常输出 |
| 0.6-0.8 | 输出但标记"建议咨询医生确认" |
| 0.4-0.6 | 要求补充信息 |
| < 0.4 | 转人工处理 |

#### 决策审计链

每步决策完整记录：输入参数 → 匹配的规则ID+版本 → 中间计算过程 → 最终结果。自动生成Evidence实体，关联到Assessment。

### 4.3 执行层

> 完整实现见 `backend/app/execution/` 目录（5个模块）

#### 建议生成管线

```
规则引擎输出 (GradingResult)
    │
    ▼
┌──────────────────┐
│ 规则模板填充      │ ← 每条规则的actions中定义建议模板
│ 优先级排序        │ ← 高风险建议排在前面
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ LLM增强（可选）   │ ← 将规则结果转为患者可理解的自然语言
│ 患者版 vs 医生版  │ ← 两套Prompt模板，差异化生成
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 免责声明附加      │ ← "本评估仅供临床参考，不构成医疗建议。请遵医嘱。"
│ AI标注           │ ← AI生成的内容标注"AI辅助生成"
└──────────────────┘
```

患者版解释：简洁通俗，避免医学术语，重点是"你该做什么"
医生版解释：详细专业，包含CTCAE分级依据、规则命中链、置信度

#### 协同请求触发机制

**自动触发：** HighRiskDetected领域事件 → ContactNotifier

**通知渠道矩阵：**

| 紧急度 | 渠道 | 时效要求 |
|--------|------|---------|
| CRITICAL | 电话+短信+APP推送 | 即时 |
| HIGH | 短信+APP推送 | 15分钟内 |
| MODERATE | APP推送 | 1小时内 |

**超时升级机制：**
- 24h未响应 → ELEVATED，通知上级医生
- 48h未响应 → CRITICAL，紧急升级

#### 不可变快照

Assessment聚合根最终状态冻结，包含：
- 完整症状数据 + CTCAE分级 + 风险评分
- 命中规则链（rule_id + version）
- AI模型版本 + Prompt版本 + AI原始输出
- SHA-256 hash完整性校验
- 版本号递增（同一患者的评估序列）

### 4.4 学习层

> 设计原则：架构完整覆盖全链路，MVP仅实现数据收集基座，优化流程作为架构预留。
> 标注：[MVP] = 首版实现 | [Phase 2] = 数据积累后 | [Phase 3+] = 长期规划

#### 反馈收集机制

**显式反馈：**

| 反馈类型 | 采集时机 | 实现阶段 |
|---------|---------|---------|
| 患者满意度（👍/👎 + 可选文字） | 查看结果后 | [MVP] |
| 医生审核修改（修改分级/建议/确认） | 医生审核时 | [Phase 2] |
| 临床结局（住院/好转/恶化） | 评估后7/30天 | [Phase 2] |

**隐式反馈（零额外开发成本，复用event_logs）：**
- 结果页停留时长（result_viewed → assessment_closed）[MVP]
- 是否点击联系团队 [MVP]
- 同一患者多次评估的risk_level时序变化 [Phase 2]
- 医生采纳率（审核通过率）[Phase 2]

**新增数据表：** patient_feedbacks [MVP]、doctor_reviews [Phase 2架构预留]、clinical_outcomes [Phase 2架构预留]

反馈API：`POST /api/v1/assessments/{id}/feedback`，每次评估只允许一条反馈（幂等，UNIQUE约束）。

#### 规则优化流程 [Phase 2]

```
数据分析 → 调整提案 → 医学专家审核 → 回归测试 → 灰度发布(10%流量) → 全量发布
```

核心指标：
- 灵敏度(Sensitivity) >= 95%（漏报是致命的）
- 在保持灵敏度前提下逐步降低误报率
- 漏报（高风险判为低风险）是医疗场景最致命的错误

版本化约束：MAJOR（风险等级变更）→ 医学审核+灰度 | MINOR（阈值调整）→ 医学审核+回归 | PATCH（文案）→ 技术审核

#### A/B测试框架 [Phase 2]

- 分流：hash(patient_id + experiment_id) % 100，同一患者始终在同一组
- 安全约束：高风险场景不参与A/B测试，直接走最新规则版本
- 安全熔断：实验组漏报率 > 对照组1.5倍 → 自动暂停；出现missed_high_risk → 立即终止

#### Prompt优化流程 [Phase 2]

```
收集Bad Case → 分析失败模式 → 调整Prompt(Git PR) → Golden Test Set回归 → 灰度上线
```

评估指标：提取Precision>=0.90, Recall>=0.85, 幻觉率<0.02, 遗漏高危率<0.01

Golden Test Set：初始>=50个标注case，覆盖所有CTCAE分类，至少2名医生独立标注。

#### 模型迭代��径

| 阶段 | 技术 | 数据量要求 | 关键里程碑 |
|------|------|-----------|-----------|
| 阶段1 [MVP] | 规则引擎 + Claude API | 无 | 系统上线，开始积累数据 |
| 阶段2 [6-12月] | + BERT微调症状分类 | >=5,000条评估 | F1>=0.90，可替代LLM做提取 |
| 阶段3 [12-24月] | + 个体化风险预测(XGBoost) | >=20,000条评估 | AUC>=0.85 |
| 阶段4 [24月+] | + 联邦学习多院协作 | 多院数据 | 不共享原始数据的协作训练 |

所有阶段规则引擎始终作为安全兜底，不被替代。

#### 闭环数据流图

```
┌─────────────────────────────────────────────────────────────────┐
│                    感知-决策-执行-学习 闭环                       │
│                                                                  │
│  ┌──────┐    ┌──────┐    ┌──────┐    ┌──────┐                  │
│  │ 感知  │───▶│ 决策  │───▶│ 执行  │───▶│ 反馈  │                │
│  │      │    │      │    │      │    │ 收集  │                  │
│  │ 症状  │    │ 规则  │    │ 建议  │    │      │                  │
│  │ 提取  │    │ 引擎  │    │ 生成  │    │ 患者  │                  │
│  │ 结构化│    │ +AI  │    │ 通知  │    │ 医生  │                  │
│  └──┬───┘    └──────┘    └──────┘    │ 结局  │                  │
│     ▲                                 └──┬───┘                  │
│     │                                    │                       │
│     │         ┌──────────────────────────┘                       │
│     │         ▼                                                  │
│     │    ┌──────┐    ┌──────┐    ┌──────┐                       │
│     │    │ 分析  │───▶│ 优化  │───▶│ 验证  │                     │
│     │    │      │    │      │    │      │                       │
│     └────│ 准确率│    │ 规则  │    │ 回归  │                       │
│          │ 指标  │    │ Prompt│    │ 测试  │                       │
│          │ Bad  │    │ 模型  │    │ 灰度  │                       │
│          │ Case │    │      │    │ 发布  │                       │
│          └──────┘    └──────┘    └──────┘                       │
│                                                                  │
│  [MVP实现范围]: 感知→决策→执行 + 反馈收集(患者满意度+事件日志)    │
│  [架构预留]:    分析→优化→验证 全链路 + 医生审核 + 临床结局       │
└─────────────────────────────────────────────────────────────────┘
```

#### 学习层安全约束

- 规则变更必须经过医学专家审核（audit_logs记录审核人+审批ID）
- Prompt变更必须经过Golden Test Set回归测试
- 任何自动化优化不得降低安全规则的灵敏度（>=95%硬约束）
- 学习层的所有变更走审计日志，与业务数据同等审计标准

---

## 5. 可观测性与工程化（Round 6）

### 5.1 事件埋点设计

> 完整实现见 `frontend/lib/event-tracker.ts`（前端SDK）+ `backend/app/observability/events.py`（后端接收）

#### 前端事件采集SDK（EventTracker）

**session_id管理：** `时间戳(base36) + crypto.getRandomValues(12字节)`，存sessionStorage，30分钟过期自动续期，串联同一用户旅程。

**5个事件触发时机与采集数据：**

| 事件 | 触发时机 | 采集数据 |
|------|---------|---------|
| assessment_started | 评估页useEffect挂载 | session_id, referrer, url |
| assessment_submitted | 提交按钮点击后 | assessment_id, input_length, symptom_count |
| result_viewed | 结果页渲染完成 | assessment_id, risk_level, load_time_ms |
| contact_team_clicked | 点击"联系团队"按钮 | assessment_id, urgency |
| assessment_closed | 页面卸载/路由离开 | assessment_id, duration_sec, completed |

**上报策略：**
- 批量攒批：buffer满10条立即flush
- 定时flush：每5秒
- 页面离开：`visibilitychange=hidden` + `pagehide` 用 `sendBeacon` 同步兜底
- 离线缓存：fetch失败重试3次（指数退避），仍失败写入IndexedDB，`online`事件触发重传

**后端接收：**
- `POST /api/v1/events` 批量接收（最多50条/次），返回202 Accepted
- Pydantic校验EventType枚举、session_id必填、时间戳不超前5分钟
- `BackgroundTasks`异步bulk insert，HTTP响应不等待数据库写入

#### structlog结构化日志

- 双模式：开发环境彩色控制台，生产环境JSON（`ensure_ascii=False`支持中文）
- 请求上下文自动注入：ContextVar携带request_id、patient_id、assessment_id
- 敏感数据脱敏：patient_name → `张*三`，free_text_input超100字符截断
- 日志级别：INFO(默认) / WARNING(AI降级) / ERROR(异常) / CRITICAL(审计链异常)

#### OpenTelemetry集成

**Traces（自定义Span）：**
- `span_llm_call(model, prompt_version)` — LLM调用延迟和错误
- `span_rule_engine(rule_count, snapshot_hash)` — 规则引擎执行
- `span_db_write(table, operation)` — 数据库写入
- `@traced`装饰器：自动为函数创建span

**Metrics（预定义指标）：**
- `gentlemend.http.request.duration` — 请求延迟直方图
- `gentlemend.ai.calls.total` / `gentlemend.ai.calls.errors` — AI调用计数
- `gentlemend.rules.hits.total` — 规则命中分布（按rule_id分组）
- `gentlemend.assessment.duration` — 评估处理延迟

MVP阶段ConsoleSpanExporter输出到日志，生产切OTLP gRPC。

### 5.2 审计实现

> 完整实现见 `backend/app/observability/audit.py` + `integrity.py`

#### 审计中间件

**AuditContextMiddleware（Starlette中间件）：**
- 每个请求自动从`X-Actor-ID`/`X-Actor-Type`头提取actor
- 生成`X-Request-ID`写入ContextVar
- 业务路由通过`Depends(get_audit_logger)`注入AuditLogger

**AuditLogger（依赖注入式）：**
- 与业务session共享事务（原子性：审计记录和业务数据同一COMMIT）
- 自动从ContextVar获取who/when
- `compute_diff()`精简diff，只存变化字段，减少JSONB存储开销

#### 审计链完整性保证

四层防护：

| 层 | 机制 | 检测方式 |
|----|------|---------|
| 数据库层 | REVOKE UPDATE/DELETE + 触发器 | 尝试修改直接报错 |
| 应用层 | HMAC-SHA256签名（`id|event_type|entity_type|entity_id|created_at`） | 批量验签 |
| 连续性 | BIGSERIAL自增ID | `lead()`窗口函数检测gap |
| 定期校验 | `run_integrity_check()` | 输出IntegrityReport |

签名存入`metadata.hmac_sha256`，批量验证分批500条/批避免内存溢出。

### 5.3 监控与告警

> 完整实现见 `backend/app/monitoring/`

#### 监控指标体系（RED方法）

**系统健康指标：**
- Rate: 请求速率（按端点分组）
- Errors: 错误率（4xx/5xx/AI超时/规则引擎异常）
- Duration: P50/P95/P99延迟

**业务指标：**
- 评估完成率（started vs completed）
- 风险等级分布
- AI降级率
- 规则命中率Top10
- 患者反馈满意度

**基础设施指标：**
- PostgreSQL连接池使用率
- Redis命中率
- 内存/CPU使用率

`/api/metrics`端点导出指标快照。

#### 告警规则（7条）

| 级别 | 规则 | 阈值 | 渠道 |
|------|------|------|------|
| P0 | 5xx错误率 | >5% (5min窗口) | 电话+短信+Slack |
| P0 | P99延迟 | >3s | 电话+短信+Slack |
| P1 | AI降级率 | >50% | Slack+邮件 |
| P1 | 评估完成率 | <80% | Slack+邮件 |
| P1 | 连接池使用率 | >90% | Slack+邮件 |
| P2 | 高风险占比异常 | >30% (1h窗口) | Slack |
| P2 | 审计日志gap | 检测到gap | Slack |

升级策略：P0→15min无响应升级主管 | P1→1h无响应升级P0

#### 健康检查

- `GET /api/health` — 存活探针，不依赖外部服务
- `GET /api/health/ready` — 就绪探针，并发检查PostgreSQL(SELECT 1) + Redis(PING) + AI API(可选)
- AI不可用仅标记degraded，不影响就绪状态（规则引擎可独立工作）

### 5.4 部署与运维

> 完整配置见项目根目录 `docker-compose.yml` + `Makefile` + `.github/workflows/ci.yml`

#### Docker Compose

4个服务：backend + frontend + postgres + redis

```yaml
services:
  backend:   # FastAPI, 端口8000, depends_on postgres+redis healthy
  frontend:  # Next.js, 端口3000, depends_on backend
  postgres:  # PostgreSQL 16, 数据卷持久化, 健康检查pg_isready
  redis:     # Redis 7, 数据卷持久化, 健康检查redis-cli ping
```

- 健康检查 + depends_on条件启动（postgres/redis healthy后才启backend）
- 资源限制（backend: 1CPU/1GB, postgres: 2CPU/2GB）
- `docker-compose.dev.yml`覆盖：源码挂载+热重载+调试端口

#### CI/CD（GitHub Actions）

```
backend-lint ──→ backend-test ──→ docker-build
                  backend-integration (PostgreSQL+Redis service containers)
frontend-lint ──→ frontend-test ──→ docker-build
```

6个job，前后端并行构建，集成测试自带数据库。

#### Makefile（12个命令）

| 命令 | 说明 |
|------|------|
| `make setup` | 首次安装依赖 |
| `make dev` | 启动开发环境 |
| `make test` | 运行全部测试 |
| `make test-unit` | 仅单元测试 |
| `make test-integration` | 仅集成测试 |
| `make lint` | 代码检查(ruff+mypy) |
| `make migrate` | 数据库迁移 |
| `make seed` | 种子数据 |
| `make build` | 构建Docker镜像 |
| `make up` | docker-compose up |
| `make down` | docker-compose down |
| `make clean` | 清理 |

#### 快速启动（3步）

```bash
git clone <repo> && cd GentleMend
cp .env.example .env          # 配置API密钥
make up                        # 一键启动
# 访问 http://localhost:3000（前端）/ http://localhost:8000/docs（API文档）
```

---

## 7. 实现偏差说明（Round 7 补充）

> 以下记录设计阶段（Round 2-6）与最终实现（Round 7）之间的差异。设计文档保留原始选型讨论作为决策记录。

### 7.1 AI 接口变更

| 设计阶段 | 最终实现 | 原因 |
|---------|---------|------|
| Anthropic Claude API + Tool Use | OpenAI 兼容接口（DeepSeek） | 通过 OpenAI SDK 兼容层调用，支持任意 OpenAI 兼容服务 |
| anthropic SDK 直接调用 | openai SDK + `AI_API_BASE_URL` 配置 | 更灵活的多供应商支持 |
| Claude Haiku 做症状提取 | `AI_MODEL` 环境变量可配置 | 默认 deepseek-chat，可切换任意模型 |

### 7.2 AI 增强输出结构变更

设计阶段的 AI 输出为简单的两段文本。最终实现改为结构化报告：主诉概要 + 需要重视的症状（原因/警示信号/建议）+ 无需过虑的症状 + 综合建议。前端按标记渲染为分色卡片。

### 7.3 风险评分算法变更

| 设计阶段 | 最终实现 |
|---------|---------|
| 固定映射 low=0, medium=0.5, high=1.0 | 加权计算：`score = risk_order×0.5 + grade×0.15 + severity×0.02`，`final = max×0.6 + avg×0.4` |

### 7.4 新增功能（设计文档未覆盖）

- **用药与手术信息**：新增 `medication_info` 和 `medical_history` 字段，传给 AI 增强分析
- **i18n 国际化**：React Context + JSON 翻译文件，中英文切换
- **三级严重程度按钮**：替代 1-10 滑块，每个症状 3 个描述性按钮（轻/中/重，映射 severity 2/5/8）
- **评估依据中文化**：evidence_text 从英文改为中文
- **患者反馈 API**：`POST /assessments/{id}/feedback`，幂等，闭环学习入口

### 7.5 数据库兼容

| 设计阶段 | 最终实现 |
|---------|---------|
| 仅 PostgreSQL | SQLite（开发）+ PostgreSQL（生产）双模式 |
| UUID / JSONB / BigInteger | SQLite 用 String(36) / JSON / Integer 适配 |
