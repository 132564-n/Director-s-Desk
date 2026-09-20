from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from threading import Event

from .chat import ChatMode, ConversationModule
from .chat_repository import ConversationRepository
from .configured_drafting import ConfiguredDirectorTeam
from .decision_memory import DecisionCardDraft, DecisionStatus, parse_decision_drafts
from .domain import STAGE_ORDER, Stage, StageStatus
from .drafting import STAGE_TEAMS, AgentRole, DemoDirectorTeam
from .model_gateway import OpenAICompatibleAdapter
from .model_settings import (
    LocalModelSettingsStore,
    ModelSettings,
    ProviderKind,
    effective_profile,
    profile_instruction,
    profile_temperature,
)
from .repository import WorkflowRepository


@dataclass(frozen=True, slots=True)
class TurnOptions:
    user_message_id: str
    mode: ChatMode
    autonomous: bool
    mentions: tuple[AgentRole, ...]


@dataclass(frozen=True, slots=True)
class DiscussionReview:
    continue_discussion: bool
    unresolved_roles: tuple[AgentRole, ...]
    unresolved_points: tuple[str, ...]
    reason: str


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
            memory_rows = self._conversations.list(conversation.episode_id)
            confirmed_facts = []
            rejected_options = []
            pending_decisions = []
            for meeting in memory_rows:
                for card in meeting.decisions.values():
                    if card.status is DecisionStatus.CONFIRMED:
                        confirmed_facts.append({
                            "scope": card.scope.value,
                            "category": card.category.value,
                            "question": card.question,
                            "value": card.resolved_value,
                            "revision": card.revision,
                        })
                        rejected_options.extend(
                            option.label for option in card.options
                            if option.id != card.selected_option_id
                        )
                    elif card.status is DecisionStatus.REJECTED:
                        rejected_options.extend(option.label for option in card.options)
                    elif card.status in {DecisionStatus.PENDING, DecisionStatus.DEFERRED}:
                        pending_decisions.append(card.question)
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
                "project_memory": {
                    "confirmed_facts": confirmed_facts[-80:],
                    "rejected_options": rejected_options[-80:],
                    "pending_decisions": pending_decisions[-30:],
                },
            }, ensure_ascii=False)

            max_rounds = min(4, max(1, conversation.max_rounds))
            current_roles = roles
            focus_points: tuple[str, ...] = ()
            last_round = 0
            for round_number in range(1, max_rounds + 1):
                refreshed = self._conversations.get(conversation_id)
                if round_number == 1:
                    round_prompt = f"当前请求：{user_message.content}\n会话资料：{context}"
                    reply_to = user_message.id
                else:
                    recent = "\n".join(
                        f"{message.sender_name}：{message.content}"
                        for message in refreshed.messages
                        if message.created_at >= user_message.created_at
                    )
                    round_prompt = (
                        f"会话资料：{context}\n"
                        + (
                            f"本轮只解决：{'；'.join(focus_points)}\n"
                            if focus_points else ""
                        )
                        + "请只回应仍未解决的分歧，"
                        f"不要重复已经形成的共识：\n{recent}"
                    )
                    reply_to = refreshed.messages[-1].id
                self._run_round(
                    conversation_id,
                    current_roles,
                    round_number=round_number,
                    prompt=round_prompt,
                    reply_to=reply_to,
                    settings=settings,
                    episode_title=episode.title,
                    stop=stop,
                )
                last_round = round_number
                if stop.is_set():
                    return self._mark_stopped(conversation_id)
                if not options.autonomous or len(roles) < 2:
                    self._update_progress(
                        conversation_id, note="本轮无需继续交叉讨论，交由总导演收束",
                    )
                    break
                if round_number >= max_rounds:
                    self._update_progress(
                        conversation_id, note="已达到四轮上限，交由总导演收束",
                    )
                    break
                if self._uses_demo_evaluator(settings):
                    if round_number >= 2:
                        self._update_progress(
                            conversation_id, note="演示讨论已完成两轮，交由总导演收束",
                        )
                        break
                    current_roles = roles[: min(3, len(roles))]
                    self._update_progress(
                        conversation_id, note="演示模式保留一轮交叉回应",
                    )
                    continue
                try:
                    review = self._evaluate_round(
                        conversation_id=conversation_id,
                        user_message=user_message.content,
                        available_roles=roles,
                        settings=settings,
                        round_number=round_number,
                        turn_started_at=user_message.created_at,
                    )
                    note = review.reason or (
                        "仍有关键分歧" if review.continue_discussion else "已形成可收束共识"
                    )
                    self._update_progress(
                        conversation_id,
                        note=note,
                        calls_increment=1,
                    )
                except Exception:  # noqa: BLE001 - evaluator failure should not lose the turn
                    review = DiscussionReview(False, (), (), "轮次判断失败，交由总导演收束")
                    self._update_progress(conversation_id, note=review.reason)
                if not review.continue_discussion:
                    break
                current_roles = review.unresolved_roles or roles[: min(3, len(roles))]
                focus_points = review.unresolved_points

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
                if team is configured:
                    providers = {provider.id: provider for provider in settings.providers}
                    assignments = {assignment.role: assignment for assignment in settings.assignments}
                    draft_calls = sum(
                        providers[assignments[role].provider_id].kind
                        is ProviderKind.OPENAI_COMPATIBLE
                        for role in STAGE_TEAMS[proposal_stage]
                    )
                    self._update_progress(
                        conversation_id, calls_increment=draft_calls,
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
                decision, _, used_external = self._respond(
                    AgentRole.CHIEF_DIRECTOR,
                    f"资料：{context}\n本轮发言：{opinions}\n"
                    "请给出总导演结论、少数意见和下一步；不能把尚未解决的分歧写成共识。",
                    max(1, last_round), settings, episode.title,
                )
                if used_external:
                    self._update_progress(conversation_id, calls_increment=1)
            decision_drafts: tuple[DecisionCardDraft, ...] = ()
            if chief_provider.kind is not ProviderKind.DEMO:
                try:
                    decision_drafts = self._extract_decisions(
                        provider=chief_provider,
                        model=chief_assignment.model,
                        user_request=user_message.content,
                        context=context,
                        opinions=opinions,
                        director_decision=decision,
                    )
                    self._update_progress(conversation_id, calls_increment=1)
                except Exception:  # noqa: BLE001 - a card failure must not lose the discussion
                    decision_drafts = ()
            if stop.is_set():
                return self._mark_stopped(conversation_id)
            current = self._conversations.get(conversation_id)
            module = ConversationModule(current)
            module.complete_turn(
                decision=decision,
                model=chief_assignment.model,
                proposal_stage=proposal_stage,
                proposal_title=proposal_title,
                proposal_payload=proposal_payload,
                decision_drafts=decision_drafts,
                final_round=max(1, last_round),
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
        self._update_progress(
            conversation_id,
            round_number=round_number,
            note=f"第 {round_number} 轮 · {len(roles)} 个专业席位正在交换意见",
        )
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
                content, model, used_external = future.result()
                module = ConversationModule(self._conversations.get(conversation_id))
                module.add_agent_message(
                    role=role,
                    content=content,
                    model=model,
                    round_number=round_number,
                    reply_to=reply_to,
                )
                module.update_discussion_progress(
                    round_number=round_number,
                    calls_increment=1 if used_external else 0,
                )
                self._conversations.save(module.snapshot())

    def _respond(self, role, prompt, round_number, settings, episode_title):
        assignment = next(item for item in settings.assignments if item.role is role)
        provider = next(item for item in settings.providers if item.id == assignment.provider_id)
        if provider.kind is ProviderKind.DEMO:
            return self._demo_response(role, prompt, round_number), assignment.model, False
        api_key = self._model_settings.api_key(provider)
        if not api_key:
            raise RuntimeError(f"{provider.label} 尚未配置 API Key，请打开团队 API 配置")
        profile = effective_profile(assignment)
        completion = OpenAICompatibleAdapter(
            base_url=provider.base_url,
            api_key=api_key,
        ).complete(
            model=assignment.model,
            system_prompt=(
                f"你是中文 AI 漫剧团队的{role.value}。当前项目是《{episode_title}》。"
                f"{profile_instruction(profile)}"
                "像群聊成员一样直接发言，只讨论你的专业判断。不要冒充其他角色。"
                "默认用150到300个中文字符完成发言，并依次写清“结论、依据、风险或异议、"
                "建议动作”。确有必要时，把补充材料放在“详细说明”之后；不要靠复述凑长度。"
            ),
            user_prompt=prompt,
            max_tokens=900,
            temperature=profile_temperature(profile),
        )
        return completion.text.strip(), completion.model, True

    def _evaluate_round(
        self,
        *,
        conversation_id: str,
        user_message: str,
        available_roles: tuple[AgentRole, ...],
        settings: ModelSettings,
        round_number: int,
        turn_started_at: datetime,
    ) -> DiscussionReview:
        assignment = next(
            item for item in settings.assignments
            if item.role is AgentRole.CHIEF_DIRECTOR
        )
        provider = next(
            item for item in settings.providers if item.id == assignment.provider_id
        )
        api_key = self._model_settings.api_key(provider)
        if not api_key:
            raise RuntimeError(f"{provider.label} 尚未配置 API Key")
        conversation = self._conversations.get(conversation_id)
        transcript = "\n".join(
            f"R{message.round} {message.sender_name}：{message.content}"
            for message in conversation.messages
            if message.kind.value == "agent"
            and message.created_at >= turn_started_at
            and message.round <= round_number
        )
        completion = OpenAICompatibleAdapter(
            base_url=provider.base_url,
            api_key=api_key,
        ).complete(
            model=assignment.model,
            system_prompt=(
                "你是导演会议的轮次控制员。判断关键创作问题是否仍有真实分歧。"
                "已经形成共识、开始重复、或剩余只是执行细节时必须停止。"
                "只有影响叙事、视听方向或制作约束的未决矛盾才继续。"
                "严格输出JSON对象，不要Markdown："
                '{"continue":false,"unresolved_roles":[],"unresolved_points":[],"reason":""}'
            ),
            user_prompt=(
                f"用户任务：{user_message}\n当前已完成第{round_number}轮。\n"
                f"可继续发言角色：{','.join(role.value for role in available_roles)}\n"
                f"会议记录：\n{transcript}\n"
                "若继续，只列出确实需要回应的角色；reason用一句中文说明。"
            ),
            json_mode=True,
            max_tokens=500,
            temperature=0.1,
        )
        return self._parse_discussion_review(completion.text, available_roles)

    @staticmethod
    def _parse_discussion_review(
        text: str,
        available_roles: tuple[AgentRole, ...],
    ) -> DiscussionReview:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        payload = json.loads(cleaned.strip())
        allowed = set(available_roles)
        parsed_roles = []
        for value in payload.get("unresolved_roles", []):
            try:
                role = AgentRole(value)
            except (TypeError, ValueError):
                continue
            if role in allowed and role not in parsed_roles:
                parsed_roles.append(role)
        unresolved_roles = tuple(parsed_roles)
        unresolved_points = tuple(
            str(value).strip()
            for value in payload.get("unresolved_points", [])
            if str(value).strip()
        )[:4]
        should_continue = bool(payload.get("continue")) and bool(unresolved_roles)
        return DiscussionReview(
            continue_discussion=should_continue,
            unresolved_roles=unresolved_roles,
            unresolved_points=unresolved_points,
            reason=str(payload.get("reason", "")).strip()[:120],
        )

    def _uses_demo_evaluator(self, settings: ModelSettings) -> bool:
        assignment = next(
            item for item in settings.assignments
            if item.role is AgentRole.CHIEF_DIRECTOR
        )
        provider = next(
            item for item in settings.providers if item.id == assignment.provider_id
        )
        return provider.kind is ProviderKind.DEMO

    def _update_progress(
        self,
        conversation_id: str,
        *,
        round_number: int | None = None,
        note: str | None = None,
        calls_increment: int = 0,
    ) -> None:
        module = ConversationModule(self._conversations.get(conversation_id))
        module.update_discussion_progress(
            round_number=round_number,
            note=note,
            calls_increment=calls_increment,
        )
        self._conversations.save(module.snapshot())

    def _extract_decisions(
        self,
        *,
        provider,
        model: str,
        user_request: str,
        context: str,
        opinions: str,
        director_decision: str,
    ) -> tuple[DecisionCardDraft, ...]:
        api_key = self._model_settings.api_key(provider)
        if not api_key:
            return ()
        completion = OpenAICompatibleAdapter(
            base_url=provider.base_url,
            api_key=api_key,
        ).complete(
            model=model,
            system_prompt=(
                "你是中文 AI 漫剧项目的决策编辑。只提取必须由用户拍板的高影响创作分岔；"
                "执行细节由团队自行决定。最多输出3项，若没有则输出空数组。"
                "每项必须有2到4个互斥方案、恰好一个推荐方案，并说明影响和风险。"
                "scope只能是project或episode；category只能是theme_audience、world_rule、"
                "character、story_timeline、scene_prop、visual_asset、shot_duration、"
                "voice_music、production_constraint、open_question。"
                "严格输出JSON对象，不要Markdown："
                '{"decisions":[{"question":"","context":"","scope":"episode",'
                '"category":"open_question","options":[{"label":"","description":"",'
                '"impact":"","risk":"","recommended":true}]}]}'
            ),
            user_prompt=(
                f"用户请求：{user_request}\n项目与已确认事实：{context}\n"
                f"本轮专业意见：{opinions}\n总导演结论：{director_decision}\n"
                "不要重复已有待决策项，不要把已经由规则唯一决定的事项升级给用户。"
            ),
            json_mode=True,
            max_tokens=1800,
        )
        return parse_decision_drafts(completion.text)

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
        if round_number > 1:
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
