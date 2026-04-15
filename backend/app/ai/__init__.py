"""
浅愈(GentleMend) — AI 症状提取模块
使用 Claude API 从自由文本中提取结构化症状信息。
降级策略：API不可用时 fallback 到关键词匹配。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# 已知的CTCAE标准症状列表（供prompt约束输出范围）
KNOWN_SYMPTOMS = [
    "nausea", "vomiting", "diarrhea", "anorexia", "mucositis",
    "fever", "hemorrhage", "rash", "alopecia", "neuropathy",
    "hand_foot_syndrome", "fatigue", "arthralgia", "hot_flash",
    "cardiotoxicity", "dyspnea",
]

EXTRACTION_PROMPT = """你是一个医疗症状提取助手。从患者的自由文本描述中提取症状信息。

已知症状列表（只能从中选择）：
{symptoms}

请从以下文本中提取症状，返回JSON数组，每个元素包含：
- name: 症状英文名（必须在上述列表中）
- severity: 严重程度估计(1-10)，根据描述判断
- reasoning: 简短说明为什么提取了这个症状

只返回JSON数组，不要其他内容。如果没有识别到任何症状，返回空数组 []。

患者描述：
{text}"""

ENHANCEMENT_PROMPT = """你是乳腺癌治疗副作用管理的资深医疗顾问。请根据以下评估数据，为患者生成结构化的个性化解读报告。

## 患者信息
- 原始描述：{free_text}
- 用药与手术：{medication_info}
- 既往病史：{medical_history}

## 规则引擎评估结果
- 综合风险等级：{risk_level}
- CTCAE分级详情：{ctcae_grades}
- 各症状评估：{symptom_details}

请严格按以下JSON结构返回（不要返回其他内容）：
{{
  "chief_complaint_summary": "用1-2句话概括患者的主诉（基于原始描述和选择的症状）",
  "high_attention_symptoms": [
    {{
      "symptom": "症状名称（中文）",
      "why_important": "为什么需要重视（结合患者的用药/病史，说明该症状在当前治疗背景下的临床意义）",
      "watch_for": "需要进一步观察的警示信号（如果出现这些情况应立即就医）",
      "suggestion": "具体的应对建议"
    }}
  ],
  "low_concern_symptoms": [
    {{
      "symptom": "症状名称（中文）",
      "reassurance": "为什么不需要过于担心（说明这是治疗中的常见反应，以及预期的恢复情况）"
    }}
  ],
  "personalized_advice": "综合所有症状给出的整体建议（2-3句话，具体可操作）"
}}

注意：
- 高风险症状（CTCAE Grade 2-3）放入 high_attention_symptoms
- 低风险症状（CTCAE Grade 1）放入 low_concern_symptoms
- 语气温暖关怀但专业，避免引起恐慌
- 你的回答不构成医疗诊断，请在建议中体现这一点
- 如果有用药信息，要结合药物的已知副作用来分析症状"""
