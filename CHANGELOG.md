# Changelog

## v1.0.0 – Initial Release (2026-04-15)

### Feature 1: Dual-Track Architecture with Rule Engine + AI Enhancement
- **Summary**: Implemented a medical decision support system with CTCAE-based rule engine as deterministic baseline and AI as enhancement layer.
- **Problem Solved**: Breast cancer patients often don't know the severity of side effects or whether medical attention is needed, leading to delayed treatment or excessive anxiety. Traditional systems either rely entirely on rules (lacking flexibility) or entirely on AI (lacking reliability).
- **Feature Details**:
  - Users input symptom descriptions (free text or structured form)
  - System identifies symptoms through 3-level cascade extraction (keyword matching → rule-based NLP → LLM semantic extraction)
  - Rule engine performs risk stratification (low/medium/high) based on 44 CTCAE rules
  - AI enhancement layer provides structured interpretation report (chief complaint summary + concerns + reassurance + personalized advice)
  - High-risk scenarios automatically trigger "contact medical team" recommendation
- **Technical Implementation**:
  - Backend: FastAPI + SQLAlchemy ORM + PostgreSQL/SQLite dual-mode
  - Rule engine: `backend/app/rules/engine.py` implements CTCAE decision table + weighted scoring
  - AI integration: `backend/app/ai/extractor.py` supports DeepSeek/OpenAI compatible API with fallback strategy
  - Perception layer: `backend/app/perception/` implements 3-level cascade symptom extraction
  - Decision layer: `backend/app/decision/` implements risk scoring, conflict resolution, confidence calculation
  - Execution layer: `backend/app/execution/` implements advice generation, priority sorting

### Feature 2: Complete Agent Closed-Loop (Perception-Decision-Execution-Learning)
- **Summary**: Implemented complete agent closed-loop from user input to assessment results to feedback collection.
- **Problem Solved**: Traditional medical assistance systems lack learning capability and cannot continuously optimize based on user feedback.
- **Feature Details**:
  - Perception layer: Receives unstructured descriptions, converts to standardized medical terminology
  - Decision layer: Multi-dimensional reasoning, risk stratification, safety guardrails
  - Execution layer: Generates action recommendations, AI gentle refinement to avoid panic
  - Learning layer: Collects explicit feedback (useful/not useful) + implicit tracking (dwell time, click behavior)
  - 5 event tracking points: page visit, assessment submission, result view, contact team, feedback submission
- **Technical Implementation**:
  - Event tracking: `frontend/src/lib/event-tracker.ts` implements frontend tracking SDK
  - Event storage: `EventLog` model in `backend/app/models/models.py`
  - Feedback collection: `backend/app/api/feedback.py` implements idempotent feedback API
  - Audit trail: `backend/app/observability/audit.py` records complete decision chain

### Feature 3: Bilingual Support (Chinese/English)
- **Summary**: Implemented complete internationalization support, users can seamlessly switch between Chinese and English.
- **Problem Solved**: Medical systems often only support a single language, limiting the user base.
- **Feature Details**:
  - Frontend interface fully bilingual (navigation, forms, result page, history page)
  - Symptom names, severity levels, risk levels all displayed in Chinese
  - AI interpretation reports support Chinese and English output
  - Language switch button in top-right corner of navigation bar
- **Technical Implementation**:
  - i18n framework: `frontend/src/lib/i18n/` uses React Context + JSON translation files
  - Translation files: `zh.json` and `en.json` contain all interface text
  - Language switching: `frontend/src/app/components/Nav.tsx` implements switching logic

### Feature 4: Fully Auditable Assessment Results
- **Summary**: Each assessment result includes complete audit trail information, ensuring traceability of medical decisions.
- **Problem Solved**: The "black box" problem of medical AI systems prevents doctors and patients from trusting their decisions.
- **Feature Details**:
  - Each recommendation is linked to specific CTCAE rules
  - Records matched rules, generation time, version number, confidence level
  - Assessment results are immutable, can only append new versions
  - Complete evidence chain: symptom → rule → risk level → recommendation
