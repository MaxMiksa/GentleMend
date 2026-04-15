"""
感知层管道 (PerceptionPipeline)

编排整个感知流程：
  1. 处理结构化表单输入
  2. 对自由文本执行三级级联提取
  3. 融合所有来源的结果
  4. 输出标准化的 PerceptionOutput
"""

from __future__ import annotations

import time
import logging

from app.perception.schemas import (
    ExtractionResult,
    ExtractionSource,
    PerceptionInput,
    PerceptionOutput,
)
from app.perception.form_processor import FormProcessor
from app.perception.extractor import (
    KeywordExtractor,
    RuleNLPExtractor,
)
from app.perception.llm_extractor import LLMExtractor
from app.perception.fuser import SymptomFuser

logger = logging.getLogger(__name__)

# 级联触发条件
# Level 1 → Level 2: 当 Level 1 置信度 < 此阈值，或提取到的症状数为 0
CASCADE_L1_TO_L2_THRESHOLD = 0.8
# Level 2 → Level 3: 当 Level 2 置信度 < 此阈值，或文本长度 > 此值（复杂描述）
CASCADE_L2_TO_L3_THRESHOLD = 0.85
CASCADE_L2_TO_L3_TEXT_LENGTH = 50


class PerceptionPipeline:
    """
    感知层主管道。

    流程：
      PerceptionInput
        ├─ form_items → FormProcessor → ExtractionResult (form)
        └─ free_text  → 三级级联提取
             ├─ Level 1: KeywordExtractor
             ├─ Level 2: RuleNLPExtractor (条件触发)
             └─ Level 3: LLMExtractor (条件触发)
        → SymptomFuser.fuse([form, L1, L2?, L3?])
        → PerceptionOutput
    """

    def __init__(
        self,
        llm_api_key: str | None = None,
        llm_model: str = "claude-sonnet-4-20250514",
        llm_timeout: float = 10.0,
        enable_llm: bool = True,
    ) -> None:
        self._form_processor = FormProcessor()
        self._keyword_extractor = KeywordExtractor()
        self._rule_nlp_extractor = RuleNLPExtractor()
        self._llm_extractor = LLMExtractor(
            api_key=llm_api_key,
            model=llm_model,
            timeout_seconds=llm_timeout,
        ) if enable_llm else None
        self._fuser = SymptomFuser()

    async def process(self, input_data: PerceptionInput) -> PerceptionOutput:
        """执行完整的感知流程"""
        start = time.perf_counter()
        all_results: list[ExtractionResult] = []
        sources_used: list[ExtractionSource] = []
        ai_used = False
        ai_degraded = False

        # ── Step 1: 处理结构化表单 ──
        if input_data.form_items:
            form_result = self._form_processor.process(input_data.form_items)
            all_results.append(form_result)
            sources_used.append(ExtractionSource.FORM)
            logger.info(
                "表单提取: %d 个症状", len(form_result.symptoms),
            )

        # ── Step 2: 自由文本三级级联提取 ──
        if input_data.free_text.strip():
            text = input_data.free_text.strip()
            text_results = await self._cascade_extract(text)
            for r in text_results:
                all_results.append(r)
                sources_used.append(r.source)
                if r.source == ExtractionSource.LLM:
                    ai_used = True
                    ai_degraded = r.degraded

        # ── Step 3: 融合 ──
        fused_symptoms = self._fuser.fuse(all_results)

        # ── Step 4: 构建输出 ──
        elapsed = (time.perf_counter() - start) * 1000
        has_urgent = any(s.is_urgent for s in fused_symptoms)

        if has_urgent:
            logger.warning(
                "检测到紧急症状! 症状: %s",
                [s.ctcae_term_cn for s in fused_symptoms if s.is_urgent],
            )

        return PerceptionOutput(
            symptoms=fused_symptoms,
            has_urgent=has_urgent,
            extraction_sources=sources_used,
            total_latency_ms=elapsed,
            ai_used=ai_used,
            ai_degraded=ai_degraded,
            raw_extractions=all_results,
        )

    async def _cascade_extract(
        self, text: str,
    ) -> list[ExtractionResult]:
        """
        三级级联提取。

        触发条件：
          - Level 1 始终执行
          - Level 2: L1 置信度 < 0.8 或 L1 未提取到症状
          - Level 3: L2 置信度 < 0.85 或文本较长(>50字)
        """
        results: list[ExtractionResult] = []

        # ── Level 1: 关键词匹配 ──
        l1 = await self._keyword_extractor.extract(text)
        results.append(l1)
        logger.info(
            "L1 关键词: %d 症状, 置信度=%.2f, %.1fms",
            len(l1.symptoms), l1.confidence, l1.latency_ms,
        )

        # 判断是否需要 Level 2
        need_l2 = (
            l1.confidence < CASCADE_L1_TO_L2_THRESHOLD
            or len(l1.symptoms) == 0
            or len(text) > 20  # 文本稍长就用分词增强
        )

        if need_l2:
            l2 = await self._rule_nlp_extractor.extract(text)
            results.append(l2)
            logger.info(
                "L2 规则NLP: %d 症状, 置信度=%.2f, %.1fms",
                len(l2.symptoms), l2.confidence, l2.latency_ms,
            )

            # 判断是否需要 Level 3
            need_l3 = (
                self._llm_extractor is not None
                and (
                    l2.confidence < CASCADE_L2_TO_L3_THRESHOLD
                    or len(l2.symptoms) == 0
                    or len(text) > CASCADE_L2_TO_L3_TEXT_LENGTH
                )
            )

            if need_l3:
                l3 = await self._llm_extractor.extract(text)
                results.append(l3)
                logger.info(
                    "L3 LLM: %d 症状, 置信度=%.2f, %.1fms, 降级=%s",
                    len(l3.symptoms), l3.confidence,
                    l3.latency_ms, l3.degraded,
                )

        return results
