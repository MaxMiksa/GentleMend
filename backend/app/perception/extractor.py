"""
症状提取器 — Protocol + 三级级联实现

  Level 1: KeywordExtractor   — 关键词/正则匹配 (<10ms)
  Level 2: RuleNLPExtractor   — jieba分词 + 模式匹配 (<50ms)
  Level 3: LLMExtractor       — Claude API 深度理解 (<3s)
"""

from __future__ import annotations

import re
import time
import logging
from typing import Protocol, runtime_checkable

from app.perception.schemas import (
    ExtractionResult,
    ExtractionSource,
    NegationType,
    SymptomEntry,
)
from app.perception.dictionary import (
    BODY_SITES,
    DEGREE_WORDS,
    NEGATION_WORDS,
    SYMPTOM_TERMS,
    UNCERTAIN_WORDS,
    URGENT_KEYWORDS,
)

logger = logging.getLogger(__name__)


# ============================================================
# Protocol 定义
# ============================================================

@runtime_checkable
class SymptomExtractorProtocol(Protocol):
    """症状提取器协议 — 所有提取器必须实现此接口"""

    async def extract(self, text: str) -> ExtractionResult:
        """从文本中提取症状列表"""
        ...

    @property
    def level(self) -> int:
        """提取器级别 (1/2/3)"""
        ...

    @property
    def name(self) -> str:
        """提取器名称"""
        ...


# ============================================================
# Level 1: 关键词/正则匹配 (<10ms)
# ============================================================

class KeywordExtractor:
    """
    第一级提取器 — 基于词典的关键词匹配。

    特点：
      - 速度极快 (<10ms)
      - 覆盖常见口语化表达
      - 支持紧急关键词快速通道
      - 支持否定表达识别
      - 置信度中等 (0.7-0.9)
    """

    @property
    def level(self) -> int:
        return 1

    @property
    def name(self) -> str:
        return "keyword_extractor"

    async def extract(self, text: str) -> ExtractionResult:
        start = time.perf_counter()
        symptoms: list[SymptomEntry] = []
        seen_terms: set[str] = set()  # 去重

        # 1) 紧急关键词快速通道
        for kw in URGENT_KEYWORDS:
            if kw in text:
                # 找到对应的标准术语
                term = SYMPTOM_TERMS.get(kw)
                if term and term.term_en not in seen_terms:
                    seen_terms.add(term.term_en)
                    symptoms.append(SymptomEntry(
                        ctcae_term=term.term_en,
                        ctcae_term_cn=term.term_cn,
                        original_text=kw,
                        severity_score=4,
                        confidence=0.9,
                        source=ExtractionSource.KEYWORD,
                        is_urgent=True,
                    ))

        # 2) 遍历症状词典做关键词匹配
        for alias, term in SYMPTOM_TERMS.items():
            if alias in text and term.term_en not in seen_terms:
                # 检查否定
                negation = self._check_negation(text, alias)
                if negation == NegationType.NEGATED:
                    seen_terms.add(term.term_en)
                    symptoms.append(SymptomEntry(
                        ctcae_term=term.term_en,
                        ctcae_term_cn=term.term_cn,
                        original_text=alias,
                        negation=NegationType.NEGATED,
                        confidence=0.8,
                        source=ExtractionSource.KEYWORD,
                        is_urgent=False,
                    ))
                    continue

                # 检查程度词
                severity = self._extract_degree(text, alias)
                seen_terms.add(term.term_en)
                symptoms.append(SymptomEntry(
                    ctcae_term=term.term_en,
                    ctcae_term_cn=term.term_cn,
                    original_text=alias,
                    severity_score=severity,
                    negation=negation,
                    confidence=0.7 if negation == NegationType.UNCERTAIN else 0.85,
                    source=ExtractionSource.KEYWORD,
                    is_urgent=term.is_urgent,
                ))

        elapsed = (time.perf_counter() - start) * 1000
        return ExtractionResult(
            symptoms=symptoms,
            source=ExtractionSource.KEYWORD,
            confidence=0.85 if symptoms else 0.0,
            latency_ms=elapsed,
        )

    def _check_negation(self, text: str, keyword: str) -> NegationType:
        """检查关键词前是否有否定词或不确定词"""
        idx = text.find(keyword)
        if idx < 0:
            return NegationType.AFFIRMED
        # 取关键词前面最多5个字符
        prefix = text[max(0, idx - 5):idx]
        for neg in NEGATION_WORDS:
            if neg in prefix:
                return NegationType.NEGATED
        for unc in UNCERTAIN_WORDS:
            if unc in prefix:
                return NegationType.UNCERTAIN
        return NegationType.AFFIRMED

    def _extract_degree(self, text: str, keyword: str) -> int | None:
        """提取关键词附近的程度词"""
        idx = text.find(keyword)
        if idx < 0:
            return None
        # 检查前面6个字符和后面6个字符
        context = text[max(0, idx - 6):idx + len(keyword) + 6]
        best_score: int | None = None
        for word, (score, _) in DEGREE_WORDS.items():
            if word in context:
                if best_score is None or score > best_score:
                    best_score = score
        return best_score


