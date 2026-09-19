from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import uuid4


class DecisionStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class FactScope(StrEnum):
    PROJECT = "project"
    EPISODE = "episode"


class FactCategory(StrEnum):
    THEME_AUDIENCE = "theme_audience"
    WORLD_RULE = "world_rule"
    CHARACTER = "character"
    STORY_TIMELINE = "story_timeline"
    SCENE_PROP = "scene_prop"
    VISUAL_ASSET = "visual_asset"
    SHOT_DURATION = "shot_duration"
    VOICE_MUSIC = "voice_music"
    PRODUCTION_CONSTRAINT = "production_constraint"
    OPEN_QUESTION = "open_question"


@dataclass(frozen=True, slots=True)
class DecisionOptionDraft:
    label: str
    description: str
    impact: str = ""
    risk: str = ""
    recommended: bool = False


@dataclass(frozen=True, slots=True)
class DecisionCardDraft:
    question: str
    context: str
    category: FactCategory
    scope: FactScope
    options: tuple[DecisionOptionDraft, ...]


@dataclass(frozen=True, slots=True)
class DecisionOption:
    id: str
    label: str
    description: str
    impact: str = ""
    risk: str = ""
    recommended: bool = False


@dataclass(frozen=True, slots=True)
class DecisionRevision:
    revision: int
    status: DecisionStatus
    resolved_value: str
    selected_option_id: str | None
    changed_at: datetime


@dataclass(frozen=True, slots=True)
class DecisionCard:
    id: str
    episode_id: str
    conversation_id: str
    source_message_id: str
    question: str
    context: str
    category: FactCategory
    scope: FactScope
    options: tuple[DecisionOption, ...]
    status: DecisionStatus
    created_at: datetime
    resolved_at: datetime | None = None
    selected_option_id: str | None = None
    resolved_value: str = ""
    revision: int = 1
    history: tuple[DecisionRevision, ...] = ()
    affected_artifacts: tuple[str, ...] = ()


def create_decision_cards(
    drafts: tuple[DecisionCardDraft, ...],
    *,
    episode_id: str,
    conversation_id: str,
    source_message_id: str,
    created_at: datetime,
) -> tuple[DecisionCard, ...]:
    cards = []
    for draft in drafts[:3]:
        card_id = f"decision-{uuid4().hex}"
        options = tuple(
            DecisionOption(
                id=f"option-{uuid4().hex}",
                label=option.label,
                description=option.description,
                impact=option.impact,
                risk=option.risk,
                recommended=option.recommended,
            )
            for option in draft.options
        )
        cards.append(
            DecisionCard(
                id=card_id,
                episode_id=episode_id,
                conversation_id=conversation_id,
                source_message_id=source_message_id,
                question=draft.question,
                context=draft.context,
                category=draft.category,
                scope=draft.scope,
                options=options,
                status=DecisionStatus.PENDING,
                created_at=created_at,
            )
        )
    return tuple(cards)


def parse_decision_drafts(text: str) -> tuple[DecisionCardDraft, ...]:
    """Parse the strict JSON returned by the chief-director decision extractor."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("决策提取结果不是 JSON 对象")
    raw = json.loads(cleaned[start : end + 1])
    rows = raw.get("decisions", [])
    if not isinstance(rows, list):
        raise TypeError("decisions 必须是数组")

    drafts: list[DecisionCardDraft] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        question = _text(row.get("question"), 180)
        context = _text(row.get("context"), 500)
        raw_options = row.get("options", [])
        if not question or not isinstance(raw_options, list) or not 2 <= len(raw_options) <= 4:
            continue
        options = []
        recommended_seen = False
        for raw_option in raw_options:
            if not isinstance(raw_option, dict):
                continue
            label = _text(raw_option.get("label"), 80)
            description = _text(raw_option.get("description"), 400)
            if not label or not description:
                continue
            recommended = bool(raw_option.get("recommended")) and not recommended_seen
            recommended_seen = recommended_seen or recommended
            options.append(
                DecisionOptionDraft(
                    label=label,
                    description=description,
                    impact=_text(raw_option.get("impact"), 300),
                    risk=_text(raw_option.get("risk"), 300),
                    recommended=recommended,
                )
            )
        if not 2 <= len(options) <= 4:
            continue
        if not recommended_seen:
            first = options[0]
            options[0] = DecisionOptionDraft(
                label=first.label,
                description=first.description,
                impact=first.impact,
                risk=first.risk,
                recommended=True,
            )
        try:
            category = FactCategory(str(row.get("category", "open_question")))
        except ValueError:
            category = FactCategory.OPEN_QUESTION
        try:
            scope = FactScope(str(row.get("scope", "episode")))
        except ValueError:
            scope = FactScope.EPISODE
        drafts.append(
            DecisionCardDraft(
                question=question,
                context=context,
                category=category,
                scope=scope,
                options=tuple(options),
            )
        )
    return tuple(drafts)


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]
