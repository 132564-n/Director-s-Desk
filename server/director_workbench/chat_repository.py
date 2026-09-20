from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .chat import (
    ChatMessage,
    Conversation,
    ConversationStatus,
    MessageKind,
    Proposal,
    ProposalStatus,
)
from .decision_memory import (
    DecisionCard,
    DecisionOption,
    DecisionRevision,
    DecisionStatus,
    FactCategory,
    FactScope,
)
from .domain import Stage
from .drafting import AgentRole


class ConversationRepository(Protocol):
    def create(self, conversation: Conversation) -> None: ...
    def get(self, conversation_id: str) -> Conversation: ...
    def save(self, conversation: Conversation) -> None: ...
    def list(self, episode_id: str | None = None) -> tuple[Conversation, ...]: ...


class InMemoryConversationRepository:
    def __init__(self) -> None:
        self._documents: dict[str, str] = {}

    def create(self, conversation: Conversation) -> None:
        if conversation.id in self._documents:
            raise ValueError(f"会话 {conversation.id} 已存在")
        self._documents[conversation.id] = _to_json(conversation)

    def get(self, conversation_id: str) -> Conversation:
        try:
            return _from_json(self._documents[conversation_id])
        except KeyError as error:
            raise KeyError(f"会话 {conversation_id} 不存在") from error

    def save(self, conversation: Conversation) -> None:
        if conversation.id not in self._documents:
            raise KeyError(f"会话 {conversation.id} 不存在")
        self._documents[conversation.id] = _to_json(conversation)

    def list(self, episode_id: str | None = None) -> tuple[Conversation, ...]:
        conversations = tuple(_from_json(document) for document in self._documents.values())
        return tuple(
            sorted(
                (
                    conversation
                    for conversation in conversations
                    if episode_id is None or conversation.episode_id == episode_id
                ),
                key=lambda item: (not item.pinned, -item.updated_at.timestamp()),
            )
        )


class SqliteConversationRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    episode_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    document TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversations_episode ON conversations(episode_id)"
            )

    def create(self, conversation: Conversation) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO conversations (id, episode_id, updated_at, document) VALUES (?, ?, ?, ?)",
                    (
                        conversation.id,
                        conversation.episode_id,
                        conversation.updated_at.isoformat(),
                        _to_json(conversation),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"会话 {conversation.id} 已存在") from error

    def get(self, conversation_id: str) -> Conversation:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"会话 {conversation_id} 不存在")
        return _from_json(row[0])

    def save(self, conversation: Conversation) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET updated_at = ?, document = ? WHERE id = ?",
                (conversation.updated_at.isoformat(), _to_json(conversation), conversation.id),
            )
            updated = cursor.rowcount
        if updated != 1:
            raise KeyError(f"会话 {conversation.id} 不存在")

    def list(self, episode_id: str | None = None) -> tuple[Conversation, ...]:
        with self._connect() as connection:
            if episode_id is None:
                rows = connection.execute(
                    "SELECT document FROM conversations ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT document FROM conversations WHERE episode_id = ? ORDER BY updated_at DESC",
                    (episode_id,),
                ).fetchall()
        conversations = [_from_json(row[0]) for row in rows]
        return tuple(sorted(conversations, key=lambda item: (not item.pinned, -item.updated_at.timestamp())))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()


