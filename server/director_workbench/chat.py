from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from .decision_memory import (
    DecisionCard,
    DecisionCardDraft,
    DecisionRevision,
    DecisionStatus,
    create_decision_cards,
)
from .domain import Stage
from .drafting import AgentRole
from .workflow import WorkflowError


class ConversationStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETE = "complete"
    FAILED = "failed"
    STOPPED = "stopped"


class MessageKind(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    DIRECTOR_DECISION = "director_decision"


class ChatMode(StrEnum):
    DISCUSS = "discuss"
    PROPOSAL = "proposal"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    ADOPTED = "adopted"
    CONFIRMED = "confirmed"
    REVISION_REQUESTED = "revision_requested"
    DISCARDED = "discarded"


@dataclass(frozen=True, slots=True)
class Proposal:
    id: str
    stage: Stage
    title: str
    payload: dict
    status: ProposalStatus
    source_message_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatMessage:
    id: str
    kind: MessageKind
    content: str
    created_at: datetime
    sender_name: str
    sender_role: AgentRole | None = None
    model: str = ""
    round: int = 0
    reply_to: str | None = None
    attachment_ids: tuple[str, ...] = ()
    proposal_id: str | None = None
    discarded: bool = False


@dataclass(slots=True)
class Conversation:
    id: str
    episode_id: str
    title: str
    goal: str
    members: tuple[AgentRole, ...]
    template: str
    created_at: datetime
    updated_at: datetime
    status: ConversationStatus = ConversationStatus.IDLE
    pinned: bool = False
    archived: bool = False
    messages: list[ChatMessage] = field(default_factory=list)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    decisions: dict[str, DecisionCard] = field(default_factory=dict)
    active_turn_id: str | None = None
    current_round: int = 0
    max_rounds: int = 4
    discussion_note: str = ""
    calls_made: int = 0


class ConversationModule:
    """Owns auditable mutations for one group-chat conversation."""

    def __init__(self, conversation: Conversation) -> None:
        self._conversation = deepcopy(conversation)

    def begin_turn(
        self,
        *,
        content: str,
        mode: ChatMode,
        autonomous: bool,
        mentions: tuple[AgentRole, ...] = (),
        reply_to: str | None = None,
        attachment_ids: tuple[str, ...] = (),
    ) -> ChatMessage:
        if self._conversation.status is ConversationStatus.RUNNING:
            raise WorkflowError("当前会话仍在讨论中，请先停止或等待本轮结束")
        if not content.strip():
            raise WorkflowError("消息内容不能为空")
        without_mentions = content
        for role in AgentRole:
            without_mentions = without_mentions.replace(f"@{role.value}", "")
        if not re.sub(r"[\W_]+", "", without_mentions, flags=re.UNICODE):
            raise WorkflowError("请在 @角色 后补充具体任务")
        now = datetime.now(UTC)
        metadata = []
        if mode is ChatMode.PROPOSAL:
            metadata.append("proposal")
        if autonomous:
            metadata.append("autonomous")
        if mentions:
            metadata.append("mentions=" + ",".join(role.value for role in mentions))
        message = ChatMessage(
            id=f"message-{uuid4().hex}",
            kind=MessageKind.USER,
            content=content.strip(),
            created_at=now,
            sender_name="你",
            model="|".join(metadata),
            reply_to=reply_to,
            attachment_ids=attachment_ids,
        )
        self._conversation.messages.append(message)
        self._conversation.status = ConversationStatus.RUNNING
        self._conversation.active_turn_id = message.id
        self._conversation.current_round = 0
        self._conversation.max_rounds = 4
        self._conversation.discussion_note = "正在分配专业席位"
        self._conversation.calls_made = 0
        self._conversation.updated_at = now
        return message

    def update_discussion_progress(
        self,
        *,
        round_number: int | None = None,
        note: str | None = None,
        calls_increment: int = 0,
    ) -> None:
        if round_number is not None:
            self._conversation.current_round = max(0, min(
                round_number, self._conversation.max_rounds,
            ))
        if note is not None:
            self._conversation.discussion_note = note.strip()
        self._conversation.calls_made = max(
            0, self._conversation.calls_made + calls_increment,
        )
        self._conversation.updated_at = datetime.now(UTC)

    def add_agent_message(
        self,
        *,
        role: AgentRole,
        content: str,
        model: str,
        round_number: int,
        reply_to: str | None = None,
    ) -> ChatMessage:
        if not content.strip():
            raise WorkflowError("Agent 返回了空内容，本次发言未保存")
        message = ChatMessage(
            id=f"message-{uuid4().hex}",
            kind=MessageKind.AGENT,
            content=content.strip(),
            created_at=datetime.now(UTC),
            sender_name=role.value,
            sender_role=role,
            model=model,
            round=round_number,
            reply_to=reply_to,
        )
        self._conversation.messages.append(message)
        self._conversation.updated_at = message.created_at
        return message

    def complete_turn(
        self,
        *,
        decision: str,
        model: str,
        proposal_stage: Stage | None = None,
        proposal_title: str = "",
        proposal_payload: dict | None = None,
        decision_drafts: tuple[DecisionCardDraft, ...] = (),
        final_round: int = 1,
    ) -> ChatMessage:
        if not decision.strip():
            raise WorkflowError("总导演返回了空内容，本轮不能标记为完成")
        proposal_id = None
        decision_id = f"message-{uuid4().hex}"
        now = datetime.now(UTC)
        if proposal_stage is not None and proposal_payload is not None:
            proposal_id = f"proposal-{uuid4().hex}"
            self._conversation.proposals[proposal_id] = Proposal(
                id=proposal_id,
                stage=proposal_stage,
                title=proposal_title,
                payload=proposal_payload,
                status=ProposalStatus.PENDING,
                source_message_id=decision_id,
                created_at=now,
            )
        message = ChatMessage(
            id=decision_id,
            kind=MessageKind.DIRECTOR_DECISION,
            content=decision.strip(),
            created_at=now,
            sender_name=AgentRole.CHIEF_DIRECTOR.value,
            sender_role=AgentRole.CHIEF_DIRECTOR,
            model=model,
            round=final_round,
            proposal_id=proposal_id,
        )
        self._conversation.messages.append(message)
        cards = create_decision_cards(
            decision_drafts,
            episode_id=self._conversation.episode_id,
            conversation_id=self._conversation.id,
            source_message_id=decision_id,
            created_at=now,
        )
        self._conversation.decisions.update({card.id: card for card in cards})
        self._conversation.status = (
            ConversationStatus.WAITING
            if any(
                card.status is DecisionStatus.PENDING
                for card in self._conversation.decisions.values()
            )
            else ConversationStatus.COMPLETE
        )
        self._conversation.active_turn_id = None
        self._conversation.current_round = min(final_round, self._conversation.max_rounds)
        self._conversation.discussion_note = "总导演已收束本轮讨论"
        self._conversation.updated_at = now
        return message

    def resolve_decision(
        self,
        decision_id: str,
        *,
        action: str,
        option_id: str | None = None,
        custom_value: str = "",
        affected_artifacts: tuple[str, ...] = (),
    ) -> DecisionCard:
        try:
            current = self._conversation.decisions[decision_id]
        except KeyError as error:
            raise WorkflowError(f"决策 {decision_id} 不存在") from error
        if action not in {"confirm", "defer", "reject"}:
            raise WorkflowError("未知的决策操作")
        now = datetime.now(UTC)
        if action == "defer" and current.status is DecisionStatus.CONFIRMED:
            self._system_message(f"决策“{current.question}”暂不修改，继续沿用已确认事实。")
            return current
        history = current.history
        revision = current.revision
        if current.status in {DecisionStatus.CONFIRMED, DecisionStatus.REJECTED}:
            history = (*history, DecisionRevision(
                revision=current.revision,
                status=current.status,
                resolved_value=current.resolved_value,
                selected_option_id=current.selected_option_id,
                changed_at=now,
            ))
            revision += 1
        if action == "confirm":
            selected = next((item for item in current.options if item.id == option_id), None)
            value = custom_value.strip() if custom_value.strip() else (
                f"{selected.label}：{selected.description}" if selected else ""
            )
            if not value:
                raise WorkflowError("请选择一个方案，或填写自定义方案")
            status = DecisionStatus.CONFIRMED
            label = f"已确认：{value}"
        elif action == "defer":
            status = DecisionStatus.DEFERRED
            value = current.resolved_value
            option_id = current.selected_option_id
            label = "已暂缓，保留在待决策队列"
        else:
            status = DecisionStatus.REJECTED
            value = custom_value.strip()
            option_id = None
            label = "已否决，不写入项目事实"
        resolved = DecisionCard(
            id=current.id,
            episode_id=current.episode_id,
            conversation_id=current.conversation_id,
            source_message_id=current.source_message_id,
            question=current.question,
            context=current.context,
            category=current.category,
            scope=current.scope,
            options=current.options,
            status=status,
            created_at=current.created_at,
            resolved_at=now,
            selected_option_id=option_id,
            resolved_value=value,
            revision=revision,
            history=history,
            affected_artifacts=affected_artifacts,
        )
        self._conversation.decisions[decision_id] = resolved
        if not any(
            card.status is DecisionStatus.PENDING
            for card in self._conversation.decisions.values()
        ):
            self._conversation.status = ConversationStatus.COMPLETE
        self._system_message(f"决策“{current.question}”{label}。")
        return resolved

    def stop(self) -> None:
        if self._conversation.status is ConversationStatus.RUNNING:
            self._conversation.status = ConversationStatus.STOPPED
            self._conversation.active_turn_id = None
            self._system_message("本轮讨论已停止，已完成的发言仍然保留。")

    def fail(self, reason: str) -> None:
        self._conversation.status = ConversationStatus.FAILED
        self._conversation.active_turn_id = None
        self._system_message(f"本轮讨论失败：{reason}")

    def set_proposal_status(self, proposal_id: str, status: ProposalStatus) -> Proposal:
        try:
            current = self._conversation.proposals[proposal_id]
        except KeyError as error:
            raise WorkflowError(f"提案 {proposal_id} 不存在") from error
        proposal = Proposal(
            id=current.id,
            stage=current.stage,
            title=current.title,
            payload=current.payload,
            status=status,
            source_message_id=current.source_message_id,
            created_at=current.created_at,
        )
        self._conversation.proposals[proposal_id] = proposal
        label = {
            ProposalStatus.ADOPTED: "已采纳为草案",
            ProposalStatus.CONFIRMED: "已确认并写入正式版本",
            ProposalStatus.REVISION_REQUESTED: "已要求修改",
            ProposalStatus.DISCARDED: "已废弃",
            ProposalStatus.PENDING: "恢复为待处理",
        }[status]
        self._system_message(f"提案“{proposal.title}”{label}。")
        return proposal

    def update_metadata(
        self,
        *,
        title: str | None = None,
        pinned: bool | None = None,
        archived: bool | None = None,
    ) -> None:
        if title is not None and title.strip():
            self._conversation.title = title.strip()
        if pinned is not None:
            self._conversation.pinned = pinned
        if archived is not None:
            self._conversation.archived = archived
        self._conversation.updated_at = datetime.now(UTC)

    def snapshot(self) -> Conversation:
        return deepcopy(self._conversation)

    def _system_message(self, content: str) -> None:
        now = datetime.now(UTC)
        self._conversation.messages.append(
            ChatMessage(
                id=f"message-{uuid4().hex}",
                kind=MessageKind.SYSTEM,
                content=content,
                created_at=now,
                sender_name="系统",
            )
        )
        self._conversation.updated_at = now


def create_conversation(
    *,
    episode_id: str,
    title: str,
    goal: str,
    members: tuple[AgentRole, ...],
    template: str,
) -> Conversation:
    now = datetime.now(UTC)
    if AgentRole.CHIEF_DIRECTOR not in members:
        members = (AgentRole.CHIEF_DIRECTOR, *members)
    return Conversation(
        id=f"conversation-{uuid4().hex}",
        episode_id=episode_id,
        title=title.strip(),
        goal=goal.strip(),
        members=tuple(dict.fromkeys(members)),
        template=template,
        created_at=now,
        updated_at=now,
        messages=[
            ChatMessage(
                id=f"message-{uuid4().hex}",
                kind=MessageKind.SYSTEM,
                content=f"会话已建立。讨论目标：{goal.strip()}",
                created_at=now,
                sender_name="系统",
            )
        ],
    )
