from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .domain import (
    DirectionPackage,
    Episode,
    OutlinePackage,
    PromptLanguage,
    Scene,
    ScriptPackage,
    Shot,
    Stage,
    StageStatus,
)
from .workflow import WorkflowError


class AgentRole(StrEnum):
    CHIEF_DIRECTOR = "总导演"
    PLANNER = "策划"
    WRITER = "编剧"
    STORYBOARD_DIRECTOR = "分镜导演"
    ART_DIRECTOR = "美术指导"
    PROMPT_ENGINEER = "提示词工程师"
    CONTINUITY_EDITOR = "连续性审校"
    VOICE_DIRECTOR = "配音指导"
    MUSIC_DIRECTOR = "音乐指导"


STAGE_TEAMS: dict[Stage, tuple[AgentRole, ...]] = {
    Stage.OUTLINE: (
        AgentRole.CHIEF_DIRECTOR,
        AgentRole.PLANNER,
        AgentRole.WRITER,
        AgentRole.CONTINUITY_EDITOR,
    ),
    Stage.SCRIPT: (
        AgentRole.CHIEF_DIRECTOR,
        AgentRole.WRITER,
        AgentRole.ART_DIRECTOR,
        AgentRole.CONTINUITY_EDITOR,
    ),
    Stage.DIRECTION: (
        AgentRole.CHIEF_DIRECTOR,
        AgentRole.STORYBOARD_DIRECTOR,
        AgentRole.ART_DIRECTOR,
        AgentRole.PROMPT_ENGINEER,
        AgentRole.VOICE_DIRECTOR,
        AgentRole.MUSIC_DIRECTOR,
        AgentRole.CONTINUITY_EDITOR,
    ),
}


@dataclass(frozen=True, slots=True)
class DiscussionMessage:
    agent: AgentRole
    round: int
    message: str


@dataclass(frozen=True, slots=True)
class DraftResult:
    stage: Stage
    participants: tuple[AgentRole, ...]
    discussion: tuple[DiscussionMessage, ...]
    artifact: OutlinePackage | ScriptPackage | DirectionPackage