def _to_json(conversation: Conversation) -> str:
    return json.dumps(
        {
            "id": conversation.id,
            "episode_id": conversation.episode_id,
            "title": conversation.title,
            "goal": conversation.goal,
            "members": [role.value for role in conversation.members],
            "template": conversation.template,
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "status": conversation.status.value,
            "pinned": conversation.pinned,
            "archived": conversation.archived,
            "messages": [_message_to_dict(message) for message in conversation.messages],
            "proposals": {
                proposal_id: {
                    "id": proposal.id,
                    "stage": proposal.stage.value,
                    "title": proposal.title,
                    "payload": proposal.payload,
                    "status": proposal.status.value,
                    "source_message_id": proposal.source_message_id,
                    "created_at": proposal.created_at.isoformat(),
                }
                for proposal_id, proposal in conversation.proposals.items()
            },
            "decisions": {
                decision_id: {
                    "id": card.id,
                    "episode_id": card.episode_id,
                    "conversation_id": card.conversation_id,
                    "source_message_id": card.source_message_id,
                    "question": card.question,
                    "context": card.context,
                    "category": card.category.value,
                    "scope": card.scope.value,
                    "options": [
                        {
                            "id": option.id,
                            "label": option.label,
                            "description": option.description,
                            "impact": option.impact,
                            "risk": option.risk,
                            "recommended": option.recommended,
                        }
                        for option in card.options
                    ],
                    "status": card.status.value,
                    "created_at": card.created_at.isoformat(),
                    "resolved_at": card.resolved_at.isoformat() if card.resolved_at else None,
                    "selected_option_id": card.selected_option_id,
                    "resolved_value": card.resolved_value,
                    "revision": card.revision,
                    "history": [
                        {
                            "revision": item.revision,
                            "status": item.status.value,
                            "resolved_value": item.resolved_value,
                            "selected_option_id": item.selected_option_id,
                            "changed_at": item.changed_at.isoformat(),
                        }
                        for item in card.history
                    ],
                    "affected_artifacts": list(card.affected_artifacts),
                }
                for decision_id, card in conversation.decisions.items()
            },
            "active_turn_id": conversation.active_turn_id,
            "current_round": conversation.current_round,
            "max_rounds": conversation.max_rounds,
            "discussion_note": conversation.discussion_note,
            "calls_made": conversation.calls_made,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _message_to_dict(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "kind": message.kind.value,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "sender_name": message.sender_name,
        "sender_role": message.sender_role.value if message.sender_role else None,
        "model": message.model,
        "round": message.round,
        "reply_to": message.reply_to,
        "attachment_ids": list(message.attachment_ids),
        "proposal_id": message.proposal_id,
        "discarded": message.discarded,
    }


def _from_json(document: str) -> Conversation:
    raw = json.loads(document)
    return Conversation(
        id=raw["id"],
        episode_id=raw["episode_id"],
        title=raw["title"],
        goal=raw["goal"],
        members=tuple(AgentRole(role) for role in raw["members"]),
        template=raw["template"],
        created_at=datetime.fromisoformat(raw["created_at"]),
        updated_at=datetime.fromisoformat(raw["updated_at"]),
        status=ConversationStatus(raw["status"]),
        pinned=raw["pinned"],
        archived=raw["archived"],
        messages=[
            ChatMessage(
                id=message["id"],
                kind=MessageKind(message["kind"]),
                content=message["content"],
                created_at=datetime.fromisoformat(message["created_at"]),
                sender_name=message["sender_name"],
                sender_role=AgentRole(message["sender_role"]) if message["sender_role"] else None,
                model=message["model"],
                round=message["round"],
                reply_to=message["reply_to"],
                attachment_ids=tuple(message["attachment_ids"]),
                proposal_id=message["proposal_id"],
                discarded=message["discarded"],
            )
            for message in raw["messages"]
        ],
        proposals={
            proposal_id: Proposal(
                id=proposal["id"],
                stage=Stage(proposal["stage"]),
                title=proposal["title"],
                payload=proposal["payload"],
                status=ProposalStatus(proposal["status"]),
                source_message_id=proposal["source_message_id"],
                created_at=datetime.fromisoformat(proposal["created_at"]),
            )
            for proposal_id, proposal in raw["proposals"].items()
        },
        decisions={
            decision_id: DecisionCard(
                id=card["id"],
                episode_id=card["episode_id"],
                conversation_id=card["conversation_id"],
                source_message_id=card["source_message_id"],
                question=card["question"],
                context=card.get("context", ""),
                category=FactCategory(card["category"]),
                scope=FactScope(card["scope"]),
                options=tuple(
                    DecisionOption(
                        id=option["id"],
                        label=option["label"],
                        description=option["description"],
                        impact=option.get("impact", ""),
                        risk=option.get("risk", ""),
                        recommended=option.get("recommended", False),
                    )
                    for option in card["options"]
                ),
                status=DecisionStatus(card["status"]),
                created_at=datetime.fromisoformat(card["created_at"]),
                resolved_at=(
                    datetime.fromisoformat(card["resolved_at"])
                    if card.get("resolved_at") else None
                ),
                selected_option_id=card.get("selected_option_id"),
                resolved_value=card.get("resolved_value", ""),
                revision=card.get("revision", 1),
                history=tuple(
                    DecisionRevision(
                        revision=item["revision"],
                        status=DecisionStatus(item["status"]),
                        resolved_value=item.get("resolved_value", ""),
                        selected_option_id=item.get("selected_option_id"),
                        changed_at=datetime.fromisoformat(item["changed_at"]),
                    )
                    for item in card.get("history", [])
                ),
                affected_artifacts=tuple(card.get("affected_artifacts", [])),
            )
            for decision_id, card in raw.get("decisions", {}).items()
        },
        active_turn_id=raw.get("active_turn_id"),
        current_round=raw.get("current_round", 0),
        max_rounds=min(4, raw.get("max_rounds", 4)),
        discussion_note=raw.get("discussion_note", ""),
        calls_made=raw.get("calls_made", 0),
    )
