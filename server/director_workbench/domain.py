from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Stage(StrEnum):
    OUTLINE = "outline"
    SCRIPT = "script"
    DIRECTION = "direction"


STAGE_ORDER: tuple[Stage, ...] = (Stage.OUTLINE, Stage.SCRIPT, Stage.DIRECTION)


class StageStatus(StrEnum):
    READY = "ready"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    STALE = "stale"
    BLOCKED = "blocked"


class PromptLanguage(StrEnum):
    CHINESE = "zh"
    ENGLISH = "en"
    BILINGUAL = "bilingual"


class AssetKind(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    PROP = "prop"
    STYLE = "style"


class AssetPolicy(StrEnum):
    LOCKED = "locked"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    target_duration_seconds: int
    prompt_language: PromptLanguage = PromptLanguage.CHINESE
    max_shot_duration_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.target_duration_seconds <= 0:
            raise ValueError("项目目标时长必须大于 0 秒")
        if self.max_shot_duration_seconds is not None and self.max_shot_duration_seconds <= 0:
            raise ValueError("单镜头最高时长必须大于 0 秒")


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    name: str
    kind: AssetKind
    policy: AssetPolicy
    confirmed: bool = False
    description: str = ""
    source_path: str = ""
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class OutlinePackage:
    title: str
    logline: str
    beats: tuple[str, ...]
    stage: Stage = field(default=Stage.OUTLINE, init=False)

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.logline.strip() or not self.beats:
            raise ValueError("大纲必须包含标题、故事梗概和至少一个节拍")


@dataclass(frozen=True, slots=True)
class Scene:
    id: str
    heading: str
    action: str
    dialogue: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptPackage:
    scenes: tuple[Scene, ...]
    stage: Stage = field(default=Stage.SCRIPT, init=False)

    def __post_init__(self) -> None:
        if not self.scenes:
            raise ValueError("剧本必须至少包含一个场次")


@dataclass(frozen=True, slots=True)
class Shot:
    id: str
    scene_id: str
    title: str
    estimated_duration_seconds: float
    visual_description: str
    standard_prompt: str
    asset_ids: tuple[str, ...] = ()
    camera: str = ""
    dialogue: str = ""
    voice_direction: str = ""
    music_direction: str = ""

    def __post_init__(self) -> None:
        if self.estimated_duration_seconds <= 0:
            raise ValueError("镜头预计时长必须大于 0 秒")
        if not self.visual_description.strip() or not self.standard_prompt.strip():
            raise ValueError("镜头必须包含画面描述和标准提示词")


@dataclass(frozen=True, slots=True)
class DirectionPackage:
    shots: tuple[Shot, ...]
    stage: Stage = field(default=Stage.DIRECTION, init=False)

    def __post_init__(self) -> None:
        if not self.shots:
            raise ValueError("导演执行包必须至少包含一个镜头")


type Artifact = OutlinePackage | ScriptPackage | DirectionPackage


@dataclass(frozen=True, slots=True)
class VersionedArtifact:
    stage: Stage
    revision: int
    author: str
    payload: Artifact
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    stage: Stage
    revision: int
    reviewer: str
    note: str
    approved_at: datetime


@dataclass(slots=True)
class StageState:
    status: StageStatus
    artifact: VersionedArtifact | None = None
    review_note: str = ""


@dataclass(slots=True)
class Episode:
    id: str
    title: str
    settings: ProjectSettings
    assets: dict[str, Asset] = field(default_factory=dict)
    stages: dict[Stage, StageState] = field(default_factory=dict)
    approvals: list[ApprovalRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.stages:
            self.stages = {
                Stage.OUTLINE: StageState(StageStatus.READY),
                Stage.SCRIPT: StageState(StageStatus.BLOCKED),
                Stage.DIRECTION: StageState(StageStatus.BLOCKED),
            }
