"""
感知层单元测试 — 覆盖三级提取器 + 融合器 + 管道

运行: pytest backend/tests/perception/ -v
"""

from __future__ import annotations

import pytest
import asyncio

from backend.app.perception.schemas import (
    ExtractionResult,
    ExtractionSource,
    NegationType,
    PROCTCAEItem,
    SymptomEntry,
    PerceptionInput,
)
from backend.app.perception.extractor import KeywordExtractor
from backend.app.perception.form_processor import FormProcessor
from backend.app.perception.fuser import SymptomFuser


# ============================================================
# KeywordExtractor 测试
# ============================================================

class TestKeywordExtractor:
    """Level 1 关键词提取器测试"""

    @pytest.fixture
    def extractor(self) -> KeywordExtractor:
        return KeywordExtractor()

    @pytest.mark.asyncio
    async def test_basic_symptom(self, extractor: KeywordExtractor):
        """基本症状识别"""
        result = await extractor.extract("最近一直恶心")
        assert len(result.symptoms) >= 1
        nausea = next(
            (s for s in result.symptoms if s.ctcae_term == "Nausea"), None,
        )
        assert nausea is not None
        assert nausea.ctcae_term_cn == "恶心"
        assert nausea.negation == NegationType.AFFIRMED

    @pytest.mark.asyncio
    async def test_multiple_symptoms(self, extractor: KeywordExtractor):
        """多症状识别"""
        result = await extractor.extract("恶心呕吐，还拉肚子")
        terms = {s.ctcae_term for s in result.symptoms}
        assert "Nausea" in terms
        assert "Vomiting" in terms
        assert "Diarrhea" in terms

    @pytest.mark.asyncio
    async def test_negation(self, extractor: KeywordExtractor):
        """否定表达识别"""
        result = await extractor.extract("不恶心，但是有点头晕")
        nausea = next(
            (s for s in result.symptoms if s.ctcae_term == "Nausea"), None,
        )
        assert nausea is not None
        assert nausea.negation == NegationType.NEGATED

    @pytest.mark.asyncio
    async def test_colloquial_expression(self, extractor: KeywordExtractor):
        """口语化表达映射"""
        result = await extractor.extract("吃不下饭，浑身没劲")
        terms = {s.ctcae_term for s in result.symptoms}
        assert "Anorexia" in terms
        assert "Fatigue" in terms

    @pytest.mark.asyncio
    async def test_urgent_keyword(self, extractor: KeywordExtractor):
        """紧急关键词识别"""
        result = await extractor.extract("今天发高烧了，喘不上气")
        urgent = [s for s in result.symptoms if s.is_urgent]
        assert len(urgent) >= 1

    @pytest.mark.asyncio
    async def test_degree_extraction(self, extractor: KeywordExtractor):
        """程度词提取"""
        result = await extractor.extract("非常恶心")
        nausea = next(
            (s for s in result.symptoms if s.ctcae_term == "Nausea"), None,
        )
        assert nausea is not None
        assert nausea.severity_score is not None
        assert nausea.severity_score >= 3  # "非常" → 严重

    @pytest.mark.asyncio
    async def test_empty_text(self, extractor: KeywordExtractor):
        """空文本"""
        result = await extractor.extract("")
        assert len(result.symptoms) == 0

    @pytest.mark.asyncio
    async def test_no_symptom_text(self, extractor: KeywordExtractor):
        """无症状文本"""
        result = await extractor.extract("今天天气不错")
        assert len(result.symptoms) == 0

    @pytest.mark.asyncio
    async def test_performance(self, extractor: KeywordExtractor):
        """性能: <10ms"""
        result = await extractor.extract(
            "恶心呕吐，拉肚子，浑身没劲，手脚发麻，还掉头发",
        )
        assert result.latency_ms < 10


# ============================================================
# FormProcessor 测试
# ============================================================

