"""
浅愈(GentleMend) — 感知层 (Perception Layer)

职责：接收并理解用户的副作用描述，将非结构化/半结构化输入
转化为规则引擎可处理的结构化数据。

架构：三级级联提取 + 多模态融合
  Level 1: 关键词/正则匹配 (<10ms)
  Level 2: 规则化NLP - jieba分词 (<50ms)
  Level 3: LLM深度理解 - Claude API (<3s)
"""

from app.perception.schemas import SymptomEntry, ExtractionResult
from app.perception.extractor import SymptomExtractorProtocol
from app.perception.fuser import SymptomFuser
from app.perception.pipeline import PerceptionPipeline

__all__ = [
    "SymptomEntry",
    "ExtractionResult",
    "SymptomExtractorProtocol",
    "SymptomFuser",
    "PerceptionPipeline",
]
