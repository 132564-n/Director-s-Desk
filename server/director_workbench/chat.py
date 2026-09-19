from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

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
    active_turn_id: str | None = None
    max_rounds: int = 6


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
        self._conversation.updated_at = now
        return message

    def add_agent_message(
        self,
        *,
        role: AgentRole,
        content: str,
        model: str,
        round_number: int,
        reply_to: str | None = None,
    ) -> ChatMessage:
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
    ) -> ChatMessage:
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
            round=2,
            proposal_id=proposal_id,
        )
        self._conversation.messages.append(message)
        self._conversation.status = ConversationStatus.COMPLETE
        self._conversation.active_turn_id = None
        self._conversation.updated_at = now
        return message

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