class DemoDirectorTeam:
    """Deterministic team adapter for local demos and end-to-end verification."""

    def draft(self, episode: Episode, stage: Stage) -> DraftResult:
        self._require_stage_ready(episode, stage)
        if stage is Stage.OUTLINE:
            artifact = self._draft_outline(episode)
        elif stage is Stage.SCRIPT:
            artifact = self._draft_script(episode)
        else:
            artifact = self._draft_direction(episode)
        return DraftResult(
            stage=stage,
            participants=STAGE_TEAMS[stage],
            discussion=self._discussion(stage),
            artifact=artifact,
        )

    def _require_stage_ready(self, episode: Episode, stage: Stage) -> None:
        state = episode.stages[stage]
        if state.status is StageStatus.BLOCKED:
            raise WorkflowError(f"{stage.value} 阶段尚未解锁")

    def _draft_outline(self, episode: Episode) -> OutlinePackage:
        asset_names = "、".join(asset.name for asset in episode.assets.values()) or "尚未命名的主角"
        return OutlinePackage(
            title=episode.title,
            logline=f"{asset_names}被一条来自旧时空的讯息卷入选择，并必须在真相与代价之间作出决定。",
            beats=(
                "异常讯息打破日常，主角被迫行动",
                "线索指向熟悉人物隐藏的过去",
                "主角付出代价后逼近真相",
                "结尾揭示更大的危机，形成追看钩子",
            ),
        )

    def _draft_script(self, episode: Episode) -> ScriptPackage:
        outline = episode.stages[Stage.OUTLINE].artifact
        if outline is None or not isinstance(outline.payload, OutlinePackage):
            raise WorkflowError("找不到已批准的大纲")
        scenes = tuple(
            Scene(
                id=f"scene-{index}",
                heading=f"场景 {index} · {'夜' if index % 2 else '日'}",
                action=beat,
                dialogue=(f"第 {index} 场的核心对白围绕“{beat}”展开。",),
            )
            for index, beat in enumerate(outline.payload.beats, start=1)
        )
        return ScriptPackage(scenes=scenes)

    def _draft_direction(self, episode: Episode) -> DirectionPackage:
        script = episode.stages[Stage.SCRIPT].artifact
        if script is None or not isinstance(script.payload, ScriptPackage):
            raise WorkflowError("找不到已批准的分场剧本")
        duration = min(5.0, episode.settings.max_shot_duration_seconds or 5.0)
        asset_ids = tuple(asset.id for asset in episode.assets.values() if asset.confirmed)
        shots: list[Shot] = []
        for scene_index, scene in enumerate(script.payload.scenes, start=1):
            shots.extend(
                (
                    self._make_shot(
                        episode,
                        shot_id=f"shot-{scene_index}-1",
                        scene=scene,
                        duration=duration,
                        asset_ids=asset_ids,
                        close_up=False,
                    ),
                    self._make_shot(
                        episode,
                        shot_id=f"shot-{scene_index}-2",
                        scene=scene,
                        duration=duration,
                        asset_ids=asset_ids,
                        close_up=True,
                    ),
                )
            )
        return DirectionPackage(shots=tuple(shots))

    def _make_shot(
        self,
        episode: Episode,
        *,
        shot_id: str,
        scene: Scene,
        duration: float,
        asset_ids: tuple[str, ...],
        close_up: bool,
    ) -> Shot:
        framing = "近景特写" if close_up else "中远景建立镜头"
        visual = f"{framing}。{scene.action}"
        chinese_prompt = f"{visual}，电影化构图，人物造型严格参考锁定资产，动作自然连贯"
        if episode.settings.prompt_language is PromptLanguage.ENGLISH:
            prompt = (
                f"{framing}, cinematic composition, preserve locked character references, "
                "natural continuous motion"
            )
        elif episode.settings.prompt_language is PromptLanguage.BILINGUAL:
            prompt = f"{chinese_prompt} / cinematic composition, preserve locked references"
        else:
            prompt = chinese_prompt
        return Shot(
            id=shot_id,
            scene_id=scene.id,
            title=framing,
            estimated_duration_seconds=duration,
            visual_description=visual,
            standard_prompt=prompt,
            asset_ids=asset_ids,
            camera="固定机位" if close_up else "缓慢推近",
            dialogue=scene.dialogue[0] if close_up and scene.dialogue else "",
            voice_direction="克制、清晰，句尾保留停顿" if close_up else "",
            music_direction="低频氛围铺底，转场处收束",
        )

    def _discussion(self, stage: Stage) -> tuple[DiscussionMessage, ...]:
        messages = {
            Stage.OUTLINE: (
                DiscussionMessage(AgentRole.PLANNER, 1, "先建立单集钩子，再把核心冲突压进四个节拍。"),
                DiscussionMessage(AgentRole.WRITER, 1, "人物行动需要由异常讯息触发，结尾留下连续剧悬念。"),
                DiscussionMessage(AgentRole.CONTINUITY_EDITOR, 2, "因果链成立，后续剧本需锁定人物动机。"),
                DiscussionMessage(AgentRole.CHIEF_DIRECTOR, 2, "采用四节拍方案，提交大纲供审批。"),
            ),
            Stage.SCRIPT: (
                DiscussionMessage(AgentRole.WRITER, 1, "每个大纲节拍对应一个场次，保持单场目标明确。"),
                DiscussionMessage(AgentRole.ART_DIRECTOR, 1, "场景描述预留锁定资产的视觉信息。"),
                DiscussionMessage(AgentRole.CONTINUITY_EDITOR, 2, "场次顺序与大纲一致，没有提前泄露结局。"),
                DiscussionMessage(AgentRole.CHIEF_DIRECTOR, 2, "分场结构通过，提交剧本供审批。"),
            ),
            Stage.DIRECTION: (
                DiscussionMessage(AgentRole.STORYBOARD_DIRECTOR, 1, "每场拆为建立镜头和情绪特写。"),
                DiscussionMessage(AgentRole.VOICE_DIRECTOR, 1, "对白集中在特写，保留句尾停顿。"),
                DiscussionMessage(AgentRole.MUSIC_DIRECTOR, 1, "音乐以低频氛围承托，不覆盖对白。"),
                DiscussionMessage(AgentRole.PROMPT_ENGINEER, 2, "提示词已包含构图、动作和资产约束。"),
                DiscussionMessage(AgentRole.CONTINUITY_EDITOR, 2, "镜头时长与资产引用均符合项目规则。"),
                DiscussionMessage(AgentRole.CHIEF_DIRECTOR, 2, "执行包通过内部审校，提交最终审批。"),
            ),
        }
        return messages[stage]
