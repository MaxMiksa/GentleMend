"""
Level 3: LLM 深度理解提取器 — Claude API + Tool Use

包含:
  - 完整的 System Prompt
  - User Prompt 模板
  - Tool Use Schema（强制结构化输出）
  - 超时处理和降级逻辑
  - Pydantic 输出校验
"""

from __future__ import annotations

import time
import logging
import asyncio
from typing import Any

from pydantic import BaseModel, Field

from app.perception.schemas import (
    ExtractionResult,
    ExtractionSource,
    NegationType,
    SymptomEntry,
)
from app.perception.dictionary import SYMPTOM_TERMS

logger = logging.getLogger(__name__)


# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_PROMPT = """\
你是浅愈(GentleMend)医疗AI系统的症状提取模块。你的唯一职责是从乳腺癌患者的副作用描述中，\
精确提取症状信息并结构化输出。

## 你的角色
- 你是一个医学NLP提取器，不是对话助手
- 你只负责提取和结构化，不做诊断、不给建议
- 你必须使用提供的 extract_symptoms 工具来输出结果

## 提取规则
1. 识别所有提及的症状，包括：
   - 明确描述的症状（"我一直恶心"）
   - 隐含的症状（"吃不下饭" → 食欲下降/Anorexia）
   - 口语化表达（"浑身没劲" → 疲劳/Fatigue）

2. 对每个症状提取：
   - CTCAE标准术语（英文+中文）
   - 严重程度评分（0-4，基于患者描述推断）
   - 频率评分（0-4，如果描述中提及）
   - 干扰程度评分（0-4，如果描述中提及）
   - 身体部位（如果提及）
   - 否定状态：affirmed（肯定）/ negated（否定，如"不恶心"）/ uncertain（不确定，如"好像有点"）

3. 严重程度评分标准：
   - 0: 没有该症状
   - 1: 轻微，不影响日常活动
   - 2: 中等，部分影响日常活动
   - 3: 严重，明显影响日常活动
   - 4: 极严重，无法进行日常活动

4. 紧急症状标记（is_urgent=true）：
   - 体温 ≥ 38.3°C 或 ≥ 101°F
   - 任何出血（吐血、便血、咳血等）
   - 呼吸困难
   - 胸痛
   - 意识改变
   - 发热性中性粒细胞减少的征兆

5. 否定表达处理：
   - "不恶心"、"没有呕吐" → negation="negated"
   - "好像有点恶心"、"似乎有些" → negation="uncertain"
   - 否定的症状也要提取，但标记为 negated

## 常见口语化映射参考
- "吃不下饭/没胃口" → Anorexia（食欲下降）
- "手脚发麻" → Peripheral sensory neuropathy（周围神经病变）
- "浑身没劲/没力气" → Fatigue（疲劳）
- "拉肚子" → Diarrhea（腹泻）
- "掉头发" → Alopecia（脱发）
- "起疹子" → Rash maculopapular（皮疹）
- "喘不上气" → Dyspnea（呼吸困难）
- "一阵一阵发热" → Hot flashes（潮热）

## 输出要求
- 必须调用 extract_symptoms 工具
- 每个症状必须有 ctcae_term（英文）和 ctcae_term_cn（中文）
- confidence 反映你对提取准确性的把握（0.0-1.0）
- 如果文本中没有任何症状描述，返回空列表\
"""

USER_PROMPT_TEMPLATE = """\
请从以下乳腺癌患者的副作用描述中提取所有症状信息。

## 患者描述
{patient_text}