- **Technical Implementation**:
  - Audit model: `AuditLog` model in `backend/app/models/models.py`
  - Audit builder: `backend/app/decision/audit_trail.py` generates audit records
  - Evidence model: `Evidence` model records basis for each recommendation
  - Immutability: Database constraints + API layer validation ensure assessment results cannot be modified

### Feature 5: Production-Grade Engineering
- **Summary**: Implemented complete Docker deployment, CI/CD pipeline, monitoring and alerting, and other production-grade features.
- **Problem Solved**: MVP projects often lack engineering support, making deployment and maintenance difficult.
- **Feature Details**:
  - Docker Compose one-click startup (backend + frontend + postgres + redis)
  - GitHub Actions CI/CD pipeline (test + build + deploy)
  - Health check endpoint (`/health`)
  - Prometheus metrics collection (`/metrics`)
  - Structured logging (JSON format)
- **Technical Implementation**:
  - Docker: `backend/Dockerfile` and `frontend/Dockerfile` multi-stage builds
  - Orchestration: `docker-compose.yml` and `docker-compose.dev.yml`
  - CI/CD: `.github/workflows/ci.yml` implements automated testing and deployment
  - Monitoring: `backend/app/monitoring/` implements metrics collection, health checks, alert rules
  - Makefile: `Makefile` provides project management commands (setup, dev, test, clean)

### Feature 6: AI Fallback Strategy
- **Summary**: When AI API is unavailable, system automatically falls back to pure rule engine mode, ensuring full functionality.
- **Problem Solved**: Systems dependent on external AI APIs become completely unavailable when API fails.
- **Feature Details**:
  - When AI API is not configured, uses keyword matching to extract symptoms
  - When AI API call fails, automatically falls back to rule engine
  - After fallback, still provides complete risk assessment and recommendations
  - Seamless switching for users
- **Technical Implementation**:
  - Fallback logic: `extract_symptoms_with_fallback()` in `backend/app/ai/extractor.py`
  - Keyword matching: `backend/app/perception/dictionary.py` maintains symptom keyword dictionary
  - Error handling: Catches API exceptions and logs them without affecting main flow

### Feature 7: Complete Frontend Three-Page Implementation
- **Summary**: Implemented three core pages: input page, result page, and history page, providing complete user experience.
- **Problem Solved**: MVP projects often only have backend APIs, lacking usable frontend interfaces.
- **Feature Details**:
  - Input page (`/`): Symptom description, medication information, medical history input
  - Result page (`/result/[id]`): Risk level, AI interpretation, recommendation list, assessment basis, feedback button
  - History page (`/history`): Assessment history list, pagination, filtering
  - Responsive design, mobile support
- **Technical Implementation**:
  - Next.js 16 App Router: `frontend/src/app/` directory structure
  - Shared components: `frontend/src/app/components/` (Nav, RiskBadge, Footer)
  - API client: `frontend/src/lib/api.ts` encapsulates backend API calls
  - Tailwind CSS v4: Styling system

### Feature 8: Automatic Rule Seed Data Import
- **Summary**: System automatically imports 44 CTCAE rules into database on startup, no manual configuration needed.
- **Problem Solved**: Rule engines depend on large amounts of rule data, manual import is error-prone and inefficient.
- **Feature Details**:
  - Checks if `rule_sources` table is empty on startup
  - If empty, automatically imports 44 CTCAE rules
  - Rules include: symptom name, severity level, risk level, recommendation text, basis description
  - Supports rule versioning and hot updates
- **Technical Implementation**:
  - Seed data: `backend/app/db/seed.py` defines rule data
  - Auto import: `backend/app/main.py` calls `seed_rules()` on startup
  - Rule model: `RuleSource` model in `backend/app/models/models.py`
