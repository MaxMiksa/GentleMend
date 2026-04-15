# 规则引擎详细架构设计

> Round 2.5 — 自建Python规则引擎 + 决策表混合方案的详细设计

---

## 1. 规则定义格式（JSON Schema）

### 1.1 规则JSON结构

每条规则是一个自描述的JSON文档，包含元数据、条件、动作三部分：

```json
{
  "rule_id": "RULE-NAUSEA-G3-001",
  "version": "1.0.0",
  "name": "化疗后重度恶心",
  "description": "CTCAE v5.0 恶心3级：需住院或需肠外营养",
  "category": "gastrointestinal",
  "ctcae_term": "Nausea",
  "ctcae_grade": 3,
  "priority": 900,
  "status": "active",
  "effective_from": "2025-01-01T00:00:00Z",
  "effective_until": null,
  "created_by": "dr-wang",
  "reviewed_by": "dr-zhang",
  "review_date": "2024-12-15T00:00:00Z",
  "evidence_source": "CTCAE v5.0 MedDRA v20.1",

  "conditions": {
    "operator": "AND",
    "items": [
      {
        "field": "symptom_type",
        "op": "eq",
        "value": "nausea"
      },
      {
        "operator": "OR",
        "items": [
          {
            "field": "severity_score",
            "op": "gte",
            "value": 7
          },
          {
            "field": "oral_intake_status",
            "op": "eq",
            "value": "unable_to_eat"
          },
          {
            "field": "hospitalization_needed",
            "op": "eq",
            "value": true
          }
        ]
      }
    ]
  },

  "action": {
    "risk_level": "high",
    "ctcae_grade": 3,
    "recommendation_key": "nausea_grade3_action",
    "urgency": "contact_team_24h",
    "patient_message_template": "您的恶心症状较为严重，建议24小时内联系您的医疗团队。在此期间请尝试少量多次饮水，避免脱水。",
    "clinician_message_template": "患者报告CTCAE 3级恶心，无法正常进食，可能需要肠外营养支持评估。",
    "tags": ["antiemetic_review", "hydration_check", "nutrition_consult"]
  }
}
```

### 1.2 条件表达式语法

条件系统支持嵌套逻辑组合，叶节点为字段比较：

```
条件节点 = 逻辑节点 | 比较节点

逻辑节点:
  operator: "AND" | "OR" | "NOT"
  items: [条件节点, ...]

比较节点:
  field: string        # 输入数据的字段路径，支持点号嵌套如 "vitals.temperature"
  op: string           # 比较操作符
  value: any           # 比较值
```

支持的比较操作符：

| 操作符 | 含义 | 示例 |
|--------|------|------|
| `eq` | 等于 | `{"field": "symptom_type", "op": "eq", "value": "nausea"}` |
| `neq` | 不等于 | `{"field": "status", "op": "neq", "value": "resolved"}` |
| `gt` / `gte` | 大于 / 大于等于 | `{"field": "temperature", "op": "gte", "value": 38.3}` |
| `lt` / `lte` | 小于 / 小于等于 | `{"field": "platelet_count", "op": "lt", "value": 50000}` |
| `in` | 在列表中 | `{"field": "drug_class", "op": "in", "value": ["anthracycline", "taxane"]}` |
| `contains` | 包含子串 | `{"field": "description", "op": "contains", "value": "出血"}` |
| `between` | 区间 | `{"field": "temperature", "op": "between", "value": [37.5, 38.3]}` |
| `exists` | 字段存在 | `{"field": "lab_results.neutrophil", "op": "exists", "value": true}` |