请调用 extract_symptoms 工具输出结构化结果。\
"""


# ============================================================
# Tool Use Schema — 强制结构化输出
# ============================================================

EXTRACT_SYMPTOMS_TOOL: dict[str, Any] = {
    "name": "extract_symptoms",
    "description": (
        "从患者描述中提取症状列表，输出结构化数据。"
        "必须为每个识别到的症状调用此工具。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "symptoms": {
                "type": "array",
                "description": "提取到的症状列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "ctcae_term": {
                            "type": "string",
                            "description": "CTCAE标准术语（英文），如 Nausea, Fatigue",
                        },
                        "ctcae_term_cn": {
                            "type": "string",
                            "description": "CTCAE标准术语（中文），如 恶心, 疲劳",
                        },
                        "original_text": {
                            "type": "string",
                            "description": "患者原始表达片段",
                        },
                        "severity_score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 4,
                            "description": "严重程度 0-4",
                        },
                        "frequency_score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 4,
                            "description": "频率 0-4",
                        },
                        "interference_score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 4,
                            "description": "对日常活动干扰程度 0-4",
                        },
                        "body_site": {
                            "type": "string",
                            "description": "身体部位（如有）",
                        },
                        "negation": {
                            "type": "string",
                            "enum": ["affirmed", "negated", "uncertain"],
                            "description": "否定状态",
                        },
                        "is_urgent": {
                            "type": "boolean",
                            "description": "是否紧急症状",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "提取置信度",
                        },
                    },
                    "required": [
                        "ctcae_term", "ctcae_term_cn", "original_text",
                        "negation", "is_urgent", "confidence",
                    ],
                },
            },
            "overall_confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "整体提取置信度",
            },
            "notes": {
                "type": "string",
                "description": "提取过程中的备注（如有歧义）",
            },
        },
        "required": ["symptoms", "overall_confidence"],
    },
}


# ============================================================
# Pydantic 校验模型 — 校验 LLM Tool Use 输出
# ============================================================

class LLMSymptomItem(BaseModel):
    """LLM 输出的单个症状（校验用）"""
    ctcae_term: str
    ctcae_term_cn: str
    original_text: str = ""
    severity_score: int | None = Field(None, ge=0, le=4)
    frequency_score: int | None = Field(None, ge=0, le=4)
    interference_score: int | None = Field(None, ge=0, le=4)
    body_site: str | None = None
    negation: str = "affirmed"
    is_urgent: bool = False
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class LLMExtractionOutput(BaseModel):
    """LLM extract_symptoms 工具的完整输出（校验用）"""
    symptoms: list[LLMSymptomItem] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    notes: str | None = None


# ============================================================
# LLM 提取器实现
# ============================================================

class LLMExtractor:
    """
    第三级提取器 — Claude API 深度理解。

    特点：
      - 能理解复杂语义和隐含症状
      - 能处理口语化、方言化表达
      - 能推断严重程度
      - 超时自动降级
      - 置信度最高 (0.85-0.98)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        timeout_seconds: float = 10.0,
        max_retries: int = 1,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._client: Any = None

    @property
    def level(self) -> int:
        return 3

    @property
    def name(self) -> str:
        return "llm_extractor"

    def _get_client(self) -> Any:
        """延迟初始化 Anthropic 客户端"""
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
            )
        return self._client

    async def extract(self, text: str) -> ExtractionResult:
        start = time.perf_counter()

        try:
            result = await asyncio.wait_for(
                self._call_claude(text),
                timeout=self._timeout,
            )
            elapsed = (time.perf_counter() - start) * 1000
            result.latency_ms = elapsed
            return result

        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - start) * 1000
            logger.warning(
                "LLM提取超时 (%.0fms > %.0fms)",
                elapsed, self._timeout * 1000,
            )
            return ExtractionResult(
                symptoms=[],
                source=ExtractionSource.LLM,
                confidence=0.0,
                latency_ms=elapsed,
                error=f"LLM调用超时 ({self._timeout}s)",
                degraded=True,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error("LLM提取失败: %s", str(e), exc_info=True)
            return ExtractionResult(
                symptoms=[],
                source=ExtractionSource.LLM,
                confidence=0.0,
                latency_ms=elapsed,
                error=f"LLM调用失败: {type(e).__name__}: {e}",
                degraded=True,
            )

    async def _call_claude(self, text: str) -> ExtractionResult:
        """调用 Claude API，使用 Tool Use 强制结构化输出"""
        client = self._get_client()

        user_prompt = USER_PROMPT_TEMPLATE.format(patient_text=text)

        response = await client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=[EXTRACT_SYMPTOMS_TOOL],
            tool_choice={"type": "tool", "name": "extract_symptoms"},
            messages=[{"role": "user", "content": user_prompt}],
        )

        # 从 response 中提取 tool_use block
        tool_input = self._extract_tool_input(response)
        if tool_input is None:
            return ExtractionResult(
                symptoms=[],
                source=ExtractionSource.LLM,
                confidence=0.0,
                error="LLM未返回tool_use结果",
                degraded=True,
                raw_output=str(response),
            )

        # Pydantic 校验
        validated = LLMExtractionOutput.model_validate(tool_input)

        # 转换为 SymptomEntry
        symptoms = self._convert_to_entries(validated)

        return ExtractionResult(
            symptoms=symptoms,
            source=ExtractionSource.LLM,
            confidence=validated.overall_confidence,
            raw_output=tool_input,
        )

    def _extract_tool_input(self, response: Any) -> dict | None:
        """从 Claude response 中提取 tool_use 的 input"""
        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_symptoms":
                return block.input
        return None

    def _convert_to_entries(
        self, output: LLMExtractionOutput,
    ) -> list[SymptomEntry]:
        """将 LLM 校验后的输出转换为 SymptomEntry 列表"""
        entries: list[SymptomEntry] = []
        for item in output.symptoms:
            # 术语标准化：尝试映射到词典中的标准术语
            term_en, term_cn = self._normalize_term(
                item.ctcae_term, item.ctcae_term_cn,
            )
            # 否定类型映射
            neg_map = {
                "affirmed": NegationType.AFFIRMED,
                "negated": NegationType.NEGATED,
                "uncertain": NegationType.UNCERTAIN,
            }
            entries.append(SymptomEntry(
                ctcae_term=term_en,
                ctcae_term_cn=term_cn,
                original_text=item.original_text,
                severity_score=item.severity_score,
                frequency_score=item.frequency_score,
                interference_score=item.interference_score,
                body_site=item.body_site,
                negation=neg_map.get(item.negation, NegationType.AFFIRMED),
                confidence=item.confidence,
                source=ExtractionSource.LLM,
                is_urgent=item.is_urgent,
            ))
        return entries

    @staticmethod
    def _normalize_term(term_en: str, term_cn: str) -> tuple[str, str]:
        """
        尝试将 LLM 输出的术语标准化到词典中的标准术语。
        LLM 可能输出略有不同的术语名，这里做模糊匹配。
        """
        # 先用中文术语在词典中查找
        term_obj = SYMPTOM_TERMS.get(term_cn)
        if term_obj:
            return term_obj.term_en, term_obj.term_cn

        # 遍历词典，按英文术语匹配（不区分大小写）
        term_en_lower = term_en.lower()
        for _, t in SYMPTOM_TERMS.items():
            if t.term_en.lower() == term_en_lower:
                return t.term_en, t.term_cn

        # 未找到匹配，原样返回
        return term_en, term_cn
