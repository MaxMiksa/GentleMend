"""
浅愈(GentleMend) — 规则种子数据
将 DECISION_TABLE 中的规则持久化到 rule_sources 表
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import RuleSource, RuleStatus
from app.rules.engine import DECISION_TABLE, EMERGENCY_KEYWORDS

logger = logging.getLogger(__name__)

VERSION = "1.0.0"


async def seed_rules(session: AsyncSession) -> int:
    """导入规则到数据库，跳过已存在的。返回新增数量。"""
    existing = await session.execute(
        select(RuleSource.rule_id).where(RuleSource.version == VERSION)
    )
    existing_ids = {r[0] for r in existing.all()}

    count = 0
    now = datetime.now(timezone.utc)

    for symptom, rules in DECISION_TABLE.items():
        for rule in rules:
            grade = rule["grade"]
            rule_id = f"RULE-{symptom.upper()}-G{grade}-001"
            if rule_id in existing_ids:
                continue

            source = RuleSource(
                rule_id=rule_id,
                version=VERSION,
                name=f"{symptom} CTCAE Grade {grade}",
                description=rule["advice"],
                category="ctcae_grading",
                ctcae_term=symptom,
                ctcae_grade=grade,
                priority=grade,
                conditions={
                    "symptom": symptom,
                    "min_severity": rule["min_severity"],
                },
                actions={
                    "risk_level": rule["risk"],
                    "advice": rule["advice"],
                },
                status=RuleStatus.ACTIVE,
                effective_from=now,
                created_by="system_seed",
            )
            session.add(source)
            count += 1

    # 紧急关键词规则
    emergency_id = "RULE-EMERGENCY-001"
    if emergency_id not in existing_ids:
        session.add(RuleSource(
            rule_id=emergency_id,
            version=VERSION,
            name="紧急关键词检测",
            description="自由文本中包含紧急关键词时触发高风险",
            category="emergency",
            priority=100,
            conditions={"keywords": EMERGENCY_KEYWORDS},
            actions={"risk_level": "high", "advice": "检测到紧急关键词，请立即联系医疗团队"},
            status=RuleStatus.ACTIVE,
            effective_from=now,
            created_by="system_seed",
        ))
        count += 1

    if count > 0:
        await session.commit()
        logger.info("Seeded %d rules to rule_sources", count)

    return count