### 1.3 规则JSON Schema（用于校验）

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "GentleMend Rule Definition",
  "type": "object",
  "required": ["rule_id", "version", "name", "category", "priority", "status", "effective_from", "conditions", "action"],
  "properties": {
    "rule_id": {
      "type": "string",
      "pattern": "^RULE-[A-Z]+-G[0-5]-\\d{3}$",
      "description": "格式: RULE-{副作用类型}-G{CTCAE等级}-{序号}"
    },
    "version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$",
      "description": "语义化版本号 major.minor.patch"
    },
    "name": { "type": "string", "maxLength": 100 },
    "description": { "type": "string" },
    "category": {
      "type": "string",
      "enum": ["gastrointestinal", "hematologic", "dermatologic", "neurologic", "cardiac", "respiratory", "musculoskeletal", "endocrine", "hepatic", "renal", "general", "emergency"]
    },
    "ctcae_term": { "type": "string" },
    "ctcae_grade": { "type": "integer", "minimum": 1, "maximum": 5 },
    "priority": {
      "type": "integer", "minimum": 0, "maximum": 1000,
      "description": "越高越优先。安全规则>=900, 指南规则700-899, 专家共识500-699, 经验规则<500"
    },
    "status": { "enum": ["draft", "active", "deprecated", "archived"] },
    "effective_from": { "type": "string", "format": "date-time" },
    "effective_until": { "type": ["string", "null"], "format": "date-time" },
    "conditions": { "$ref": "#/$defs/condition_node" },
    "action": { "$ref": "#/$defs/action" }
  },
  "$defs": {
    "condition_node": {
      "oneOf": [
        { "$ref": "#/$defs/logic_node" },
        { "$ref": "#/$defs/comparison_node" }
      ]
    },
    "logic_node": {
      "type": "object",
      "required": ["operator", "items"],
      "properties": {
        "operator": { "enum": ["AND", "OR", "NOT"] },
        "items": { "type": "array", "items": { "$ref": "#/$defs/condition_node" }, "minItems": 1 }
      }
    },
    "comparison_node": {
      "type": "object",
      "required": ["field", "op", "value"],
      "properties": {
        "field": { "type": "string" },
        "op": { "enum": ["eq", "neq", "gt", "gte", "lt", "lte", "in", "contains", "between", "exists"] },
        "value": {}
      }
    },
    "action": {
      "type": "object",
      "required": ["risk_level", "urgency", "patient_message_template"],
      "properties": {
        "risk_level": { "enum": ["low", "medium", "high"] },
        "ctcae_grade": { "type": "integer", "minimum": 1, "maximum": 5 },
        "recommendation_key": { "type": "string" },
        "urgency": { "enum": ["self_monitor", "contact_team_routine", "contact_team_24h", "emergency_immediate"] },
        "patient_message_template": { "type": "string" },
        "clinician_message_template": { "type": "string" },
        "tags": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

---

## 2. 规则加载、缓存与热更新

### 2.1 规则存储层次

```
PostgreSQL (持久化，规则的 source of truth)
    │
    ▼
RuleStore (应用层缓存，内存中的规则索引)
    │
    ▼
RuleEngine (执行时从 RuleStore 读取)
```

### 2.2 加载流程

1. 应用启动时，`RuleStore.load_all()` 从数据库加载所有 `status=active` 且在有效期内的规则
2. 按 `category` 建立索引（`dict[str, list[Rule]]`），按 `priority` 降序排列
3. 构建 `rule_id -> Rule` 的快速查找映射
4. 记录加载时间戳和规则集hash（用于一致性校验）

### 2.3 缓存与热更新

```python
class RuleStore:
    """规则缓存，支持热更新。使用 copy-on-write 保证评估一致性。"""

    def __init__(self):
        self._rules_by_id: dict[str, Rule] = {}
        self._rules_by_category: dict[str, list[Rule]] = {}
        self._version_hash: str = ""
        self._loaded_at: datetime | None = None
        self._lock = threading.RLock()

    def snapshot(self) -> RuleSnapshot:
        """评估开始时获取不可变快照，后续热更新不影响进行中的评估"""
        with self._lock:
            return RuleSnapshot(
                rules=dict(self._rules_by_id),
                version_hash=self._version_hash,
                timestamp=self._loaded_at,
            )

    async def hot_reload(self, changed_rule_ids: list[str] | None = None):
        """热更新：增量或全量，不中断正在执行的评估"""
        with self._lock:
            if changed_rule_ids:
                new_rules = await self._repo.get_rules_by_ids(changed_rule_ids)
                for rule in new_rules:
                    self._rules_by_id[rule.rule_id] = rule
            else:
                all_rules = await self._repo.get_all_active_rules()
                self._rules_by_id = {r.rule_id: r for r in all_rules}
            self._rebuild_indexes()
            self._loaded_at = datetime.now(UTC)
```

热更新触发方式：
- **轮询**：后台线程每60秒查 `rules_changelog` 表���有变更则增量加载
- **主动通知**：管理API `POST /admin/rules/reload` 即时重载

---

## 3. 规则匹配算法与执行流程

### 3.1 条件求值器

递归求值条件树，支持短路计算：

```python
class ConditionEvaluator:
    """条件表达式求值器"""

    def evaluate(self, condition: dict, facts: dict) -> bool:
        if "operator" in condition:
            return self._eval_logic(condition, facts)
        return self._eval_comparison(condition, facts)

    def _eval_logic(self, node: dict, facts: dict) -> bool:
        op = node["operator"]
        items = node["items"]
        if op == "AND":
            return all(self.evaluate(item, facts) for item in items)
        elif op == "OR":
            return any(self.evaluate(item, facts) for item in items)
        elif op == "NOT":
            return not self.evaluate(items[0], facts)
        raise ValueError(f"Unknown operator: {op}")

    def _eval_comparison(self, node: dict, facts: dict) -> bool:
        field_value = self._resolve_field(node["field"], facts)
        op = node["op"]
        expected = node["value"]

        if op == "eq":    return field_value == expected
        if op == "neq":   return field_value != expected
        if op == "gt":    return field_value > expected
        if op == "gte":   return field_value >= expected
        if op == "lt":    return field_value < expected
        if op == "lte":   return field_value <= expected
        if op == "in":    return field_value in expected
        if op == "contains": return expected in str(field_value)
        if op == "between":  return expected[0] <= field_value <= expected[1]
        if op == "exists":   return (field_value is not None) == expected
        raise ValueError(f"Unknown op: {op}")

    def _resolve_field(self, field_path: str, facts: dict) -> Any:
        """支持点号路径解析，如 'vitals.temperature'"""
        parts = field_path.split(".")
        current = facts
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
```

### 3.2 规则执行流程

```
输入: SymptomFacts (LLM结构化输出 或 表单结构化数据)
  │
  ▼
┌─────────────────────────────────┐
│ 1. 获取规则快照 (RuleSnapshot)   │
│    保证本次评估规则集一致性       │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 2. 预筛选                       │
│    按 category 过滤相关规则      │
│    排除过期/未生效规则           │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 3. 逐条求值                     │
│    按 priority 降序遍历          │
│    ConditionEvaluator.evaluate() │
│    记录每条规则的匹配结果        │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 4. 收集所有命中规则              │
│    matched_rules: list[RuleHit] │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 5. 冲突解决                     │
│    取最高 risk_level             │
│    同级别取最高 priority         │
│    合并所有 tags 和建议          │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 6. 生成 EvaluationResult        │
│    包含: 最终风险等级、命中规则链 │
│    建议列表、审计元数据          │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│ 7. 持久化                       │
│    写入 assessment + evidence    │
│    写入 audit_log               │
└─────────────────────────────────┘
```

### 3.3 冲突解决策略

多条规则同时命中时的合并逻辑：

```python
RISK_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}
URGENCY_ORDER = {
    "self_monitor": 0,
    "contact_team_routine": 1,
    "contact_team_24h": 2,
    "emergency_immediate": 3,
}

def resolve_conflicts(matched_rules: list[RuleHit]) -> EvaluationResult:
    """
    冲突解决原则：
    1. risk_level: 取最高（安全优先）
    2. urgency: 取最紧急
    3. 建议: 合并去重，按priority排序
    4. 主规则: 同风险等级中priority最高的作为primary_rule
    """
    if not matched_rules:
        return EvaluationResult(risk_level="low", urgency="self_monitor", ...)

    final_risk = max(matched_rules, key=lambda r: RISK_LEVEL_ORDER[r.risk_level])
    final_urgency = max(matched_rules, key=lambda r: URGENCY_ORDER[r.urgency])
    primary_rule = max(matched_rules, key=lambda r: (RISK_LEVEL_ORDER[r.risk_level], r.priority))

    all_tags = list(dict.fromkeys(tag for r in matched_rules for tag in r.tags))

    return EvaluationResult(
        risk_level=final_risk.risk_level,
        urgency=final_urgency.urgency,
        primary_rule_id=primary_rule.rule_id,
        matched_rules=[r.to_evidence() for r in matched_rules],
        merged_tags=all_tags,
    )
```

---

## 4. 决策表设计

### 4.1 CTCAE分级决策表结构

决策表是规则的表格化表达，每行是一条规则，列分为条件列和动作列。适合CTCAE这种"症状×等级→处置"的映射关系。

```python
@dataclass
class DecisionTableRow:
    """决策表的一行，等价于一条规则"""
    rule_id: str
    symptom_type: str           # CTCAE术语
    grade: int                  # CTCAE等级 1-4
    condition_fields: dict      # 额外条件字段（频率、持续时间等）
    risk_level: str             # low / medium / high
    urgency: str                # 处置紧急度
    patient_message: str        # 患者端提示
    clinician_summary: str      # 医生端摘要

@dataclass
class DecisionTable:
    """决策表，按副作用类别组织"""
    table_id: str
    name: str
    category: str
    version: str
    rows: list[DecisionTableRow]
```

决策表在内部会被转换为标准 `Rule` 对象加载到 `RuleStore`，统一执行路径。

### 4.2 乳腺癌常见副作用决策表（20种）

以下覆盖化疗、放疗、靶向治疗、内分泌治疗四大类的常见副作用：

#### 表1：消化系统副作用

| rule_id | 症状 | CTCAE等级 | 条件 | 风险 | 紧急度 | 患者建议 |
|---------|------|-----------|------|------|--------|---------|
| RULE-NAUSEA-G1-001 | 恶心 | 1 | 不影响进食 | low | self_monitor | 少量多餐，避免油腻食物，必要时含姜片 |
| RULE-NAUSEA-G2-001 | 恶心 | 2 | 进食减少但未脱水 | medium | contact_team_routine | 建议联系团队评估是否需要调整止吐方案 |
| RULE-NAUSEA-G3-001 | 恶心 | 3 | 无法进食/需住院 | high | contact_team_24h | 请24小时内联系医疗团队，注意少量饮水防脱水 |
| RULE-VOMIT-G2-001 | 呕吐 | 2 | 24h内2-5次 | medium | contact_team_routine | 记录呕吐次数，联系团队评估止吐药调整 |
| RULE-VOMIT-G3-001 | 呕吐 | 3 | 24h内≥6次/需住院 | high | contact_team_24h | 严重呕吐可致脱水，请尽快联系医疗团队 |
| RULE-DIARR-G2-001 | 腹泻 | 2 | 4-6次/天 | medium | contact_team_routine | 注意补充水分和电解质，联系团队评估 |
| RULE-DIARR-G3-001 | 腹泻 | 3 | ≥7次/天或需住院 | high | contact_team_24h | 严重腹泻有脱水风险，请24小时内联系团队 |
| RULE-MUCOSI-G2-001 | 口腔黏膜炎 | 2 | 影响进食但可吃软食 | medium | contact_team_routine | 使用温和漱口水，避免辛辣食物，联系团队 |

#### 表2：血液系统副作用

| rule_id | 症状 | CTCAE等级 | 条件 | 风险 | 紧急度 | 患者建议 |
|---------|------|-----------|------|------|--------|---------|
| RULE-NEUTRO-G3-001 | 中性粒细胞减少 | 3 | ANC 500-1000/mm³ | high | contact_team_24h | 避免人群密集场所，出现发热立即就医 |
| RULE-NEUTRO-G4-001 | 中性粒细胞减少 | 4 | ANC<500/mm³ | high | emergency_immediate | 严重粒细胞减少，请立即联系医疗团队 |
| RULE-FN-G4-001 | 粒缺性发热 | 4 | ANC<1000且T≥38.3°C | high | emergency_immediate | 这是医疗紧急情况，请立即前往急诊 |
| RULE-ANEMIA-G2-001 | 贫血 | 2 | Hb 8-10g/dL | medium | contact_team_routine | 注意休息，避免剧烈活动，联系团队复查血常规 |
| RULE-THROM-G3-001 | 血小板减少 | 3 | PLT 25000-50000 | high | contact_team_24h | 避免碰撞和受伤，出现出血立即就医 |

#### 表3：皮肤与神经系统副作用

| rule_id | 症状 | CTCAE等级 | 条件 | 风险 | 紧急度 | 患者建议 |
|---------|------|-----------|------|------|--------|---------|
| RULE-RASH-G1-001 | 皮疹 | 1 | 覆盖<10%体表面积 | low | self_monitor | 保持皮肤清洁湿润，避免日晒，观察变化 |
| RULE-RASH-G2-001 | 皮疹 | 2 | 10-30%体表或伴瘙痒 | medium | contact_team_routine | 联系团队评估是否需要外用药物 |
| RULE-RASH-G3-001 | 皮疹 | 3 | >30%体表或伴水疱 | high | contact_team_24h | 皮疹范围较大或出现水疱，请尽快联系团队 |
| RULE-HFS-G2-001 | 手足综合征 | 2 | 疼痛性皮肤改变影响ADL | medium | contact_team_routine | 使用保湿霜，避免热水，联系团队评估是否需调整剂量 |
| RULE-NEURO-G2-001 | 周围神经病变 | 2 | 中度症状影响工具性ADL | medium | contact_team_routine | 注意手脚保暖，避免接触冷物，联系团队评估 |
| RULE-NEURO-G3-001 | 周围神经病变 | 3 | 重度症状影响自理ADL | high | contact_team_24h | 神经症状明显加重，请联系团队评估是否需调整方案 |

#### 表4：心脏与其他系统副作用

| rule_id | 症状 | CTCAE等级 | 条件 | 风险 | 紧急度 | 患者建议 |
|---------|------|-----------|------|------|--------|---------|
| RULE-CARDIAC-G3-001 | 心脏毒性 | 3 | LVEF下降或心衰症状 | high | emergency_immediate | 出现胸闷气短请立即就医，这可能与药物心脏毒性有关 |
| RULE-FATIGUE-G1-001 | 疲劳 | 1 | 轻度疲劳不影响ADL | low | self_monitor | 适当休息，保持轻度活动，均衡饮食 |
| RULE-FATIGUE-G2-001 | 疲劳 | 2 | 影响工具性ADL | medium | contact_team_routine | 合理安排活动和休息，联系团队排除贫血等原因 |
| RULE-ARTHRAL-G2-001 | 关节痛(AI相关) | 2 | 中度疼痛影响ADL | medium | contact_team_routine | 适当活动，联系团队评估是否需要止痛药调整 |
| RULE-HOTFLASH-G1-001 | 潮热 | 1 | 轻度不影响ADL | low | self_monitor | 穿透气衣物，避免辛辣食物和热饮，保持凉爽环境 |

### 4.3 高风险紧急规则（红色警报）

这些规则 `priority >= 950`，无论其他规则结果如何，一旦命中立即触发最高警报：

```json
[
  {
    "rule_id": "RULE-EMERG-FEVER-001",
    "version": "1.0.0",
    "name": "化疗期间高热（粒缺性发热筛查）",
    "priority": 980,
    "conditions": {
      "operator": "AND",
      "items": [
        {"field": "temperature", "op": "gte", "value": 38.3},
        {"field": "treatment_phase", "op": "in", "value": ["active_chemo", "post_chemo_14d"]}
      ]
    },
    "action": {
      "risk_level": "high",
      "urgency": "emergency_immediate",
      "patient_message_template": "化疗期间体温≥38.3°C是医疗紧急情况（可能为粒缺性发热），请立即前往最近的急诊科。不要等待，不要自行服用退烧药后观察。",
      "clinician_message_template": "患者化疗期间报告T≥38.3°C，疑似粒缺性发热，需紧急血常规+血培养。"
    }
  },
  {
    "rule_id": "RULE-EMERG-DYSPNEA-001",
    "version": "1.0.0",
    "name": "严重呼吸困难",
    "priority": 990,
    "conditions": {
      "operator": "OR",
      "items": [
        {"field": "dyspnea_severity", "op": "eq", "value": "at_rest"},
        {"field": "oxygen_needed", "op": "eq", "value": true},
        {"field": "symptom_type", "op": "eq", "value": "chest_pain"}
      ]
    },
    "action": {
      "risk_level": "high",
      "urgency": "emergency_immediate",
      "patient_message_template": "严重呼吸困难或胸痛需要立即就医。请拨打120或前往最近的急诊科。",
      "clinician_message_template": "患者报告静息状态呼吸困难/胸痛，需排除肺栓塞、心包积液、放射性肺炎。"
    }
  },
  {
    "rule_id": "RULE-EMERG-ALLERGY-001",
    "version": "1.0.0",
    "name": "严重过敏反应",
    "priority": 995,
    "conditions": {
      "operator": "OR",
      "items": [
        {"field": "facial_swelling", "op": "eq", "value": true},
        {"field": "throat_tightness", "op": "eq", "value": true},
        {"field": "anaphylaxis_signs", "op": "eq", "value": true}
      ]
    },
    "action": {
      "risk_level": "high",
      "urgency": "emergency_immediate",
      "patient_message_template": "面部肿胀或喉咙发紧可能是严重过敏反应，请立即拨打120。",
      "clinician_message_template": "患者报告疑似过敏反应体征，需紧急评估是否为药物相关过敏反应。"
    }
  },
  {
    "rule_id": "RULE-EMERG-BLEEDING-001",
    "version": "1.0.0",
    "name": "严重出血",
    "priority": 985,
    "conditions": {
      "operator": "OR",
      "items": [
        {"field": "bleeding_severity", "op": "eq", "value": "severe"},
        {"field": "bloody_stool", "op": "eq", "value": true},
        {"field": "consciousness_change", "op": "eq", "value": true}
      ]
    },
    "action": {
      "risk_level": "high",
      "urgency": "emergency_immediate",
      "patient_message_template": "严重出血或意识改变是紧急情况，请立即拨打120或前往急诊。",
      "clinician_message_template": "患者报告严重出血/意识改变，需紧急评估，注意血小板减少可能。"
    }
  },
  {
    "rule_id": "RULE-EMERG-DVT-001",
    "version": "1.0.0",
    "name": "疑似深静脉血栓",
    "priority": 960,
    "conditions": {
      "operator": "AND",
      "items": [
        {"field": "limb_swelling", "op": "eq", "value": true},
        {"field": "limb_pain", "op": "eq", "value": true},
        {"field": "unilateral", "op": "eq", "value": true}
      ]
    },
    "action": {
      "risk_level": "high",
      "urgency": "contact_team_24h",
      "patient_message_template": "单侧肢体肿胀伴疼痛可能提示血栓，请24小时内联系医疗团队安排检查。避免按摩患肢。",
      "clinician_message_template": "患者报告单侧肢体肿胀+疼痛，需排除DVT，建议安排下肢血管超声。"
    }
  }
]
```

### 4.4 药物-副作用关联规则

药物关联规则用于在已知患者用药方案时，提升特定副作用的关注度：

```json
{
  "drug_side_effect_associations": [
    {
      "drug_class": "anthracycline",
      "drugs": ["多柔比星", "表柔比星"],
      "heightened_risks": [
        {"symptom": "cardiac_toxicity", "note": "累积剂量相关，多柔比星>450mg/m²需警惕"},
        {"symptom": "nausea", "note": "高致吐风险，需三联止吐预防"}
      ],
      "priority_boost": 50
    },
    {
      "drug_class": "taxane",
      "drugs": ["紫杉醇", "多西他赛"],
      "heightened_risks": [
        {"symptom": "peripheral_neuropathy", "note": "剂量累积性，紫杉醇更常见"},
        {"symptom": "allergic_reaction", "note": "首次输注过敏风险高，需预处理"},
        {"symptom": "neutropenia", "note": "多西他赛粒缺风险更高"}
      ],
      "priority_boost": 50
    },
    {
      "drug_class": "trastuzumab",
      "drugs": ["曲妥珠单抗", "帕妥珠单抗"],
      "heightened_risks": [
        {"symptom": "cardiac_toxicity", "note": "需定期监测LVEF，与蒽环类合用风险叠加"},
        {"symptom": "infusion_reaction", "note": "首次输注反应常见"}
      ],
      "priority_boost": 80
    },
    {
      "drug_class": "cdk4_6_inhibitor",
      "drugs": ["哌柏西利", "阿贝西利", "瑞波西利"],
      "heightened_risks": [
        {"symptom": "neutropenia", "note": "哌柏西利粒缺发生率>80%，需定期血常规"},
        {"symptom": "diarrhea", "note": "阿贝西利腹泻发生率高"}
      ],
      "priority_boost": 50
    },
    {
      "drug_class": "aromatase_inhibitor",
      "drugs": ["来曲唑", "阿那曲唑", "依西美坦"],
      "heightened_risks": [
        {"symptom": "arthralgia", "note": "关节痛发生率30-50%，是停药主要原因"},
        {"symptom": "osteoporosis", "note": "需定期骨密度监测"},
        {"symptom": "hot_flash", "note": "常见，通常可耐受"}
      ],
      "priority_boost": 30
    },
    {
      "drug_class": "tamoxifen",
      "drugs": ["他莫昔芬"],
      "heightened_risks": [
        {"symptom": "thromboembolism", "note": "血栓风险增加2-3倍"},
        {"symptom": "hot_flash", "note": "最常见副作用"},
        {"symptom": "endometrial_change", "note": "子宫内膜增厚/癌变风险，需定期妇科检查"}
      ],
      "priority_boost": 40
    }
  ]
}
```

药物关联的作用：当患者用药方案中包含某类药物时，该药物关联的副作用规则 `priority` 自动上浮 `priority_boost` 点，使其在冲突解决时获得更高权重，同时在输出中附加药物特异性提示。

---

## 5. 规则版本化机制

### 5.1 版本号格式

采用语义化版本 `MAJOR.MINOR.PATCH`，含义针对医疗规则场景定制：

| 版本段 | 变更类型 | 示例 |
|--------|---------|------|
| MAJOR | 风险等级或紧急度变更（影响临床决策） | 恶心G2从low改为medium → 2.0.0 |
| MINOR | 条件逻辑调整或新增条件分支 | 增加"伴脱水"子条件 → 1.1.0 |
| PATCH | 文案修改、标签调整等非逻辑变更 | 修改患者提示措辞 → 1.0.1 |

每条规则独立版本号，规则集整体也有一个聚合版本号（所有规则版本的hash）。

### 5.2 版本切换流程

```
1. 规则编辑（draft状态）
   │
   ▼
2. 医学审核（reviewed_by 签名）
   │
   ▼
3. 发布为新版本
   ├── 旧版本 status → "deprecated"
   ├── 新版本 status → "active", effective_from = 指定时间
   └── 写入 rules_changelog
   │
   ▼
4. 热更新生效
   ├── 轮询检测到 changelog 变更
   └── 或管理员手动触发 reload
   │
   ▼
5. 验证
   └── 新版本规则参与后续评估，旧版本不再命中
```

关键约束：
- 同一 `rule_id` 同一时刻只有一个 `active` 版本
- 版本切换是原子操作（数据库事务）
- 支持定时生效：`effective_from` 设为未来时间，到时自动切换

### 5.3 历史版本保留策略

```sql
-- 规则版本表，永不删除，只追加
CREATE TABLE rule_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id         VARCHAR(50) NOT NULL,
    version         VARCHAR(20) NOT NULL,
    status          VARCHAR(20) NOT NULL,  -- draft/active/deprecated/archived
    definition      JSONB NOT NULL,        -- 完整规则JSON
    content_hash    VARCHAR(64) NOT NULL,  -- SHA-256 of definition
    effective_from  TIMESTAMPTZ,
    effective_until TIMESTAMPTZ,
    created_by      VARCHAR(100) NOT NULL,
    reviewed_by     VARCHAR(100),
    review_date     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(rule_id, version)
);

-- 规则变更日志，审计用
CREATE TABLE rules_changelog (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_id         VARCHAR(50) NOT NULL,
    old_version     VARCHAR(20),
    new_version     VARCHAR(20) NOT NULL,
    change_type     VARCHAR(20) NOT NULL,  -- created/updated/deprecated/activated
    change_summary  TEXT,
    changed_by      VARCHAR(100) NOT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    old_content_hash VARCHAR(64),
    new_content_hash VARCHAR(64) NOT NULL
);
```

保留策略：
- `active`：当前生效版本，有且仅有一个
- `deprecated`：被新版本替代，保留用于历史评估追溯
- `archived`：超过2年的deprecated版本，可迁移到冷存储
- 永不物理删除：任何历史评估引用的规则版本必须可查

### 5.4 规则变更审计

每次规则变更记录完整的审计链：

```python
@dataclass
class RuleChangeAudit:
    rule_id: str
    old_version: str | None      # 新建时为None
    new_version: str
    change_type: ChangeType      # created / updated / deprecated / activated
    change_summary: str           # 人工填写的变更说明
    changed_by: str               # 操作人
    changed_at: datetime
    diff: dict | None             # 新旧版本的JSON diff（仅updated时）
    review_status: str            # pending / approved / rejected
    reviewer: str | None
    review_comment: str | None
```

审计查询接口：
- `GET /admin/rules/{rule_id}/history` — 查看某规则的完整版本历史
- `GET /admin/rules/changelog?since=2025-01-01` — 查看时间段内所有规则变更
- `GET /admin/assessments/{id}/rule-snapshot` — 查看某次评估使用的规则版本快照

---

## 6. 规则引擎与AI的协作接口

### 6.1 LLM输出 → 规则引擎输入的映射

LLM负责将患者自然语言描述结构化为规则引擎可消费的 `SymptomFacts`：

```python
class SymptomFacts(BaseModel):
    """LLM结构化输出 → 规则引擎输入"""

    # 基本症状信息
    symptoms: list[SymptomItem]
    # 生命体征（患者自报或设备数据）
    vitals: VitalSigns | None = None
    # 用药信息（用于药物关联规则）
    current_medications: list[MedicationInfo] = []
    # 治疗阶段
    treatment_phase: str | None = None  # active_chemo / post_chemo_14d / radiation / endocrine / ...
    # LLM置信度
    extraction_confidence: float  # 0.0-1.0

class SymptomItem(BaseModel):
    symptom_type: str           # 标准化症状代码，映射到CTCAE��语
    severity_score: int         # 1-10 患者自评严重度
    frequency: str | None       # once / intermittent / constant
    duration_days: int | None   # 持续天数
    description: str            # 原始描述片段
    associated_factors: dict    # 症状特异性字段，如 oral_intake_status, bleeding_severity 等

class VitalSigns(BaseModel):
    temperature: float | None = None
    heart_rate: int | None = None
    blood_pressure_systolic: int | None = None
    blood_pressure_diastolic: int | None = None
    oxygen_saturation: float | None = None
```

LLM通过 Anthropic Tool Use 强制输出此结构：

```python
# Prompt中的tool定义（简化）
tools = [{
    "name": "extract_symptoms",
    "description": "从患者描述中提取结构化症状信息",
    "input_schema": SymptomFacts.model_json_schema()
}]
```

### 6.2 规则引擎输出 → LLM解释增强

规则引擎输出 `EvaluationResult`，传递给LLM做自然语言解释：

```python
class EvaluationResult(BaseModel):
    """规则引擎输出，同时作为LLM解释增强的输入"""

    assessment_id: str
    risk_level: RiskLevel                    # low / medium / high
    urgency: Urgency                         # self_monitor / contact_team_routine / contact_team_24h / emergency_immediate
    primary_rule: RuleEvidence               # 主要命中规则
    all_matched_rules: list[RuleEvidence]    # 所有命中规则
    merged_tags: list[str]                   # 合并后的标签
    drug_specific_notes: list[str]           # 药物特异性提示
    rule_engine_version: str                 # 引擎版本
    rules_snapshot_hash: str                 # 规则集快照hash
    evaluated_at: datetime

class RuleEvidence(BaseModel):
    rule_id: str
    rule_version: str
    rule_name: str
    ctcae_term: str | None
    ctcae_grade: int | None
    evidence_source: str                     # 如 "CTCAE v5.0 MedDRA v20.1"
    patient_message_template: str
    clinician_message_template: str
```

LLM解释增强的Prompt模板：

```
你是一个医疗信息助手。根据以下规则引擎评估结果，为患者生成通俗易懂的解释。

## 硬性约束
- 不能修改风险等级和紧急度判断（这些由规则引擎确定）
- 不能做诊断或开处方
- 必须包含规则引擎给出的核心建议
- 语言温和、不制造恐慌，但高风险时必须传达紧迫性

## 规则引擎评估结果
风险等级: {risk_level}
紧急度: {urgency}
命中规则: {matched_rules_summary}
核心建议: {patient_message_template}
药物提示: {drug_specific_notes}

请生成：
1. 患者版解释（简洁通俗，200字以内）
2. 下一步行动建议（具体可执行）
```

### 6.3 降级策略：AI不可用时规则引擎独立工作

```
正常模式:
  患者输入 → [LLM结构化] → [规则引擎] → [LLM解释] → 输出

降级模式1 (LLM结构化不可用):
  患者输入 → [表单结构化数据直接使用] → [规则引擎] → [模板化输出]

降级模式2 (LLM解释不可用):
  患者输入 → [LLM结构化] → [规则引擎] → [模板化输出，不做个性化解释]

降级模式3 (LLM完全不可用):
  患者输入 → [仅表单结构化] → [规则引擎] → [模板化输出]
```

```python
class DegradationManager:
    """降级管理器"""

    async def evaluate_with_fallback(
        self, patient_input: PatientInput
    ) -> AssessmentOutput:
        # 尝试LLM结构化
        facts = await self._try_llm_extraction(patient_input)
        if facts is None:
            # 降级：使用表单结构化数据
            facts = self._build_facts_from_form(patient_input.form_data)
            facts.extraction_confidence = 1.0  # 表单数据是确定的

        # 规则引擎评估（核心，永不降级）
        result = self._rule_engine.evaluate(facts)

        # 尝试LLM解释增强
        explanation = await self._try_llm_explanation(result)
        if explanation is None:
            # 降级：使用规则模板
            explanation = self._build_template_explanation(result)

        return AssessmentOutput(
            evaluation=result,
            explanation=explanation,
            degraded=facts.extraction_confidence < 0.5 or explanation.is_template,
        )
```

核心原则：规则引擎是系统的确定性底线，永远可用。LLM是增强层，不可用时优雅降级到模板化输出，不影响风险评估的准确性。

---

## 7. Python核心类设计

### 7.1 Protocol接口定义

```python
from typing import Protocol, runtime_checkable
from datetime import datetime

@runtime_checkable
class RuleRepository(Protocol):
    """规则持久化层接口"""
    async def get_all_active_rules(self) -> list["Rule"]: ...
    async def get_rules_by_ids(self, rule_ids: list[str]) -> list["Rule"]: ...
    async def get_rule_version(self, rule_id: str, version: str) -> "Rule | None": ...
    async def save_rule_version(self, rule: "Rule") -> None: ...
    async def get_changelog_since(self, since: datetime) -> list["RuleChangeRecord"]: ...

@runtime_checkable
class AuditLogger(Protocol):
    """审计日志接口"""
    async def log_evaluation(self, audit: "EvaluationAudit") -> None: ...
    async def log_rule_change(self, change: "RuleChangeAudit") -> None: ...

@runtime_checkable
class SymptomExtractor(Protocol):
    """症状提取接口（LLM实现或表单实现）"""
    async def extract(self, patient_input: "PatientInput") -> "SymptomFacts": ...

@runtime_checkable
class ExplanationGenerator(Protocol):
    """解释生成接口（LLM实现或模板实现）"""
    async def generate(
        self, result: "EvaluationResult", patient_input: "PatientInput"
    ) -> "Explanation": ...
```

### 7.2 核心数据模型

```python
from dataclasses import dataclass, field
from enum import StrEnum
from pydantic import BaseModel

class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class Urgency(StrEnum):
    SELF_MONITOR = "self_monitor"
    CONTACT_TEAM_ROUTINE = "contact_team_routine"
    CONTACT_TEAM_24H = "contact_team_24h"
    EMERGENCY_IMMEDIATE = "emergency_immediate"

class RuleStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
```

### 7.3 Rule 类

```python
@dataclass(frozen=True)
class Rule:
    """不可变规则对象"""
    rule_id: str
    version: str
    name: str
    description: str
    category: str
    ctcae_term: str | None
    ctcae_grade: int | None
    priority: int
    status: RuleStatus
    effective_from: datetime
    effective_until: datetime | None
    conditions: dict                    # 条件树JSON
    action: RuleAction
    evidence_source: str | None
    created_by: str
    reviewed_by: str | None
    content_hash: str                   # SHA-256

    def is_active(self, at: datetime | None = None) -> bool:
        """检查规则在指定时间是否生效"""
        at = at or datetime.now(UTC)
        if self.status != RuleStatus.ACTIVE:
            return False
        if at < self.effective_from:
            return False
        if self.effective_until and at > self.effective_until:
            return False
        return True

@dataclass(frozen=True)
class RuleAction:
    risk_level: RiskLevel
    urgency: Urgency
    recommendation_key: str | None
    patient_message_template: str
    clinician_message_template: str
    tags: tuple[str, ...] = ()
```

### 7.4 RuleEngine 类

```python
class RuleEngine:
    """规则引擎核心，无状态，线程安全"""

    def __init__(
        self,
        rule_store: "RuleStore",
        evaluator: "ConditionEvaluator",
        audit_logger: AuditLogger,
        drug_associations: "DrugAssociationTable | None" = None,
    ):
        self._store = rule_store
        self._evaluator = evaluator
        self._audit = audit_logger
        self._drug_assoc = drug_associations

    async def evaluate(self, facts: "SymptomFacts") -> "EvaluationResult":
        """
        核心评估方法。
        1. 获取规则快照
        2. 应用药物关联优先级提升
        3. 逐条匹配
        4. 冲突解决
        5. 记录审计
        """
        snapshot = self._store.snapshot()
        candidate_rules = self._select_candidates(snapshot, facts)

        if self._drug_assoc and facts.current_medications:
            candidate_rules = self._apply_drug_boost(candidate_rules, facts)

        matched: list[RuleHit] = []
        for rule in candidate_rules:
            try:
                if self._evaluator.evaluate(rule.conditions, facts.to_facts_dict()):
                    matched.append(RuleHit.from_rule(rule))
            except Exception as e:
                logger.warning("rule_eval_error", rule_id=rule.rule_id, error=str(e))

        result = resolve_conflicts(matched)
        result.rules_snapshot_hash = snapshot.version_hash
        result.evaluated_at = datetime.now(UTC)

        await self._audit.log_evaluation(result.to_audit())
        return result

    def _select_candidates(
        self, snapshot: "RuleSnapshot", facts: "SymptomFacts"
    ) -> list[Rule]:
        """预筛选：按症状类别选取相关规则 + 紧急规则（始终参与）"""
        categories = {s.symptom_type_to_category() for s in facts.symptoms}
        categories.add("emergency")  # 紧急规则始终参与
        rules = []
        for cat in categories:
            rules.extend(snapshot.get_rules_by_category(cat))
        return sorted(rules, key=lambda r: r.priority, reverse=True)
```

### 7.5 DecisionTable 类

```python
class DecisionTable:
    """决策表：CTCAE分级表的程序化表达"""

    def __init__(self, table_id: str, name: str, version: str):
        self.table_id = table_id
        self.name = name
        self.version = version
        self._rows: list[DecisionTableRow] = []

    def add_row(self, row: "DecisionTableRow") -> None:
        self._rows.append(row)

    def to_rules(self) -> list[Rule]:
        """将决策表行转换为标准Rule对象，统一执行路径"""
        return [self._row_to_rule(row) for row in self._rows]

    def _row_to_rule(self, row: "DecisionTableRow") -> Rule:
        conditions = self._build_conditions(row)
        return Rule(
            rule_id=row.rule_id,
            version=self.version,
            name=f"{row.symptom_type} Grade {row.grade}",
            description=f"Decision table: {self.name}",
            category=row.category,
            ctcae_term=row.symptom_type,
            ctcae_grade=row.grade,
            priority=self._grade_to_priority(row.grade),
            status=RuleStatus.ACTIVE,
            effective_from=datetime.now(UTC),
            effective_until=None,
            conditions=conditions,
            action=RuleAction(
                risk_level=RiskLevel(row.risk_level),
                urgency=Urgency(row.urgency),
                recommendation_key=None,
                patient_message_template=row.patient_message,
                clinician_message_template=row.clinician_summary,
            ),
            evidence_source="CTCAE v5.0",
            created_by="system",
            reviewed_by=None,
            content_hash="",
        )

    @staticmethod
    def _grade_to_priority(grade: int) -> int:
        """CTCAE等级映射到优先级"""
        return {1: 100, 2: 300, 3: 600, 4: 900, 5: 1000}.get(grade, 100)
```

### 7.6 RuleStore 类（完整版）

```python
class RuleStore:
    """规则缓存与索引，支持热更新"""

    def __init__(self, repo: RuleRepository):
        self._repo = repo
        self._rules_by_id: dict[str, Rule] = {}
        self._rules_by_category: dict[str, list[Rule]] = {}
        self._version_hash: str = ""
        self._loaded_at: datetime | None = None
        self._lock = threading.RLock()

    async def load_all(self) -> None:
        """启动时全量加载"""
        rules = await self._repo.get_all_active_rules()
        with self._lock:
            self._rules_by_id = {r.rule_id: r for r in rules}
            self._rebuild_indexes()
            self._version_hash = self._compute_hash()
            self._loaded_at = datetime.now(UTC)
        logger.info("rule_store_loaded", count=len(rules), hash=self._version_hash)

    def snapshot(self) -> "RuleSnapshot":
        """获取当前规则集的不可变快照"""
        with self._lock:
            return RuleSnapshot(
                rules_by_id=dict(self._rules_by_id),
                rules_by_category={k: list(v) for k, v in self._rules_by_category.items()},
                version_hash=self._version_hash,
                timestamp=self._loaded_at,
            )

    async def hot_reload(self, changed_rule_ids: list[str] | None = None) -> int:
        """热更新，返回更新的规则数量"""
        with self._lock:
            if changed_rule_ids:
                new_rules = await self._repo.get_rules_by_ids(changed_rule_ids)
                for rule in new_rules:
                    if rule.status == RuleStatus.ACTIVE:
                        self._rules_by_id[rule.rule_id] = rule
                    elif rule.rule_id in self._rules_by_id:
                        del self._rules_by_id[rule.rule_id]
                count = len(new_rules)
            else:
                all_rules = await self._repo.get_all_active_rules()
                self._rules_by_id = {r.rule_id: r for r in all_rules}
                count = len(all_rules)
            self._rebuild_indexes()
            self._version_hash = self._compute_hash()
            self._loaded_at = datetime.now(UTC)
            return count

    def _rebuild_indexes(self) -> None:
        by_cat: dict[str, list[Rule]] = {}
        for rule in self._rules_by_id.values():
            by_cat.setdefault(rule.category, []).append(rule)
        for rules in by_cat.values():
            rules.sort(key=lambda r: r.priority, reverse=True)
        self._rules_by_category = by_cat

    def _compute_hash(self) -> str:
        content = "|".join(
            f"{r.rule_id}:{r.version}:{r.content_hash}"
            for r in sorted(self._rules_by_id.values(), key=lambda r: r.rule_id)
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]
```

### 7.7 RuleSnapshot（不可变快照）

```python
@dataclass(frozen=True)
class RuleSnapshot:
    """评估期间使用的不可变规则快照"""
    rules_by_id: dict[str, Rule]
    rules_by_category: dict[str, list[Rule]]
    version_hash: str
    timestamp: datetime | None

    def get_rules_by_category(self, category: str) -> list[Rule]:
        return self.rules_by_category.get(category, [])

    def get_rule(self, rule_id: str) -> Rule | None:
        return self.rules_by_id.get(rule_id)
```

### 7.8 EvaluationAudit（审计记录）

```python
@dataclass
class EvaluationAudit:
    """每次评估的完整审计记录"""
    assessment_id: str
    patient_id: str
    input_hash: str                          # 输入数据的SHA-256
    rules_snapshot_hash: str                 # 使用的规则集hash
    matched_rule_ids: list[str]              # 命中的规则ID列表
    matched_rule_versions: dict[str, str]    # {rule_id: version}
    final_risk_level: RiskLevel
    final_urgency: Urgency
    primary_rule_id: str
    rule_engine_version: str
    llm_model_version: str | None            # AI增强时记录
    llm_prompt_version: str | None
    llm_raw_output: str | None               # AI原始输出（脱敏后）
    extraction_confidence: float | None
    degraded: bool                           # 是否降级模式
    evaluated_at: datetime
    evaluation_duration_ms: int              # 评估耗时
```

### 7.9 类关系总览

```
┌─────────────────────────────────────────────────────────────┐
│                      应用层 (FastAPI)                        │
│  AssessmentService                                          │
│    ├── DegradationManager                                   │
│    │     ├── SymptomExtractor (Protocol)                    │
│    │     │     ├── LLMSymptomExtractor (正常)               │
│    │     │     └── FormSymptomExtractor (降级)              │
│    │     └── ExplanationGenerator (Protocol)                │
│    │           ├── LLMExplanationGenerator (正常)           │
│    │           └── TemplateExplanationGenerator (降级)      │
│    └── RuleEngine                                           │
│          ├── RuleStore                                      │
│          │     ├── RuleSnapshot (不可变快照)                │
│          │     └── RuleRepository (Protocol → PostgreSQL)   │
│          ├── ConditionEvaluator                             │
│          ├── DrugAssociationTable                           │
│          └── AuditLogger (Protocol → PostgreSQL)            │
│                                                             │
│  DecisionTable ──转换──→ Rule[] ──加载──→ RuleStore         │
└─────────────────────────────────────────────────────────────┘
```

### 7.10 关键方法签名汇总

```python
# === 规则引擎核心 ===
class RuleEngine:
    async def evaluate(self, facts: SymptomFacts) -> EvaluationResult: ...

# === 规则存储 ===
class RuleStore:
    async def load_all(self) -> None: ...
    def snapshot(self) -> RuleSnapshot: ...
    async def hot_reload(self, changed_rule_ids: list[str] | None = None) -> int: ...

# === 条件求值 ===
class ConditionEvaluator:
    def evaluate(self, condition: dict, facts: dict) -> bool: ...

# === 决策表 ===
class DecisionTable:
    def to_rules(self) -> list[Rule]: ...
    @classmethod
    def from_json(cls, data: dict) -> "DecisionTable": ...

# === 冲突解决 ===
def resolve_conflicts(matched_rules: list[RuleHit]) -> EvaluationResult: ...

# === 降级管理 ===
class DegradationManager:
    async def evaluate_with_fallback(self, patient_input: PatientInput) -> AssessmentOutput: ...

# === 审计 ===
class PostgresAuditLogger:
    async def log_evaluation(self, audit: EvaluationAudit) -> None: ...
    async def log_rule_change(self, change: RuleChangeAudit) -> None: ...
```
