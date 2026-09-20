from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .domain import (
    DirectionPackage,
    Episode,
    OutlinePackage,
    Scene,
    ScriptPackage,
    Shot,
    Stage,
    StageStatus,
)
from .drafting import STAGE_TEAMS, AgentRole, DiscussionMessage, DraftResult
from .model_gateway import CompletionGateway, OpenAICompatibleAdapter
from .model_settings import (
    ModelSettings,
    ProviderKind,
    ProviderSettings,
    effective_profile,
    profile_instruction,
    profile_temperature,
)
from .workflow import WorkflowError


@dataclass(frozen=True, slots=True)
class _AgentOutput:
    role: AgentRole
    text: str


class ConfiguredDirectorTeam:
    """Runs stage experts once, then asks the chief director for a JSON artifact."""

    def __init__(
        self,
        settings: ModelSettings,
        *,
        environment: Mapping[str, str] | None = None,
        api_keys: Mapping[str, str] | None = None,
        gateway_factory: Callable[[ProviderSettings, str], CompletionGateway] | None = None,
    ) -> None:
        settings.validate()
        self._settings = settings
        self._environment = os.environ if environment is None else environment
        self._api_keys = api_keys or {}
        self._gateway_factory = gateway_factory or self._default_gateway
        self._providers = {provider.id: provider for provider in settings.providers}
        self._assignments = {assignment.role: assignment for assignment in settings.assignments}

    def draft(self, episode: Episode, stage: Stage, *, instructions: str = "") -> DraftResult:
        if episode.stages[stage].status is StageStatus.BLOCKED:
            raise WorkflowError(f"{stage.value} 阶段尚未解锁")
        participants = STAGE_TEAMS[stage]
        expert_roles = tuple(role for role in participants if role is not AgentRole.CHIEF_DIRECTOR)
        context = self._project_context(episode, stage)
        if instructions:
            context += f"\n用户任务及会话讨论资料：\n{instructions}"

        with ThreadPoolExecutor(max_workers=len(expert_roles)) as executor:
            outputs = tuple(executor.map(lambda role: self._consult(role, stage, context), expert_roles))

        artifact = self._finalize(episode, stage, context, outputs)
        messages = tuple(
            DiscussionMessage(output.role, 1, output.text) for output in outputs
        ) + (
            DiscussionMessage(
                AgentRole.CHIEF_DIRECTOR,
                2,
                "已综合专业意见并生成结构化定稿，提交用户审批。",
            ),
        )
        return DraftResult(
            stage=stage,
            participants=participants,
            discussion=messages,
            artifact=artifact,
        )

    def uses_external_models(self, stage: Stage) -> bool:
        return any(
            self._providers[self._assignments[role].provider_id].kind
            is ProviderKind.OPENAI_COMPATIBLE
            for role in STAGE_TEAMS[stage]
        )

    def _consult(self, role: AgentRole, stage: Stage, context: str) -> _AgentOutput:
        assignment = self._assignments[role]
        provider = self._providers[assignment.provider_id]
        if provider.kind is ProviderKind.DEMO:
            return _AgentOutput(role, f"{role.value}已按项目事实完成本地演示审阅。")
        gateway = self._gateway(provider)
        completion = gateway.complete(
            model=assignment.model,
            system_prompt=(
                f"你是中文 AI 漫剧制作团队的{role.value}。"
                f"{profile_instruction(effective_profile(assignment))}"
                "只讨论自己专业范围内的关键问题，给出具体可执行建议，不写空话。"
            ),
            user_prompt=f"当前阶段：{stage.value}\n项目材料：\n{context}",
            temperature=profile_temperature(effective_profile(assignment)),
            max_tokens=900,
        )
        return _AgentOutput(role, completion.text.strip())

    def _finalize(
        self,
        episode: Episode,
        stage: Stage,
        context: str,
        outputs: tuple[_AgentOutput, ...],
    ):
        assignment = self._assignments[AgentRole.CHIEF_DIRECTOR]
        provider = self._providers[assignment.provider_id]
        if provider.kind is ProviderKind.DEMO:
            from .drafting import DemoDirectorTeam

            return DemoDirectorTeam().draft(episode, stage).artifact
        opinions = "\n".join(f"[{output.role.value}] {output.text}" for output in outputs)
        completion = self._gateway(provider).complete(
            model=assignment.model,
            system_prompt=(
                "你是总导演。综合专业意见形成唯一版本。"
                f"{profile_instruction(effective_profile(assignment))}"
                "必须只返回符合用户给定结构的 JSON，不要使用 Markdown 代码块。"
            ),
            user_prompt=(
                f"项目材料：\n{context}\n\n专业意见：\n{opinions}\n\n"
                f"输出要求：\n{self._schema(stage, episode)}"
            ),
            json_mode=True,
            temperature=profile_temperature(effective_profile(assignment)),
        )
        try:
            payload = json.loads(_strip_code_fence(completion.text))
            return artifact_from_payload(stage, payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise WorkflowError(f"总导演模型返回的 {stage.value} 结构无效：{error}") from error

    def _gateway(self, provider: ProviderSettings) -> CompletionGateway:
        api_key = self._api_keys.get(provider.id) or self._environment.get(provider.api_key_env, "")
        if not api_key:
            raise WorkflowError(
                f"{provider.label} 尚未配置密钥，请在网页的团队 API 配置中保存 API Key"
                + (f"，或设置环境变量 {provider.api_key_env}" if provider.api_key_env else "")
            )
        return self._gateway_factory(provider, api_key)

    def _default_gateway(self, provider: ProviderSettings, api_key: str) -> CompletionGateway:
        return OpenAICompatibleAdapter(base_url=provider.base_url, api_key=api_key)

    def _project_context(self, episode: Episode, stage: Stage) -> str:
        assets = [
            {
                "id": asset.id,
                "name": asset.name,
                "policy": asset.policy.value,
                "description": asset.description,
            }
            for asset in episode.assets.values()
            if asset.confirmed
        ]
        upstream = {}
        if stage in {Stage.SCRIPT, Stage.DIRECTION}:
            outline = episode.stages[Stage.OUTLINE].artifact
            if outline:
                upstream["outline"] = _artifact_payload(outline.payload)
        if stage is Stage.DIRECTION:
            script = episode.stages[Stage.SCRIPT].artifact
            if script:
                upstream["script"] = _artifact_payload(script.payload)
        return json.dumps(
            {
                "episode": episode.title,
                "target_duration_seconds": episode.settings.target_duration_seconds,
                "max_shot_duration_seconds": episode.settings.max_shot_duration_seconds,
                "prompt_language": episode.settings.prompt_language.value,
                "confirmed_assets": assets,
                **upstream,
            },
            ensure_ascii=False,
        )

    def _schema(self, stage: Stage, episode: Episode) -> str:
        if stage is Stage.OUTLINE:
            return '{"title":"...","logline":"...","beats":["..."]}'
        if stage is Stage.SCRIPT:
            return (
                '{"scenes":[{"id":"scene-1","heading":"内景·地点·时间",'
                '"action":"...","dialogue":["..."]}]}'
            )
        limit = episode.settings.max_shot_duration_seconds
        limit_rule = f"每个 estimated_duration_seconds 必须小于等于 {limit}" if limit else "镜头时长不设上限"
        return (
            '{"shots":[{"id":"shot-1","scene_id":"scene-1","title":"...",'
            '"estimated_duration_seconds":3,"visual_description":"...",'
            '"standard_prompt":"...","asset_ids":[],"camera":"...","dialogue":"...",'
            '"voice_direction":"...","music_direction":"..."}]}。' + limit_rule
        )


def _artifact_payload(artifact) -> dict:
    if isinstance(artifact, OutlinePackage):
        return {"title": artifact.title, "logline": artifact.logline, "beats": artifact.beats}
    if isinstance(artifact, ScriptPackage):
        return {
            "scenes": [
                {
                    "id": scene.id,
                    "heading": scene.heading,
                    "action": scene.action,
                    "dialogue": scene.dialogue,
                }
                for scene in artifact.scenes
            ]
        }
    return {}


def artifact_from_payload(stage: Stage, payload: dict):
    if stage is Stage.OUTLINE:
        return OutlinePackage(
            title=payload["title"],
            logline=payload["logline"],
            beats=tuple(payload["beats"]),
        )
    if stage is Stage.SCRIPT:
        return ScriptPackage(
            scenes=tuple(
                Scene(
                    id=scene["id"],
                    heading=scene["heading"],
                    action=scene["action"],
                    dialogue=tuple(scene.get("dialogue", ())),
                )
                for scene in payload["scenes"]
            )
        )
    return DirectionPackage(
        shots=tuple(
            Shot(
                id=shot["id"],
                scene_id=shot["scene_id"],
                title=shot["title"],
                estimated_duration_seconds=float(shot["estimated_duration_seconds"]),
                visual_description=shot["visual_description"],
                standard_prompt=shot["standard_prompt"],
                asset_ids=tuple(shot.get("asset_ids", ())),
                camera=shot.get("camera", ""),
                dialogue=shot.get("dialogue", ""),
                voice_direction=shot.get("voice_direction", ""),
                music_direction=shot.get("music_direction", ""),
            )
            for shot in payload["shots"]
        )
    )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0]
    return stripped.strip()