class TestFormProcessor:
    """表单处理器测试"""

    @pytest.fixture
    def processor(self) -> FormProcessor:
        return FormProcessor()

    def test_basic_form(self, processor: FormProcessor):
        """基本表单处理"""
        items = [
            PROCTCAEItem(
                symptom_term="恶心",
                frequency="经常",
                severity="严重",
                interference="很多",
            ),
        ]
        result = processor.process(items)
        assert len(result.symptoms) == 1
        s = result.symptoms[0]
        assert s.ctcae_term == "Nausea"
        assert s.frequency_score == 3   # 经常 → 3
        assert s.severity_score == 3    # 严重 → 3
        assert s.interference_score == 3  # 很多 → 3
        assert s.confidence == 1.0
        assert s.source == ExtractionSource.FORM

    def test_partial_form(self, processor: FormProcessor):
        """部分填写的表单"""
        items = [
            PROCTCAEItem(
                symptom_term="疲劳",
                severity="轻微",
            ),
        ]
        result = processor.process(items)
        assert len(result.symptoms) == 1
        s = result.symptoms[0]
        assert s.ctcae_term == "Fatigue"
        assert s.severity_score == 1
        assert s.frequency_score is None

    def test_unknown_term(self, processor: FormProcessor):
        """未知术语跳过"""
        items = [
            PROCTCAEItem(symptom_term="不存在的症状"),
        ]
        result = processor.process(items)
        assert len(result.symptoms) == 0

    def test_ctcae_grade_computation(self, processor: FormProcessor):
        """CTCAE等级计算"""
        items = [
            PROCTCAEItem(
                symptom_term="恶心",
                frequency="几乎一直",  # 4
                severity="非常严重",    # 4
                interference="非常多",  # 4
            ),
        ]
        result = processor.process(items)
        s = result.symptoms[0]
        assert s.ctcae_grade is not None
        assert s.ctcae_grade >= 3


# ============================================================
# SymptomFuser 测试
# ============================================================

class TestSymptomFuser:
    """融合器测试"""

    @pytest.fixture
    def fuser(self) -> SymptomFuser:
        return SymptomFuser()

    def test_single_source(self, fuser: SymptomFuser):
        """单来源不需要融合"""
        results = [
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Nausea",
                        ctcae_term_cn="恶心",
                        severity_score=2,
                        confidence=0.9,
                        source=ExtractionSource.KEYWORD,
                    ),
                ],
                source=ExtractionSource.KEYWORD,
                confidence=0.9,
            ),
        ]
        fused = fuser.fuse(results)
        assert len(fused) == 1
        assert fused[0].ctcae_term == "Nausea"

    def test_form_priority(self, fuser: SymptomFuser):
        """表单数据优先级高于LLM"""
        results = [
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Nausea",
                        ctcae_term_cn="恶心",
                        severity_score=3,
                        confidence=0.85,
                        source=ExtractionSource.LLM,
                    ),
                ],
                source=ExtractionSource.LLM,
                confidence=0.85,
            ),
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Nausea",
                        ctcae_term_cn="恶心",
                        severity_score=2,
                        confidence=1.0,
                        source=ExtractionSource.FORM,
                    ),
                ],
                source=ExtractionSource.FORM,
                confidence=1.0,
            ),
        ]
        fused = fuser.fuse(results)
        assert len(fused) == 1
        # 表单的 severity=2 应该被采用（优先级更高）
        assert fused[0].severity_score == 2
        # 但置信度取最高
        assert fused[0].confidence == 1.0

    def test_urgent_union(self, fuser: SymptomFuser):
        """紧急标记取并集"""
        results = [
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Fever",
                        ctcae_term_cn="发热",
                        is_urgent=False,
                        confidence=0.7,
                        source=ExtractionSource.KEYWORD,
                    ),
                ],
                source=ExtractionSource.KEYWORD,
                confidence=0.7,
            ),
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Fever",
                        ctcae_term_cn="发热",
                        is_urgent=True,
                        confidence=0.9,
                        source=ExtractionSource.LLM,
                    ),
                ],
                source=ExtractionSource.LLM,
                confidence=0.9,
            ),
        ]
        fused = fuser.fuse(results)
        assert fused[0].is_urgent is True

    def test_dedup(self, fuser: SymptomFuser):
        """同一症状去重"""
        results = [
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Fatigue",
                        ctcae_term_cn="疲劳",
                        confidence=0.8,
                        source=ExtractionSource.KEYWORD,
                    ),
                ],
                source=ExtractionSource.KEYWORD,
                confidence=0.8,
            ),
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Fatigue",
                        ctcae_term_cn="疲劳",
                        confidence=0.9,
                        source=ExtractionSource.RULE_NLP,
                    ),
                ],
                source=ExtractionSource.RULE_NLP,
                confidence=0.9,
            ),
        ]
        fused = fuser.fuse(results)
        assert len(fused) == 1  # 去重后只有一个

    def test_negation_from_high_priority(self, fuser: SymptomFuser):
        """否定状态以高优先级来源为准"""
        results = [
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Nausea",
                        ctcae_term_cn="恶心",
                        negation=NegationType.AFFIRMED,
                        confidence=0.7,
                        source=ExtractionSource.KEYWORD,
                    ),
                ],
                source=ExtractionSource.KEYWORD,
                confidence=0.7,
            ),
            ExtractionResult(
                symptoms=[
                    SymptomEntry(
                        ctcae_term="Nausea",
                        ctcae_term_cn="恶心",
                        negation=NegationType.NEGATED,
                        confidence=0.9,
                        source=ExtractionSource.LLM,
                    ),
                ],
                source=ExtractionSource.LLM,
                confidence=0.9,
            ),
        ]
        fused = fuser.fuse(results)
        # LLM 优先级高于 KEYWORD，所以否定状态应为 NEGATED
        assert fused[0].negation == NegationType.NEGATED


