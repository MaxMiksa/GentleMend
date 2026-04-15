"""
浅愈(GentleMend) — 规则引擎核心
基于CTCAE v5.0的乳腺癌副作用风险评估
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.extractor import extract_symptoms_with_ai

logger = logging.getLogger(__name__)


# ── 症状关键词映射（口语化 → 标准CTCAE术语）──

SYMPTOM_ALIASES: dict[str, str] = {
    # 消化系统
    "恶心": "nausea", "想吐": "nausea", "反胃": "nausea",
    "呕吐": "vomiting", "吐了": "vomiting",
    "腹泻": "diarrhea", "拉肚子": "diarrhea", "拉稀": "diarrhea",
    "吃不下": "anorexia", "没食欲": "anorexia", "食欲下降": "anorexia",
    "口腔溃疡": "mucositis", "嘴巴烂": "mucositis", "口腔疼": "mucositis",
    # 血液系统
    "发热": "fever", "发烧": "fever", "体温高": "fever", "低烧": "fever",
    "出血": "hemorrhage", "流血": "hemorrhage", "瘀斑": "hemorrhage",
    # 皮肤/神经
    "皮疹": "rash", "起疹子": "rash", "红疹": "rash",
    "脱发": "alopecia", "掉头发": "alopecia", "头发掉": "alopecia",
    "手脚麻": "neuropathy", "手脚发麻": "neuropathy",
    "麻木": "neuropathy", "刺痛": "neuropathy", "手指麻": "neuropathy",
    "手足综合征": "hand_foot_syndrome", "手脚脱皮": "hand_foot_syndrome",
    # 全身
    "疲劳": "fatigue", "累": "fatigue", "没力气": "fatigue",
    "浑身没劲": "fatigue", "乏力": "fatigue",
    "关节痛": "arthralgia", "关节疼": "arthralgia", "骨头疼": "arthralgia",
    "潮热": "hot_flash", "出汗": "hot_flash", "盗汗": "hot_flash",
    # 心肺
    "胸闷": "cardiotoxicity", "心悸": "cardiotoxicity", "心跳快": "cardiotoxicity",
    "呼吸困难": "dyspnea", "喘不上气": "dyspnea", "气短": "dyspnea",
}

# ── CTCAE决策表 ──
# 格式: symptom -> list of {min_severity, grade, risk_level, advice}

DECISION_TABLE: dict[str, list[dict]] = {
    "nausea": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度恶心，可尝试少量多餐、清淡饮食"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "中度恶心，建议联系医疗团队评估是否需要调整止吐方案"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "重度恶心，需住院或肠外营养支持，请立即联系医疗团队"},
    ],
    "vomiting": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "偶尔呕吐，注意补充水分，观察记录"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "频繁呕吐，有脱水风险，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "严重呕吐，需紧急就医补液治疗"},
    ],
    "diarrhea": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度腹泻，注意补充水分和电解质"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "腹泻加重，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "严重腹泻，有脱水和电解质紊乱风险，请立即就医"},
    ],
    "fever": [
        {"min_severity": 3, "grade": 2, "risk": "medium",
         "advice": "低热，密切监测体温，如持续升高请联系医疗团队"},
        {"min_severity": 6, "grade": 3, "risk": "high",
         "advice": "高热(≥38.3°C)，化疗期间发热可能提示粒缺性发热，请立即就医"},
    ],
    "fatigue": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度疲劳，适当休息，保持适度活动"},
        {"min_severity": 5, "grade": 2, "risk": "low",
         "advice": "中度疲劳，影响日常活动，建议调整作息"},
        {"min_severity": 8, "grade": 3, "risk": "medium",
         "advice": "重度疲劳，严重影响自理能力，建议联系医疗团队"},
    ],
    "neuropathy": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度麻木/刺痛，注意保暖，避免接触冷物"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "中度神经病变，影响日常功能，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "重度神经病变，影响自理能力，请立即就医"},
    ],
    "rash": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度皮疹，保持皮肤清洁，避免刺激"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "皮疹扩散，伴有瘙痒，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "严重皮疹，可能需要全身治疗，请立即就医"},
    ],
    "alopecia": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度脱发，属于化疗常见反应，可考虑使用冷帽"},
        {"min_severity": 5, "grade": 2, "risk": "low",
         "advice": "明显脱发，建议心理支持，可选择假发或头巾"},
    ],
    "anorexia": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "食欲轻度下降，少量多餐，选择喜欢的食物"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "明显食欲减退，体重下降，建议营养评估"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "严重厌食，需营养支持治疗，请联系医疗团队"},
    ],
    "dyspnea": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "活动后轻度气短，注意休息"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "日常活动即感气短，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "静息状态下呼吸困难，请立即就医"},
    ],
    "cardiotoxicity": [
        {"min_severity": 3, "grade": 2, "risk": "medium",
         "advice": "心悸/胸闷，建议心电图检查"},
        {"min_severity": 6, "grade": 3, "risk": "high",
         "advice": "明显心脏不适，可能存在心脏毒性，请立即就医"},
    ],
    "hemorrhage": [
        {"min_severity": 2, "grade": 1, "risk": "medium",
         "advice": "轻微出血，注意观察，避免磕碰"},
        {"min_severity": 5, "grade": 2, "risk": "high",
         "advice": "明显出血，可能血小板低下，请立即就医"},
    ],
    "mucositis": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度口腔不适，保持口腔卫生，使用软毛牙刷"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "口腔溃疡影响进食，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "严重口腔溃疡，无法进食，请立即就医"},
    ],
    "arthralgia": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度关节疼痛，可适当热敷缓解"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "关节疼痛影响活动，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "严重关节疼痛，影响自理，请就医"},
    ],
    "hot_flash": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "轻度潮热，穿透气衣物，保持环境凉爽"},
        {"min_severity": 5, "grade": 2, "risk": "low",
         "advice": "频繁潮热影响生活，可咨询医生是否需要药物干预"},
    ],
    "hand_foot_syndrome": [
        {"min_severity": 1, "grade": 1, "risk": "low",
         "advice": "手足轻度不适，保持皮肤湿润，避免摩擦"},
        {"min_severity": 4, "grade": 2, "risk": "medium",
         "advice": "手足疼痛脱皮，影响日常活动，建议联系医疗团队"},
        {"min_severity": 7, "grade": 3, "risk": "high",
         "advice": "严重手足综合征，无法正常活动，请立即就医"},
    ],
}

# ── 紧急关键词 ──

EMERGENCY_KEYWORDS: list[str] = [
    "高热不退",
    "大量出血",
    "呼吸极度困难",
    "意识模糊",
    "剧烈胸痛",
]

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_RISK_CN = {"low": "低风险", "medium": "中风险", "high": "高风险"}
_SEVERITY_LEVEL_CN = {2: "轻度", 5: "中度", 8: "重度"}

# 症状中文名映射
_SYMPTOM_CN = {
    "nausea": "恶心", "vomiting": "呕吐", "diarrhea": "腹泻",
    "anorexia": "食欲下降", "mucositis": "口腔溃疡", "fever": "发热",
    "hemorrhage": "出血", "rash": "皮疹", "alopecia": "脱发",
    "neuropathy": "手足麻木", "fatigue": "疲劳", "arthralgia": "关节疼痛",
    "hot_flash": "潮热", "cardiotoxicity": "心脏毒性", "dyspnea": "呼吸困难",
    "hand_foot_syndrome": "手足综合征",
}


class RuleEngine:
    """基于CTCAE决策表的规则引擎"""

    version = "1.0.0"

    # ── public ──

    def evaluate(self, symptoms: list[dict], free_text: str) -> dict:
        """
        评估症状列表 + 自由文本，返回风险等级、建议、证据等。
        AI提取优先，失败时降级到关键词匹配。
        """
        all_symptoms = list(symptoms)
        ai_extraction_used = False
        ai_meta: dict | None = None

        # 从自由文本中提取额外症状 — 先尝试AI，失败fallback关键词
        if free_text:
            ai_result = extract_symptoms_with_ai(free_text)
            if ai_result and ai_result["symptoms"]:
                text_symptoms = ai_result["symptoms"]
                ai_extraction_used = True
                ai_meta = {
                    "model": ai_result["model"],
                    "prompt_version": ai_result["prompt_version"],
                    "raw_output": ai_result["raw_output"],
                }
                logger.info("AI提取成功: %d 个症状", len(text_symptoms))
            else:
                text_symptoms = self._extract_from_text(free_text)
                logger.info("降级到关键词匹配: %d 个症状", len(text_symptoms))
        else:
            text_symptoms = []

        existing_names = {s["name"] for s in all_symptoms}
        for ts in text_symptoms:
            if ts["name"] not in existing_names:
                all_symptoms.append(ts)
                existing_names.add(ts["name"])

        ctcae_grades: dict[str, int] = {}
        advices: list[dict] = []
        evidences: list[dict] = []
        symptom_details: list[dict] = []
        max_risk = "low"
        risk_scores: list[float] = []  # 每个症状的风险分

        for symptom in all_symptoms:
            name_raw = symptom.get("name", "")
            severity = symptom.get("severity", 1)

            # 标准化症状名
            std_name = SYMPTOM_ALIASES.get(name_raw, name_raw).lower()
            rules = DECISION_TABLE.get(std_name)
            if not rules:
                continue

            # 找到匹配的最高等级规则（按 min_severity 降序匹配）
            matched = None
            for rule in sorted(rules, key=lambda r: r["min_severity"], reverse=True):
                if severity >= rule["min_severity"]:
                    matched = rule
                    break

            if not matched:
                continue

            grade = matched["grade"]
            risk = matched["risk"]
            ctcae_grades[std_name] = grade

            if _RISK_ORDER.get(risk, 0) > _RISK_ORDER.get(max_risk, 0):
                max_risk = risk

            # 收集风险分（用于真实评分计算）
            risk_scores.append(_RISK_ORDER.get(risk, 0) * 0.5 + grade * 0.15 + severity * 0.02)

            # 收集症状详情（供AI增强使用）
            symptom_details.append({
                "name": _SYMPTOM_CN.get(std_name, std_name),
                "name_en": std_name,
                "severity": severity,
                "grade": grade,
                "risk": risk,
            })

            advices.append({
                "content": matched["advice"],
                "type": f"ctcae_grade_{grade}",
                "priority": grade,
            })

            # 中文化 evidence_text
            symptom_cn = _SYMPTOM_CN.get(std_name, std_name)
            severity_cn = _SEVERITY_LEVEL_CN.get(severity, f"程度{severity}")
            risk_cn = _RISK_CN.get(risk, risk)
            rule_id = f"RULE-{std_name.upper()}-G{grade}-001"
            evidences.append({
                "rule_id": rule_id,
                "rule_version": self.version,
                "confidence": min(1.0, 0.7 + severity * 0.03),
                "matched_conditions": {
                    "symptom": std_name,
                    "severity": severity,
                    "min_severity_threshold": matched["min_severity"],
                },
                "evidence_text": (
                    f"{symptom_cn}（{severity_cn}）匹配 CTCAE Grade {grade}，{risk_cn}"
                ),
            })

        # 紧急关键词检查
        if free_text:
            for kw in EMERGENCY_KEYWORDS:
                if kw in free_text:
                    max_risk = "high"
                    advices.append({
                        "content": f"检测到紧急关键词「{kw}」，请立即联系医疗团队或拨打急救电话",
                        "type": "emergency",
                        "priority": 10,
                    })
                    evidences.append({
                        "rule_id": "RULE-EMERGENCY-001",
                        "rule_version": self.version,
                        "confidence": 1.0,
                        "matched_conditions": {"keyword": kw},
                        "evidence_text": f"自由文本中包含紧急关键词: {kw}",
                    })
                    break  # 一条紧急即够

        # 真实风险评分计算（0-100）
        if risk_scores:
            # 加权：最高分占60%，平均分占40%
            max_score = max(risk_scores)
            avg_score = sum(risk_scores) / len(risk_scores)
            raw = max_score * 0.6 + avg_score * 0.4
            # 归一化到 0-1（理论最大值约 1.0+0.45+0.2 = 1.65）
            risk_score = min(1.0, raw / 1.5)
        else:
            risk_score = 0.0

        # 无症状匹配时给默认建议
        if not advices:
            advices.append({
                "content": "未识别到明确副作用症状，如有不适请及时联系医疗团队",
                "type": "general",
                "priority": 0,
            })

        rationale = self._generate_explanation(max_risk, advices)
        patient_explanation = (
            f"根据您描述的症状，当前评估风险等级为"
            f"{'低' if max_risk == 'low' else '中' if max_risk == 'medium' else '高'}。"
            f"{'请按建议做好日常护理。' if max_risk == 'low' else ''}"
            f"{'建议尽快联系医疗团队。' if max_risk == 'medium' else ''}"
            f"{'请立即就医或联系急救。' if max_risk == 'high' else ''}"
        )

        return {
            "risk_level": max_risk,
            "risk_score": risk_score,
            "ctcae_grades": ctcae_grades,
            "advices": advices,
            "evidences": evidences,
            "symptom_details": symptom_details,
            "rationale": rationale,
            "patient_explanation": patient_explanation,
            "ai_extraction_used": ai_extraction_used,
            "ai_meta": ai_meta,
        }

    # ── private ──

    def _extract_from_text(self, text: str) -> list[dict]:
        """从自由文本中通过关键词匹配提取症状"""
        if not text:
            return []
        found: list[dict] = []
        seen: set[str] = set()
        for keyword, std_name in SYMPTOM_ALIASES.items():
            if keyword in text and std_name not in seen:
                seen.add(std_name)
                found.append({"name": std_name, "severity": 3})
        return found

    def _generate_explanation(self, risk: str, advices: list[dict]) -> str:
        """生成评估理由说明"""
        risk_cn = {"low": "低风险", "medium": "中风险", "high": "高风险"}.get(risk, risk)
        parts = [f"综合评估结果: {risk_cn}。"]
        top = sorted(advices, key=lambda a: a["priority"], reverse=True)[:3]
        for a in top:
            parts.append(f"- {a['content']}")
        return "\n".join(parts)


# ── 依赖注入 ──

_engine_instance: RuleEngine | None = None


def get_rule_engine() -> RuleEngine:
    """FastAPI Depends 使用的工厂函数"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RuleEngine()
    return _engine_instance
