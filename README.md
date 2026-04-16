<h1 align="center">浅愈 (GentleMend)</h1>

<p align="center">
  <img src="resources/logo.png" alt="GentleMend Logo" width="160"/>
</p>

<p align="center">
  <a href="#"><img alt="License" src="https://img.shields.io/badge/license-MIT-green.svg" /></a>
  <a href="#"><img alt="Python" src="https://img.shields.io/badge/python-3.11+-blue.svg?logo=python&logoColor=white" /></a>
  <a href="#"><img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white" /></a>
  <a href="#"><img alt="Next.js" src="https://img.shields.io/badge/Next.js-16-black.svg?logo=next.js&logoColor=white" /></a>
  <a href="#"><img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql&logoColor=white" /></a>
</p>

---

✅ **医疗安全优先 | 完全可审计 | AI 增强 | 中英双语**  
✅ **规则引擎保底 + AI 智能提升 | 症状提取 | 风险评估 | 个性化建议**  
✅ **乳腺癌副作用智能评估系统 — 温和陪伴康复之路**  

乳腺癌患者在治疗过程中常遇到各种副作用，本系统通过规则引擎（CTCAE 标准）+ AI 增强的双轨架构，帮助患者快速评估副作用风险等级，获得个性化建议，并在必要时及时联系医疗团队。

---

## 🎬 系统演示

<div align="center">
  <img src="resources/demo.gif" alt="系统演示" width="800"/>
</div>

## 🏗️ 系统架构与数据流图

该部分是为了系统梳理本项目的核心架构图、数据流图以及智能体闭环流程图。

### 📐 1. 架构图 (Architecture Diagram)

该图展示了系统的整体分层架构，特别是"规则引擎（保底）+ AI 增强（提升）"的双轨设计。

```mermaid
graph TD
    subgraph Frontend ["前端客户端 (Next.js)"]
        UI["用户界面 UI"]
        API_Client["API 客户端"]
        Tracker["埋点追踪 SDK"]
    end

    subgraph Backend ["后端服务 (FastAPI)"]
        API_Layer["API 路由层"]

        subgraph AgentEngine ["Agent 核心引擎"]
            Perception["感知层 Perception\n三级级联提取"]
            Decision["决策层 Decision\n规则匹配+加权评分"]
            Execution["执行层 Execution\n双版本建议生成"]
        end

        subgraph RuleBase ["确定性基线"]
            RuleEngine["规则引擎"]
            SeedData["规则种子数据 / CTCAE"]
        end

        subgraph AIEnhancement ["AI 增强层"]
            LLMExtractor["LLM 症状提取"]
            LLMAdvisor["LLM 建议润色"]
        end

        subgraph Observability ["可观测性与审计"]
            AuditTrail["审计追踪构建器"]
            EventLogger["事件埋点记录器"]
        end
    end

    subgraph Database ["数据持久层"]
        DB[("PostgreSQL / SQLite")]
    end

    UI -->|"用户输入"| API_Client
    API_Client -->|"HTTP 请求"| API_Layer
    Tracker -->|"上报行为事件"| API_Layer

    API_Layer --> AgentEngine
    Perception --> Decision
    Decision --> Execution

    Perception -.->|"L3 复杂文本触发"| LLMExtractor
    Execution -.->|"自然语言润色触发"| LLMAdvisor
    Decision <-->|"获取匹配规则"| RuleEngine
    RuleEngine --> SeedData

    AgentEngine --> AuditTrail
    API_Layer --> EventLogger

    AuditTrail --> DB
    EventLogger --> DB
    Execution -->|"持久化不可变记录"| DB
```

---

### 🌊 2. 数据流图 (Data Flow Diagram)

该图详细描述了一次患者评估请求从输入到输出的完整管线数据流向。

```mermaid
graph TD
    Input["患者输入: 自由文本 / 结构化表单"]

    subgraph Perception_Pipeline ["感知流: 提取与标准化"]
        FormProc["表单处理器"]
        CascadeExtract{"级联提取调度器"}
        L1["L1: 关键词精准匹配"]
        L2["L2: 规则 NLP 提取"]
        L3["L3: LLM 语义大模型提取"]
        Fuser["症状融合器 SymptomFuser"]
    end

    subgraph Decision_Pipeline ["决策流: 评估与推理"]
        RuleEval["规则评估 Rule Evaluation"]
        CTCAE["CTCAE 症状分级"]
        RiskScore["综合风险评分 Risk Scoring"]
        ConflictRes["冲突解决与降级处理"]
        Confidence["置信度计算"]
    end

    subgraph Execution_Pipeline ["执行流: 结果生成"]
        RuleAdvice["基础规则建议生成"]
        SortAdvice["紧急度与优先级排序"]
        AIEnhance["AI 建议增强 / 医生摘要生成"]
    end

    Output["评估报告 Assessment Report"]

    Input --> FormProc
    Input --> CascadeExtract
    CascadeExtract --> L1
    CascadeExtract -->|"L1 置信度低 / 文本较长"| L2
    CascadeExtract -->|"L2 置信度低 / 文本复杂"| L3

    FormProc --> Fuser
    L1 --> Fuser
    L2 --> Fuser
    L3 --> Fuser

    Fuser -->|"结构化症状列表"| RuleEval
    RuleEval -->|"匹配到的规则列表"| CTCAE
    CTCAE --> RiskScore
    RiskScore --> ConflictRes
    ConflictRes --> Confidence

    Confidence -->|"包含审计数据的 DecisionResult"| RuleAdvice
    RuleAdvice --> SortAdvice
    SortAdvice --> AIEnhance
    AIEnhance --> Output
```

