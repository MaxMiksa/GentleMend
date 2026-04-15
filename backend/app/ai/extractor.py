"""
AI 症状提取器 — OpenAI兼容接口（支持DeepSeek/Claude/OpenAI）+ 降级处理
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

from . import EXTRACTION_PROMPT, KNOWN_SYMPTOMS

logger = logging.getLogger(__name__)

PROMPT_VERSION = "1.0.0"


def _get_config() -> tuple[str | None, str | None, str]:
    """读取AI配置，返回 (api_key, base_url, model)"""
    api_key = os.getenv("AI_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    base_url = os.getenv("AI_API_BASE_URL") or None
    model = os.getenv("AI_MODEL", "deepseek-chat")
    return api_key, base_url, model


def get_client() -> tuple[OpenAI, str] | None:
    """获取 OpenAI 兼容客户端，未配置时返回 None"""
    api_key, base_url, model = _get_config()
    if not api_key:
        return None
    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model


def extract_symptoms_with_ai(text: str) -> dict[str, Any] | None:
    """
    用LLM从自由文本提取症状（OpenAI兼容接口）。
    返回 {"symptoms": [...], "model": str, "prompt_version": str, "raw_output": str}
    失败时返回 None（调用方 fallback 到关键词匹配）。
    """
    if not text or not text.strip():
        return None

    result = get_client()
    if result is None:
        logger.info("AI提取跳过：未配置 AI_API_KEY")
        return None

    client, model = result
    prompt = EXTRACTION_PROMPT.format(
        symptoms=", ".join(KNOWN_SYMPTOMS),
        text=text,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        raw_output = response.choices[0].message.content.strip()

        # 解析JSON — 容忍markdown代码块包裹
        json_str = raw_output
        if json_str.startswith("```"):
            json_str = json_str.split("\n", 1)[-1].rsplit("```", 1)[0]

        symptoms = json.loads(json_str)
        if not isinstance(symptoms, list):
            logger.warning("AI返回非数组: %s", raw_output[:200])
            return None

        # 校验并过滤：只保留已知症状，severity限制在1-10
        valid = []
        for s in symptoms:
            name = s.get("name", "")
            if name not in KNOWN_SYMPTOMS:
                continue
            severity = max(1, min(10, int(s.get("severity", 5))))
            valid.append({"name": name, "severity": severity})

        return {
            "symptoms": valid,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "raw_output": raw_output,
        }

    except json.JSONDecodeError as e:
        logger.warning("AI输出JSON解析失败: %s", e)
        return None
    except Exception as e:
        logger.warning("AI提取异常（将降级到关键词匹配）: %s", e)
        return None


def enhance_with_ai(
    free_text: str,
    risk_level: str,
    ctcae_grades: dict,
    advices: list[dict],
    medication_info: str = "",
    medical_history: str = "",
    symptom_details: list[dict] | None = None,
) -> dict[str, Any] | None:
    """
    用LLM生成结构化的个性化患者解读报告。
    失败时返回 None。
    """
    result = get_client()
    if result is None:
        return None

    client, model = result

    from . import ENHANCEMENT_PROMPT

    # 构建症状详情文本
    details_text = ""
    if symptom_details:
        for sd in symptom_details:
            details_text += f"- {sd['name']}: severity={sd['severity']}, grade={sd.get('grade','N/A')}, risk={sd.get('risk','N/A')}\n"

    prompt = ENHANCEMENT_PROMPT.format(
        free_text=free_text or "（未填写）",
        medication_info=medication_info or "（未填写）",
        medical_history=medical_history or "（未填写）",
        risk_level={"low": "低风险", "medium": "中风险", "high": "高风险"}.get(risk_level, risk_level),
        ctcae_grades=json.dumps(ctcae_grades, ensure_ascii=False),
        symptom_details=details_text or "（无结构化症状）",
    )

    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw_output = response.choices[0].message.content.strip()

        json_str = raw_output
        if json_str.startswith("```"):
            json_str = json_str.split("\n", 1)[-1].rsplit("```", 1)[0]

        data = json.loads(json_str)

        # 构建结构化的 explanation
        parts = []
        if data.get("chief_complaint_summary"):
            parts.append(f"【主诉概要】{data['chief_complaint_summary']}")
        for item in data.get("high_attention_symptoms", []):
            parts.append(f"\n【需要重视】{item.get('symptom', '')}")
            if item.get("why_important"):
                parts.append(f"  原因：{item['why_important']}")
            if item.get("watch_for"):
                parts.append(f"  警示信号：{item['watch_for']}")
            if item.get("suggestion"):
                parts.append(f"  建议：{item['suggestion']}")
        for item in data.get("low_concern_symptoms", []):
            parts.append(f"\n【无需过虑】{item.get('symptom', '')}")
            if item.get("reassurance"):
                parts.append(f"  {item['reassurance']}")

        explanation = "\n".join(parts) if parts else data.get("chief_complaint_summary", "")
        personalized_advice = data.get("personalized_advice", "")

        return {
            "explanation": explanation,
            "personalized_advice": personalized_advice,
            "structured_data": data,
            "model": model,
            "raw_output": raw_output,
        }
    except Exception as e:
        logger.warning("AI增强异常: %s", e)
        return None