# ============================================================
# PerceptionPipeline 集成测试（不含LLM）
# ============================================================

class TestPerceptionPipeline:
    """管道集成测试（禁用LLM，仅测试L1+L2+融合）"""

    @pytest.fixture
    def pipeline(self):
        from backend.app.perception.pipeline import PerceptionPipeline
        return PerceptionPipeline(enable_llm=False)

    @pytest.mark.asyncio
    async def test_form_only(self, pipeline):
        """仅表单输入"""
        input_data = PerceptionInput(
            form_items=[
                PROCTCAEItem(
                    symptom_term="恶心",
                    severity="严重",
                    frequency="经常",
                ),
            ],
        )
        output = await pipeline.process(input_data)
        assert len(output.symptoms) >= 1
        assert output.ai_used is False

    @pytest.mark.asyncio
    async def test_text_only(self, pipeline):
        """仅自由文本输入"""
        input_data = PerceptionInput(
            free_text="最近三天一直恶心，吃不下东西，今天吐了两次",
        )
        output = await pipeline.process(input_data)
        assert len(output.symptoms) >= 2
        terms = {s.ctcae_term for s in output.symptoms}
        assert "Nausea" in terms

    @pytest.mark.asyncio
    async def test_mixed_input(self, pipeline):
        """表单 + 自由文本混合输入"""
        input_data = PerceptionInput(
            form_items=[
                PROCTCAEItem(
                    symptom_term="恶心",
                    severity="中等",
                ),
            ],
            free_text="还有点头晕，手脚发麻",
        )
        output = await pipeline.process(input_data)
        terms = {s.ctcae_term for s in output.symptoms}
        assert "Nausea" in terms
        assert "Dizziness" in terms

    @pytest.mark.asyncio
    async def test_urgent_detection(self, pipeline):
        """紧急症状检测"""
        input_data = PerceptionInput(
            free_text="发高烧了，喘不上气，胸口疼",
        )
        output = await pipeline.process(input_data)
        assert output.has_urgent is True

    @pytest.mark.asyncio
    async def test_empty_input(self, pipeline):
        """空输入"""
        input_data = PerceptionInput()
        output = await pipeline.process(input_data)
        assert len(output.symptoms) == 0
        assert output.has_urgent is False
