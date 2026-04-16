# Release Notes

## v1.0.0 – Initial Release / 首个正式版本 (2026-04-15)

## ✨ 规则引擎 + AI 增强的医疗决策辅助系统

**浅愈（GentleMend）首个正式版本发布！这是一个专为乳腺癌患者设计的副作用智能评估系统，采用规则引擎作为确定性底线，AI 作为增强层的双轨架构，确保医疗决策的安全性和可靠性。**

| 类别 | 详细内容 |
| :--- | :--- |
| **双轨架构** | 规则引擎（44 条 CTCAE 规则）作为确定性底线，AI 增强层提供智能症状提取和结构化解读报告 |
| **智能体闭环** | 完整的感知-决策-执行-学习闭环，支持显式反馈和隐式埋点（5 个事件追踪点） |
| **完全可审计** | 每次评估结果包含完整审计追踪：命中规则、生成时间、版本号、置信度、证据链 |
| **AI 降级策略** | AI API 不可用时自动降级到纯规则引擎模式，确保功能完整可用 |
| **中英双语** | 完整的国际化支持，界面、症状名称、AI 解读报告全部支持中英文 |
| **生产级工程化** | Docker Compose 一键部署、GitHub Actions CI/CD、健康检查、Prometheus 指标收集 |
| **前端三页** | 输入页、结果页、历史页完整实现，响应式设计，支持移动端 |
| **规则自动导入** | 系统启动时自动导入 44 条 CTCAE 规则，无需手动配置 |

## ✨ Rule Engine + AI-Enhanced Medical Decision Support System

**GentleMend's first official release! This is a side effect intelligent assessment system designed for breast cancer patients, adopting a dual-track architecture with rule engine as deterministic baseline and AI as enhancement layer, ensuring safety and reliability of medical decisions.**

| Category | Details |
| :--- | :--- |
| **Dual-Track Architecture** | Rule engine (44 CTCAE rules) as deterministic baseline, AI enhancement layer provides intelligent symptom extraction and structured interpretation reports |
| **Agent Closed-Loop** | Complete perception-decision-execution-learning loop, supports explicit feedback and implicit tracking (5 event tracking points) |
| **Fully Auditable** | Each assessment result includes complete audit trail: matched rules, generation time, version number, confidence level, evidence chain |
| **AI Fallback Strategy** | Automatically falls back to pure rule engine mode when AI API is unavailable, ensuring full functionality |
| **Bilingual Support** | Complete internationalization support, interface, symptom names, AI interpretation reports all support Chinese and English |
| **Production-Grade Engineering** | Docker Compose one-click deployment, GitHub Actions CI/CD, health checks, Prometheus metrics collection |
| **Three-Page Frontend** | Input page, result page, history page fully implemented, responsive design, mobile support |
| **Automatic Rule Import** | Automatically imports 44 CTCAE rules on system startup, no manual configuration needed |
