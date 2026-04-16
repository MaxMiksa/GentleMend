# 浅愈 (GentleMend) - 系统架构与数据流图

本文档提供了浅愈 (GentleMend) 系统的核心架构图、数据流图以及智能体闭环流程图。

## 1. 架构图 (Architecture Diagram)

该图展示了系统的整体分层架构，特别是“规则引擎（保底）+ AI 增强（提升）”的双轨设计。

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

## 2. 数据流图 (Data Flow Diagram)

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

## 3. 智能体闭环流程图 (Agent Closed-loop Flowchart)

该图展示了系统如何实现“感知 - 决策 - 执行 - 学习”的智能体完整闭环。

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