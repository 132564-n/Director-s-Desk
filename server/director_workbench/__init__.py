"""Core domain module for the AI director workbench."""

from .chat import (
    ChatMessage,
    ChatMode,
    Conversation,
    ConversationModule,
    ConversationStatus,
    MessageKind,
    Proposal,
    ProposalStatus,
    create_conversation,
)
from .chat_engine import GroupChatEngine, TurnOptions
from .chat_repository import InMemoryConversationRepository, SqliteConversationRepository
from .configured_drafting import ConfiguredDirectorTeam, artifact_from_payload
from .decision_memory import (
    DecisionCard,
    DecisionCardDraft,
    DecisionOption,
    DecisionOptionDraft,
    DecisionStatus,
    FactCategory,
    FactScope,
)
from .domain import (
    ApprovalRecord,
    Asset,
    AssetKind,
    AssetPolicy,
    DirectionPackage,
    Episode,
    OutlinePackage,
    ProjectSettings,
    PromptLanguage,
    Scene,
    ScriptPackage,
    Shot,
    Stage,
    StageStatus,
)
from .drafting import AgentRole, DemoDirectorTeam, DraftResult
from .exporting import build_episode_package
from .model_gateway import ChatCompletion, OpenAICompatibleAdapter
from .model_settings import (
    AgentModelSettings,
    LocalModelSettingsStore,
    ModelSettings,
    ProviderKind,
    ProviderSettings,
)
from .repository import InMemoryWorkflowRepository, SqliteWorkflowRepository
from .workflow import ProductionWorkflow, WorkflowError, WorkflowView

__all__ = [
    "AgentModelSettings",
    "AgentRole",
    "ApprovalRecord",
    "Asset",
    "AssetKind",
    "AssetPolicy",
    "ChatCompletion",
    "ChatMessage",
    "ChatMode",
    "ConfiguredDirectorTeam",
    "Conversation",
    "ConversationModule",
    "ConversationStatus",
    "DecisionCard",
    "DecisionCardDraft",
    "DecisionOption",
    "DecisionOptionDraft",
    "DecisionStatus",
    "DemoDirectorTeam",
    "DirectionPackage",
    "DraftResult",
    "Episode",
    "FactCategory",
    "FactScope",
    "GroupChatEngine",
    "InMemoryConversationRepository",
    "InMemoryWorkflowRepository",
    "LocalModelSettingsStore",
    "MessageKind",
    "ModelSettings",
    "OpenAICompatibleAdapter",
    "OutlinePackage",
    "ProductionWorkflow",
    "ProjectSettings",
    "PromptLanguage",
    "Proposal",
    "ProposalStatus",
    "ProviderKind",
    "ProviderSettings",
    "Scene",
    "ScriptPackage",
    "Shot",
    "SqliteConversationRepository",
    "SqliteWorkflowRepository",
    "Stage",
    "StageStatus",
    "TurnOptions",
    "WorkflowError",
    "WorkflowView",
    "artifact_from_payload",
    "build_episode_package",
    "create_conversation",
]
