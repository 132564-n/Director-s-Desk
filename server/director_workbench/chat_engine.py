from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from threading import Event

from .chat import ChatMode, ConversationModule
from .chat_repository import ConversationRepository
from .configured_drafting import ConfiguredDirectorTeam
from .domain import STAGE_ORDER, Stage, StageStatus
from .drafting import AgentRole, DemoDirectorTeam
from .model_gateway import OpenAICompatibleAdapter
from .model_settings import LocalModelSettingsStore, ProviderKind
from .repository import WorkflowRepository


@dataclass(frozen=True, slots=True)
class TurnOptions:
    user_message_id: str
    mode: ChatMode
    autonomous: bool
    mentions: tuple[AgentRole, ...]


class GroupChatEngine:
    """Runs a bounded group turn and persists each completed contribution."""

    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        workflows: WorkflowRepository,
        model_settings: LocalModelSettingsStore,
    ) -> None:
        self._conversations = conversations
        self._workflows = workflows
        self._model_settings = model_settings

    def run(self, conversation_id: str, options: TurnOptions, stop: Event) -> None:
        try:
            conversation = self._conversations.get(conversation_id)
            workflow = self._workflows.get(conversation.episode_id)
            episode = workflow.snapshot().episode
            user_message = next(
                message for message in conversation.messages if message.id == options.user_message_id
            )
            roles = self._route_roles(conversation.members, user_message.content, options.mentions)
            if options.autonomous and len(roles) < 2:
                roles = self._expand_for_autonomy(conversation.members, roles)
            settings = self._model_settings.load()
            context = json.dumps({
                "goal": conversation.goal,
                "settings": asdict(episode.settings),
                "confirmed_artifacts": {
                    stage.value: asdict(state.artifact.payload)
                    for stage, state in episode.stages.items()
                    if state.artifact and state.status is StageStatus.APPROVED
                },
                "assets": [
                    {"name": asset.name, "description": asset.description,
                     "policy": asset.policy.value}
                    for asset in episode.assets.values()
                    if asset.confirmed or asset.id in user_message.attachment_ids
                ],
                "history": [
                    {"sender": message.sender_name, "content": message.content}
                    for message in conversation.messages[-30:]
                ],
            }, ensure_ascii=False)

            self._run_round(
                conversation_id,
                roles,
                round_number=1,
                prompt=f"当前请求：{user_message.content}\n会话资料：{context}",
                reply_to=user_message.id,
                settings=settings,
                episode_title=episode.title,
                stop=stop,
            )
            if stop.is_set():
                return self._mark_stopped(conversation_id)

            if options.autonomous and len(roles) > 1:
                refreshed = self._conversations.get(conversation_id)
                recent = "\n".join(
                    f"{message.sender_name}：{message.content}"
                    for message in refreshed.messages[-len(roles) :]
                )
                self._run_round(
                    conversation_id,
                    roles[: min(3, len(roles))],
                    round_number=2,
                    prompt=f"会话资料：{context}\n请回应上一轮意见，指出共识或分歧：\n{recent}",
                    reply_to=refreshed.messages[-1].id,
                    settings=settings,
                    episode_title=episode.title,
                    stop=stop,
                )
            if stop.is_set():
                return self._mark_stopped(conversation_id)

            proposal_stage = None
            proposal_title = ""
            proposal_payload = None
            if options.mode is ChatMode.PROPOSAL:
                proposal_stage = self._active_stage(episode)
                configured = ConfiguredDirectorTeam(
                    settings, api_keys=self._model_settings.api_keys(settings),
                )
                team = (
                    configured
                    if configured.uses_external_models(proposal_stage)
                    else DemoDirectorTeam()
                )
                draft = (
                    configured.draft(episode, proposal_stage, instructions=context)
                    if team is configured else team.draft(episode, proposal_stage)
                )
                proposal_title = {
                    Stage.OUTLINE: "故事大纲提案",
                    Stage.SCRIPT: "分场剧本提案",
                    Stage.DIRECTION: "导演执行包提案",
                }[proposal_stage]
                proposal_payload = asdict(draft.artifact)
                proposal_payload.pop("stage", None)

            chief_assignment = next(
                assignment
                for assignment in settings.assignments
                if assignment.role is AgentRole.CHIEF_DIRECTOR
            )
            current = self._conversations.get(conversation_id)
            opinions = "\n".join(
                f"{message.sender_name}：{message.content}"
                for message in current.messages
                if message.created_at >= user_message.created_at
            )
            chief_provider = next(
                item for item in settings.providers if item.id == chief_assignment.provider_id
            )
            decision = (
                "总导演结论：本地演示讨论已结束；请接入真实模型获取针对性结论。\n"
                "少数意见：演示内容不判断实际共识。\n"
                + ("提案：已生成演示草案。" if proposal_stage else "提案：本轮不生成正式提案。")
            )
            if chief_provider.kind is not ProviderKind.DEMO:
                decision, _ = self._respond(
                    AgentRole.CHIEF_DIRECTOR,
                    f"资料：{context}\n本轮发言：{opinions}\n"
                    "请给出总导演结论、少数意见和下一步；不能把尚未解决的分歧写成共识。",
                    3, settings, episode.title,
                )
            if stop.is_set():
                return self._mark_stopped(conversation_id)
            module = ConversationModule(current)
            module.complete_turn(
                decision=decision,
                model=chief_assignment.model,
                proposal_stage=proposal_stage,
                proposal_title=proposal_title,
                proposal_payload=proposal_payload,
            )
            self._conversations.save(module.snapshot())
        # A background turn must always leave an auditable terminal state, including
        # provider/network exceptions whose concrete types vary by adapter.
        except Exception as error:  # noqa: BLE001
            try:
                module = ConversationModule(self._conversations.get(conversation_id))
                module.fail(str(error))
                self._conversations.save(module.snapshot())
            except Exception:  # noqa: BLE001 - best-effort failure persistence
                return

    def _run_round(
        self,
        conversation_id: str,
        roles: tuple[AgentRole, ...],
        *,
        round_number: int,
        prompt: str,
        reply_to: str,
        settings,
        episode_title: str,
        stop: Event,
    ) -> None:
        with ThreadPoolExecutor(max_workers=max(1, len(roles))) as executor:
            futures = {
                executor.submit(
                    self._respond,
                    role,
                    prompt,
                    round_number,
                    settings,
                    episode_title,
                ): role
                for role in roles
            }
            for future in as_completed(futures):
                if stop.is_set():
                    return
                role = futures[future]
                content, model = future.result()
                module = ConversationModule(self._conversations.get(conversation_id))
                module.add_agent_message(
                    role=role,
                    content=content,
                    model=model,
                    round_number=round_number,
                    reply_to=reply_to,
                )
                self._conversations.save(module.snapshot())

    def _respond(self, role, prompt, round_number, settings, episode_title):
        assignment = next(item for item in settings.assignments if item.role is role)
        provider = next(item for item in settings.providers if item.id == assignment.provider_id)
        if provider.kind is ProviderKind.DEMO:
            return self._demo_response(role, prompt, round_number), assignment.model
        api_key = self._model_settings.api_key(provider)
        if not api_key:
            raise RuntimeError(f"{provider.label} 尚未配置 API Key，请打开团队 API 配置")
        completion = OpenAICompatibleAdapter(
            base_url=provider.base_url,
            api_key=api_key,
        ).complete(
            model=assignment.model,
            system_prompt=(
                f"你是中文 AI 漫剧团队的{role.value}。当前项目是《{episode_title}》。"
                "像群聊成员一样直接发言，只讨论你的专业判断。不要冒充其他角色。"
            ),
            user_prompt=prompt,
        )
        return completion.text.strip(), completion.model

    def _demo_response(self, role: AgentRole, prompt: str, round_number: int) -> str:
        subject = prompt.strip().replace("\n", " ")[:56]
        advice = {
            AgentRole.PLANNER: "我建议先明确这一轮要解决的观众期待和追看钩子。",
            AgentRole.WRITER: "人物行动需要一个清楚的动机，场景结束时还要产生信息变化。",
            AgentRole.STORYBOARD_DIRECTOR: "先用建立镜头交代空间，再把情绪转折落到近景。",
            AgentRole.ART_DIRECTOR: "锁定资产的外形和主色不能漂移，参考资产可以只继承质感。",
            AgentRole.PROMPT_ENGINEER: "提示词应拆开主体、动作、构图、光线、镜头与禁止项。",
            AgentRole.CONTINUITY_EDITOR: "我会重点检查人物状态、因果顺序和上下镜头衔接。",
            AgentRole.VOICE_DIRECTOR: "对白要给停顿和重音留出时长，情绪不能只写成形容词。",
            AgentRole.MUSIC_DIRECTOR: "音乐应该托住节奏转折，并在对白出现时主动让位。",
            AgentRole.CHIEF_DIRECTOR: "我会收束分歧并提交唯一版本。",
        }[role]
        if round_number == 2:
            return f"回应上一轮：我同意保留核心方向；补充一点，{advice}"
        return f"关于“{subject}”，{advice}"

    def _route_roles(
        self,
        members: tuple[AgentRole, ...],
        content: str,
        mentions: tuple[AgentRole, ...],
    ) -> tuple[AgentRole, ...]:
        available = tuple(role for role in members if role is not AgentRole.CHIEF_DIRECTOR)
        if mentions:
            selected = tuple(role for role in mentions if role in available)
            return selected or (AgentRole.CHIEF_DIRECTOR,)
        keyword_roles = []
        routes = {
            AgentRole.WRITER: ("故事", "剧本", "对白", "人物"),
            AgentRole.PLANNER: ("受众", "卖点", "定位", "节奏"),
            AgentRole.STORYBOARD_DIRECTOR: ("镜头", "分镜", "机位", "运镜"),
            AgentRole.ART_DIRECTOR: ("画面", "美术", "角色", "场景", "资产"),
            AgentRole.PROMPT_ENGINEER: ("提示词", "模型", "生成"),
            AgentRole.VOICE_DIRECTOR: ("配音", "声线", "台词"),
            AgentRole.MUSIC_DIRECTOR: ("音乐", "音效", "配乐"),
            AgentRole.CONTINUITY_EDITOR: ("检查", "逻辑", "连续", "审校"),
        }
        for role, keywords in routes.items():
            if role in available and any(keyword in content for keyword in keywords):
                keyword_roles.append(role)
        if not keyword_roles:
            keyword_roles = [
                role
                for role in (AgentRole.WRITER, AgentRole.CONTINUITY_EDITOR)
                if role in available
            ]
        return tuple(keyword_roles[:4]) or available[:2]

    def _expand_for_autonomy(
        self,
        members: tuple[AgentRole, ...],
        selected: tuple[AgentRole, ...],
    ) -> tuple[AgentRole, ...]:
        """Ensure autonomous mode is a real exchange rather than a solo monologue."""
        preferred = (
            AgentRole.CONTINUITY_EDITOR,
            AgentRole.WRITER,
            AgentRole.PLANNER,
            AgentRole.STORYBOARD_DIRECTOR,
            AgentRole.ART_DIRECTOR,
            AgentRole.PROMPT_ENGINEER,
            AgentRole.VOICE_DIRECTOR,
            AgentRole.MUSIC_DIRECTOR,
        )
        additions = tuple(
            role
            for role in preferred
            if role in members and role not in selected and role is not AgentRole.CHIEF_DIRECTOR
        )
        return (*selected, *additions[: max(0, 2 - len(selected))])

    def _active_stage(self, episode) -> Stage:
        return next(
            (
                stage
                for stage in STAGE_ORDER
                if episode.stages[stage].status is not StageStatus.APPROVED
                and episode.stages[stage].status is not StageStatus.BLOCKED
            ),
            Stage.DIRECTION,
        )

    def _mark_stopped(self, conversation_id: str) -> None:
        module = ConversationModule(self._conversations.get(conversation_id))
        module.stop()
        self._conversations.save(module.snapshot())
