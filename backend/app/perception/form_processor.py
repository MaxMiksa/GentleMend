"""
表单处理器 — PRO-CTCAE 问卷数据 → SymptomEntry

将前端提交的结构化表单数据解析为标准化的 SymptomEntry，
包括 PRO-CTCAE 三维度评分到 CTCAE 等级的映射。
"""

from __future__ import annotations

import logging

from app.perception.schemas import (
    ExtractionResult,
    ExtractionSource,
    NegationType,
    PROCTCAEItem,
    SymptomEntry,
    FREQUENCY_MAP,
    SEVERITY_MAP,
    INTERFERENCE_MAP,
)
from app.perception.dictionary import SYMPTOM_TERMS

logger = logging.getLogger(__name__)


class FormProcessor:
    """将 PRO-CTCAE 表单数据转换为 ExtractionResult"""

    def process(self, items: list[PROCTCAEItem]) -> ExtractionResult:
        """
        处理表单数据。

        每个 PROCTCAEItem 包含:
          - symptom_term: CTCAE标准术语（中文）
          - frequency/severity/interference: PRO-CTCAE 三维度文本选项

        转换逻辑:
          1. 文本选项 → 数值评分 (0-4)
          2. 查词典获取英文术语
          3. 三维度评分 → CTCAE 综合等级
        """
        symptoms: list[SymptomEntry] = []

        for item in items:
            # 查词典
            term = SYMPTOM_TERMS.get(item.symptom_term)
            if term is None:
                logger.warning(
                    "表单术语 '%s' 未在词典中找到，跳过", item.symptom_term,
                )
                continue

            # 三维度文本 → 数值
            freq = FREQUENCY_MAP.get(item.frequency) if item.frequency else None
            sev = SEVERITY_MAP.get(item.severity) if item.severity else None
            interf = INTERFERENCE_MAP.get(item.interference) if item.interference else None

            entry = SymptomEntry(
                ctcae_term=term.term_en,
                ctcae_term_cn=term.term_cn,
                original_text=item.symptom_term,
                frequency_score=freq,
                severity_score=sev,
                interference_score=interf,
                confidence=1.0,  # 表单数据置信度最高
                source=ExtractionSource.FORM,
                is_urgent=term.is_urgent,
                negation=NegationType.AFFIRMED,
            )
            # 计算 CTCAE 综合等级
            entry.ctcae_grade = entry.compute_ctcae_grade()
            symptoms.append(entry)

        return ExtractionResult(
            symptoms=symptoms,
            source=ExtractionSource.FORM,
            confidence=1.0,
            latency_ms=0.0,
        )