# ============================================================
# Level 2: 规则化NLP — jieba分词 + 模式匹配 (<50ms)
# ============================================================

class RuleNLPExtractor:
    """
    第二级提取器 — 基于 jieba 分词的规则化 NLP。

    相比 Level 1 的优势：
      - 能处理分词后的组合模式（"手脚 + 发麻"）
      - 能识别部位信息
      - 能处理更复杂的程度表达
      - 置信度更高 (0.8-0.95)

    依赖: pip install jieba
    """

    def __init__(self) -> None:
        import jieba
        self._jieba = jieba
        # 添加自定义医学词典
        for alias in SYMPTOM_TERMS:
            jieba.add_word(alias, freq=1000, tag="symptom")
        for site in BODY_SITES:
            jieba.add_word(site, freq=800, tag="body_site")
        for deg in DEGREE_WORDS:
            jieba.add_word(deg, freq=600, tag="degree")

    @property
    def level(self) -> int:
        return 2

    @property
    def name(self) -> str:
        return "rule_nlp_extractor"

    async def extract(self, text: str) -> ExtractionResult:
        start = time.perf_counter()
        symptoms: list[SymptomEntry] = []
        seen_terms: set[str] = set()

        # jieba 分词（带词性标注）
        import jieba.posseg as pseg
        words = list(pseg.cut(text))
        word_list = [(w.word, w.flag) for w in words]

        for i, (word, flag) in enumerate(word_list):
            term = SYMPTOM_TERMS.get(word)
            if term is None:
                continue
            if term.term_en in seen_terms:
                continue

            # 上下文窗口：前后各3个词
            ctx_start = max(0, i - 3)
            ctx_end = min(len(word_list), i + 4)
            context_words = [w for w, _ in word_list[ctx_start:ctx_end]]

            # 否定检测
            negation = NegationType.AFFIRMED
            prefix_words = [w for w, _ in word_list[ctx_start:i]]
            for pw in prefix_words:
                if pw in NEGATION_WORDS:
                    negation = NegationType.NEGATED
                    break
                if pw in UNCERTAIN_WORDS:
                    negation = NegationType.UNCERTAIN

            # 程度提取
            severity: int | None = None
            for cw in context_words:
                if cw in DEGREE_WORDS:
                    score, _ = DEGREE_WORDS[cw]
                    if severity is None or score > severity:
                        severity = score

            # 部位提取
            body_site: str | None = None
            for cw in context_words:
                if cw in BODY_SITES:
                    body_site = BODY_SITES[cw]
                    break

            seen_terms.add(term.term_en)
            symptoms.append(SymptomEntry(
                ctcae_term=term.term_en,
                ctcae_term_cn=term.term_cn,
                original_text=word,
                severity_score=severity,
                body_site=body_site,
                negation=negation,
                confidence=0.9 if negation == NegationType.AFFIRMED else 0.75,
                source=ExtractionSource.RULE_NLP,
                is_urgent=term.is_urgent,
            ))

        # 补充：尝试组合模式匹配（如 "手脚" + "发麻"）
        self._match_compound_patterns(text, word_list, symptoms, seen_terms)

        elapsed = (time.perf_counter() - start) * 1000
        return ExtractionResult(
            symptoms=symptoms,
            source=ExtractionSource.RULE_NLP,
            confidence=0.9 if symptoms else 0.0,
            latency_ms=elapsed,
        )

    def _match_compound_patterns(
        self,
        text: str,
        word_list: list[tuple[str, str]],
        symptoms: list[SymptomEntry],
        seen: set[str],
    ) -> None:
        """匹配复合模式，如 '手脚 + 发麻' → 周围神经病变"""
        compound_patterns: list[tuple[list[str], str, str, str]] = [
            # (关键词组合, 英文术语, 中文术语, 分类)
            (["手", "麻"], "Peripheral sensory neuropathy", "周围神经病变", "neurological"),
            (["脚", "麻"], "Peripheral sensory neuropathy", "周围神经病变", "neurological"),
            (["手脚", "麻"], "Peripheral sensory neuropathy", "周围神经病变", "neurological"),
            (["吃不下", "饭"], "Anorexia", "食欲下降", "gastrointestinal"),
            (["睡不着", "觉"], "Insomnia", "失眠", "neurological"),
            (["白细胞", "低"], "Febrile neutropenia", "发热性中性粒细胞减少", "hematological"),
        ]
        all_words = {w for w, _ in word_list}
        for keywords, term_en, term_cn, _ in compound_patterns:
            if term_en in seen:
                continue
            if all(any(kw in w for w in all_words) for kw in keywords):
                seen.add(term_en)
                symptoms.append(SymptomEntry(
                    ctcae_term=term_en,
                    ctcae_term_cn=term_cn,
                    original_text="".join(keywords),
                    confidence=0.8,
                    source=ExtractionSource.RULE_NLP,
                ))
