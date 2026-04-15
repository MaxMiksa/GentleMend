"""
感知层数据模型 — Pydantic v2

核心模型:
  - SymptomEntry: 单个症状的标准化表示（规则引擎的输入单元）
  - ExtractionResult: 提取器的统一输出
  - PRO-CTCAE 问卷相关模型
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 枚举
# ============================================================

class ExtractionSource(str, Enum):
    """提取来源标识"""
    FORM = "form"              # 结构化表单
    KEYWORD = "keyword"        # 第一级：关键词匹配
    RULE_NLP = "rule_nlp"      # 第二级：规则化NLP
    LLM = "llm"                # 第三级：LLM提取
    FUSED = "fused"            # 融合后


class CTCAEDimension(str, Enum):
    """PRO-CTCAE 三维度"""
    FREQUENCY = "frequency"        # 频率
    SEVERITY = "severity"          # 严重程度
    INTERFERENCE = "interference"  # 对日常活动的干扰程度


class NegationType(str, Enum):
    """否定类型"""
    AFFIRMED = "affirmed"    # 肯定表达
    NEGATED = "negated"      # 否定表达 ("不恶心")
    UNCERTAIN = "uncertain"  # 不确定 ("好像有点恶心")


# ============================================================
# PRO-CTCAE 问卷模型
# ============================================================

# PRO-CTCAE 频率选项 → 数值映射
FREQUENCY_MAP: dict[str, int] = {
    "从不": 0, "很少": 1, "偶尔": 2, "经常": 3, "几乎一直": 4,
}

# PRO-CTCAE 严重程度选项 → 数值映射
SEVERITY_MAP: dict[str, int] = {
    "没有": 0, "轻微": 1, "中等": 2, "严重": 3, "非常严重": 4,
}

# PRO-CTCAE 干扰程度选项 → 数值映射
INTERFERENCE_MAP: dict[str, int] = {
    "完全没有": 0, "有一点": 1, "比较多": 2, "很多": 3, "非常多": 4,
}


class PROCTCAEItem(BaseModel):
    """单个 PRO-CTCAE 问卷条目（前端表单提交）"""
    symptom_term: str = Field(..., description="CTCAE标准术语，如'恶心'")
    frequency: str | None = Field(None, description="频率：从不/很少/偶尔/经常/几乎一直")
    severity: str | None = Field(None, description="严重程度：没有/轻微/中等/严重/非常严重")
    interference: str | None = Field(None, description="干扰程度：完全没有/有一点/比较多/很多/非常多")

    @field_validator("frequency")
    @classmethod
    def validate_frequency(cls, v: str | None) -> str | None:
        if v is not None and v not in FREQUENCY_MAP:
            raise ValueError(f"无效的频率选项: {v}，可选: {list(FREQUENCY_MAP.keys())}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str | None) -> str | None:
        if v is not None and v not in SEVERITY_MAP:
            raise ValueError(f"无效的严重程度: {v}，可选: {list(SEVERITY_MAP.keys())}")
        return v

    @field_validator("interference")
    @classmethod
    def validate_interference(cls, v: str | None) -> str | None:
        if v is not None and v not in INTERFERENCE_MAP:
            raise ValueError(f"无效的干扰程度: {v}，可选: {list(INTERFERENCE_MAP.keys())}")
        return v


# ============================================================
# 核心模型：SymptomEntry
# ============================================================

class SymptomEntry(BaseModel):
    """
    单个症状的标准化表示 — 规则引擎的输入单元。

    这是感知层的核心输出，无论输入来自表单、关键词匹配还是LLM，
    最终都统一为此结构。
    """
    # 症状标识
    ctcae_term: str = Field(
        ..., description="CTCAE标准术语（英文），如 Nausea, Fatigue",
    )
    ctcae_term_cn: str = Field(
        ..., description="CTCAE标准术语（中文），如 恶心, 疲劳",
    )
    original_text: str = Field(
        "", description="患者原始表达，如 '吃不下饭'",
    )

    # PRO-CTCAE 三维度评分 (0-4)
    frequency_score: int | None = Field(
        None, ge=0, le=4, description="频率评分 0-4",
    )
    severity_score: int | None = Field(
        None, ge=0, le=4, description="严重程度评分 0-4",
    )
    interference_score: int | None = Field(
        None, ge=0, le=4, description="干扰程度评分 0-4",
    )

    # CTCAE 综合等级 (1-5)
    ctcae_grade: int | None = Field(
        None, ge=1, le=5, description="CTCAE综合等级 1-5",
    )

    # 元信息
    body_site: str | None = Field(None, description="部位，如 '左手'")
    negation: NegationType = Field(
        default=NegationType.AFFIRMED, description="否定状态",
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="提取置信度",
    )
    source: ExtractionSource = Field(
        ..., description="提取来源",
    )
    is_urgent: bool = Field(
        default=False, description="是否触发紧急通道",
    )

    def compute_ctcae_grade(self) -> int:
        """
        根据 PRO-CTCAE 三维度评分计算 CTCAE 综合等级。

        映射规则（简化版，实际应由规则引擎细化）：
          - 三维度最大值 0   -> Grade 1
          - 三维度最大值 1   -> Grade 1
          - 三维度最大值 2   -> Grade 2
          - 三维度最大值 3   -> Grade 3
          - 三维度最大值 4   -> Grade 3-4（需结合具体症状）
        """
        scores = [
            s for s in [
                self.frequency_score,
                self.severity_score,
                self.interference_score,
            ] if s is not None
        ]
        if not scores:
            return self.ctcae_grade or 1
        max_score = max(scores)
        grade_map = {0: 1, 1: 1, 2: 2, 3: 3, 4: 4}
        return grade_map.get(max_score, 1)


# ============================================================
# 提取结果
# ============================================================

class ExtractionResult(BaseModel):
    """提取器的统一输出"""
    symptoms: list[SymptomEntry] = Field(default_factory=list)
    source: ExtractionSource
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    raw_output: Any | None = Field(
        None, description="原始输出（审计用）",
    )
    error: str | None = Field(None, description="错误信息（降级时）")
    degraded: bool = Field(default=False, description="是否降级")


class PerceptionInput(BaseModel):
    """感知层的统一输入"""
    form_items: list[PROCTCAEItem] = Field(
        default_factory=list, description="结构化表单数据",
    )
    free_text: str = Field(
        default="", description="自由文本描述",
    )
    session_id: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PerceptionOutput(BaseModel):
    """感知层的统一输出 — 传递给规则引擎"""
    symptoms: list[SymptomEntry] = Field(default_factory=list)
    has_urgent: bool = Field(default=False, description="是否包含紧急症状")
    extraction_sources: list[ExtractionSource] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    ai_used: bool = False
    ai_degraded: bool = False
    raw_extractions: list[ExtractionResult] = Field(
        default_factory=list, description="各级提取的原始结果（审计用）",
    )