---

### 🔄 3. 智能体闭环流程图 (Agent Closed-loop Flowchart)

该图展示了系统如何实现"感知 - 决策 - 执行 - 学习"的智能体完整闭环。

```mermaid
graph TD
    subgraph Perception ["1. 感知层 (Perception)"]
        Receive["接收用户非结构化描述"]
        Understand["理解上下文: 病史/用药/症状"]
        Standardize["转化为标准化医疗术语 CTCAE"]
    end

    subgraph Decision ["2. 决策层 (Decision)"]
        Infer["多维度推理: 匹配医疗安全规则"]
        Stratify["风险分层: 判定 高/中/低 风险"]
        Guard["安全守护: 冲突检测与最高风险优先"]
    end

    subgraph Execution ["3. 执行层 (Execution)"]
        Generate["生成行动建议: 居家观察/联系团队/就医"]
        Empathize["同理心表达: AI 温和润色避免恐慌"]
        Output["交付可解释的、带有审计链的评估结果"]
    end

    subgraph Learning ["4. 学习层 (Learning)"]
        Feedback["收集患者显式反馈"]
        Observe["收集隐式埋点: 停留时间/点击求助行为"]
        Audit["记录完整决策依据链与 LLM 原始输出"]
        Evolve["系统迭代: 优化规则阈值与 Prompt 提示词"]
    end

    Perception -->|"输出结构化症状向量"| Decision
    Decision -->|"输出风险级别与依据证据"| Execution
    Execution -->|"呈现给用户与医疗团队"| Learning
    Learning -.->|"数据反哺: 识别漏报症状"| Perception
    Learning -.->|"规则热更新: 调整风险权重"| Decision
```

## 🚀 快速开始

### 💻 本地开发（推荐）

```bash
# 后端
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# 前端（新终端）
cd frontend
npm install
npm run build
npx next start -p 3000
```

默认使用 SQLite，无需安装 PostgreSQL/Redis。

启动后访问:
- 前端界面: http://localhost:3000
- API 文档: http://localhost:8000/docs

### 🤖 AI 增强配置（可选）

在项目根目录 `.env` 中配置 AI API（支持 DeepSeek/OpenAI 兼容接口）：

```bash
AI_API_BASE_URL=https://api.deepseek.com/v1
AI_API_KEY=your-api-key
AI_MODEL=deepseek-chat
```

未配置时系统使用纯规则引擎模式，功能完整可用。配置后启用：
- AI 症状提取（从自由文本智能识别症状和严重程度）
- AI 结构化解读（主诉概要 + 重点关注 + 无需过虑 + 个性化建议）

### 🐳 Docker 部署

```bash
make setup && make dev
```



核心原则:
- 规则引擎作为确定性底线，AI 作为增强层（AI不可用时自动降级）
- 评估结果不可变，只追加新版本
- 每条建议可追溯到具体规则/依据
- 中英文双语支持

技术栈: Python 3.11 + FastAPI / SQLite (开发) + PostgreSQL 16 (生产) / Next.js 16 + React 19 / DeepSeek API

## 📁 项目结构

```
GentleMend/
├── backend/
│   ├── app/
│   │   ├── ai/               # AI增强层 (症状提取 + 结构化解读 + 降级)
│   │   ├── api/              # API路由 (patients, assessments, events, contact_requests, feedback)
│   │   ├── db/               # 数据库配置 + 规则种子数据
│   │   ├── models/           # ORM模型
│   │   ├── rules/            # 规则引擎 (CTCAE决策表 + 加权评分)
│   │   ├── monitoring/       # 监控告警
│   │   └── main.py           # FastAPI入口
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── app/              # Next.js App Router (输入页/结果页/历史页)
│       │   └── components/   # 共享组件 (Nav, RiskBadge, Footer)
│       └── lib/
│           ├── api.ts        # 后端API客户端
│           ├── event-tracker.ts  # 事件埋点SDK
│           └── i18n/         # 国际化 (中/英文)
├── docs/                     # 设计文档 (PRD, SDD, 架构图)
├── docker-compose.yml        # 服务编排
└── .env.example              # 环境变量模板
```

## 🔌 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/patients/` | 创建患者 |
| POST | `/api/v1/assessments/` | 提交评估（含用药/病史/症状） |
| GET | `/api/v1/assessments/` | 评估历史列表 (分页+筛选) |
| GET | `/api/v1/assessments/{id}` | 查询评估详情 |
| POST | `/api/v1/assessments/{id}/feedback` | 患者反馈（幂等） |
| POST | `/api/v1/events/` | 事件埋点上报 |
| POST | `/api/v1/contact-requests/` | 联系团队请求 |

完整 API 文档: 启动后访问 http://localhost:8000/docs

---

## 📖 文档

- [产品需求文档 (PRD)](docs/PRD.md)
- [系统设计文档 (SDD)](docs/SDD.md)
- [架构设计详解](architecture/)

## 🤝 贡献与联系

欢迎提交 Issue 和 Pull Request！
如有任何问题或建议，请联系 Zheyuan (Max) Kong (卡内基梅隆大学，宾夕法尼亚州)。

Zheyuan (Max) Kong: kongzheyuan@outlook.com | zheyuank@andrew.cmu.edu

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

<div align="center">
  <p>用心陪伴康复之路 · 温和助愈身心</p>
  <p>Made with ❤️ for breast cancer patients</p>
</div>
