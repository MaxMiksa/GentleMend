"""
症状融合器 (SymptomFuser)

职责：将多个来源的提取结果融合为最终的症状列表。

融合策略：
  1. 结构化表单数据优先级最高（患者主动填写）
  2. 同一症状多来源时，取置信度最高的
  3. 冲突解决：同一症状不同来源给出不同严重程度时，
     结构化数据 > LLM > 规则NLP > 关键词
  4. 否定症状从最终列表中标记但保留（供审计）
  5. 紧急标记取并集（任一来源标记紧急即为紧急）
"""

from __future__ import annotations

import logging
from collections import defaultdict

from app.perception.schemas import (
    ExtractionResult,
    ExtractionSource,
    NegationType,
    SymptomEntry,
)

logger = logging.getLogger(__name__)

# 来源优先级：数值越大优先级越高
SOURCE_PRIORITY: dict[ExtractionSource, int] = {
    ExtractionSource.FORM: 100,      # 结构化表单最高
    ExtractionSource.LLM: 80,        # LLM 次之
    ExtractionSource.RULE_NLP: 60,   # 规则NLP
    ExtractionSource.KEYWORD: 40,    # 关键词最低
    ExtractionSource.FUSED: 0,       # 融合后（不参与优先级比较）
}


class SymptomFuser:
    """
    多来源症状融合器。

    使用方法:
        fuser = SymptomFuser()
        fused = fuser.fuse([form_result, keyword_result, llm_result])
    """

    def fuse(self, results: list[ExtractionResult]) -> list[SymptomEntry]:
        """
        融合多个提取结果。

        算法：
        1. 按 ctcae_term 分组所有症状
        2. 每组内按来源优先级排序
        3. 取优先级最高的作为基准，用其他来源补充缺失字段
        4. 紧急标记取并集
        5. 否定状态：如果高优先级来源说"否定"，则最终为否定
        """
        # 按 ctcae_term 分组
        groups: dict[str, list[SymptomEntry]] = defaultdict(list)
        for result in results:
            for symptom in result.symptoms:
                groups[symptom.ctcae_term].append(symptom)

        fused_symptoms: list[SymptomEntry] = []
        for term, entries in groups.items():
            fused = self._fuse_group(term, entries)
            if fused is not None:
                fused_symptoms.append(fused)

        # 按紧急程度和严重程度排序
        fused_symptoms.sort(
            key=lambda s: (
                -int(s.is_urgent),
                -(s.severity_score or 0),
                -(s.confidence),
            ),
        )
        return fused_symptoms

    def _fuse_group(
        self, term: str, entries: list[SymptomEntry],
    ) -> SymptomEntry | None:
        """融合同一症状的多个来源"""
        if not entries:
            return None

        # 按来源优先级降序排列
        entries.sort(
            key=lambda e: SOURCE_PRIORITY.get(e.source, 0),
            reverse=True,
        )

        # 基准：优先级最高的条目
        base = entries[0]

        # 紧急标记取并集
        is_urgent = any(e.is_urgent for e in entries)

        # 否定状态：以最高优先级来源为准
        negation = base.negation

        # 严重程度：优先用高优先级来源的值，缺失时向下查找
        severity = self._pick_first_not_none(
            [e.severity_score for e in entries],
        )
        frequency = self._pick_first_not_none(
            [e.frequency_score for e in entries],
        )
        interference = self._pick_first_not_none(
            [e.interference_score for e in entries],
        )

        # 部位：优先用高优先级来源
        body_site = self._pick_first_not_none(
            [e.body_site for e in entries],
        )

        # 置信度：取最高
        confidence = max(e.confidence for e in entries)

        # 原始文本：取最长的（信息量最大）
        original_text = max(
            (e.original_text for e in entries),
            key=len,
            default="",
        )

        # 记录冲突
        self._log_conflicts(term, entries)

        return SymptomEntry(
            ctcae_term=base.ctcae_term,
            ctcae_term_cn=base.ctcae_term_cn,
            original_text=original_text,
            frequency_score=frequency,
            severity_score=severity,
            interference_score=interference,
            ctcae_grade=base.ctcae_grade,
            body_site=body_site,
            negation=negation,
            confidence=confidence,
            source=ExtractionSource.FUSED,
            is_urgent=is_urgent,
        )

    @staticmethod
    def _pick_first_not_none(values: list) -> Any:
        """取列表中第一个非 None 的值"""
        for v in values:
            if v is not None:
                return v
        return None

    def _log_conflicts(
        self, term: str, entries: list[SymptomEntry],
    ) -> None:
        """记录同一症状不同来源之间的冲突"""
        severity_values = [
            (e.source.value, e.severity_score)
            for e in entries
            if e.severity_score is not None
        ]
        if len(severity_values) >= 2:
            scores = {s for _, s in severity_values}
            if len(scores) > 1:
                logger.warning(
                    "症状 %s 严重程度冲突: %s — 采用最高优先级来源",
                    term, severity_values,
                )

        # 否定状态冲突
        neg_values = [(e.source.value, e.negation.value) for e in entries]
        negs = {n for _, n in neg_values}
        if len(negs) > 1:
            logger.warning(
                "症状 %s 否定状态冲突: %s — 采用最高优先级来源",
                term, neg_values,
            )


# 需要导入 Any
from typing import Any
