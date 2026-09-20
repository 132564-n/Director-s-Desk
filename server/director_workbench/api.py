from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from threading import Event
from typing import Annotated, Literal
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi import Path as PathParameter
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .chat import ChatMode, ConversationModule, ProposalStatus, create_conversation
from .chat_engine import GroupChatEngine, TurnOptions
from .chat_repository import ConversationRepository, SqliteConversationRepository
from .configured_drafting import ConfiguredDirectorTeam, artifact_from_payload
from .domain import (
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
)
from .drafting import AgentRole, DemoDirectorTeam
from .exporting import build_episode_package
from .model_gateway import OpenAICompatibleAdapter
from .model_settings import (
    AgentModelSettings,
    AgentWorkProfile,
    LocalModelSettingsStore,
    ModelSettings,
    ProviderKind,
    ProviderSettings,
)
from .repository import SqliteWorkflowRepository, WorkflowRepository
from .workflow import ProductionWorkflow, WorkflowError, WorkflowView


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectSettingsInput(StrictModel):
    target_duration_seconds: int = Field(gt=0)
    prompt_language: PromptLanguage = PromptLanguage.CHINESE
    max_shot_duration_seconds: float | None = Field(default=None, gt=0)


class AssetInput(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: AssetKind
    policy: AssetPolicy
    confirmed: bool = False
    description: str = ""
    source_path: str = ""
    mime_type: str = ""


class CreateEpisodeInput(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    title: str = Field(min_length=1)
    settings: ProjectSettingsInput
    assets: list[AssetInput] = Field(default_factory=list)


class OutlineInput(StrictModel):
    title: str = Field(min_length=1)
    logline: str = Field(min_length=1)
    beats: list[str] = Field(min_length=1)
    author: str = Field(min_length=1)


class SceneInput(StrictModel):
    id: str = Field(min_length=1)
    heading: str = Field(min_length=1)
    action: str
    dialogue: list[str] = Field(default_factory=list)


class ScriptInput(StrictModel):
    scenes: list[SceneInput] = Field(min_length=1)
    author: str = Field(min_length=1)


class ShotInput(StrictModel):
    id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    estimated_duration_seconds: float = Field(gt=0)
    visual_description: str = Field(min_length=1)
    standard_prompt: str = Field(min_length=1)
    asset_ids: list[str] = Field(default_factory=list)
    camera: str = ""
    dialogue: str = ""
    voice_direction: str = ""
    music_direction: str = ""


class DirectionInput(StrictModel):
    shots: list[ShotInput] = Field(min_length=1)
    author: str = Field(min_length=1)


class ReviewInput(StrictModel):
    reviewer: str = Field(min_length=1)
    note: str = ""


class ChangeRequestInput(StrictModel):
    reviewer: str = Field(min_length=1)
    note: str = Field(min_length=1)


class ConfirmAssetInput(StrictModel):
    description: str = Field(min_length=1)
    policy: AssetPolicy


class ProviderSettingsInput(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
    label: str = Field(min_length=1)
    kind: ProviderKind
    base_url: str = ""
    api_key_env: str = ""
    api_key: SecretStr | None = None
    api_key_set: bool = False


class TestModelInput(StrictModel):
    provider_id: str
    model: str = Field(min_length=1, max_length=200)


class AgentModelSettingsInput(StrictModel):
    role: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    profile: AgentWorkProfile | None = None


class ModelSettingsInput(StrictModel):
    providers: list[ProviderSettingsInput] = Field(min_length=1)
    assignments: list[AgentModelSettingsInput] = Field(min_length=1)


class CreateConversationInput(StrictModel):
    episode_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    members: list[AgentRole] = Field(min_length=1)
    template: str = "自由讨论"


class ConversationUpdateInput(StrictModel):
    title: str | None = Field(default=None, min_length=1)
    pinned: bool | None = None
    archived: bool | None = None


class SendMessageInput(StrictModel):
    content: str = Field(min_length=1)
    mode: ChatMode = ChatMode.DISCUSS
    autonomous: bool = False
    mentions: list[AgentRole] = Field(default_factory=list)
    reply_to: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)


class ResolveDecisionInput(StrictModel):
    action: Literal["confirm", "defer", "reject"]
    option_id: str | None = None
    custom_value: str = Field(default="", max_length=2000)


StagePath = Annotated[Stage, PathParameter(description="Production stage")]


def _response(view: WorkflowView) -> dict:
    return jsonable_encoder(asdict(view))


def create_app(
    repository: WorkflowRepository,
    *,
    data_root: Path = Path("data"),
    conversation_repository: ConversationRepository | None = None,
) -> FastAPI:
    director_team = DemoDirectorTeam()
    data_root.mkdir(parents=True, exist_ok=True)
    model_settings_store = LocalModelSettingsStore(data_root / "model-settings.json")
    conversations = conversation_repository or SqliteConversationRepository(
        data_root / "database.sqlite"
    )
    chat_engine = GroupChatEngine(
        conversations=conversations,
        workflows=repository,
        model_settings=model_settings_store,
    )
    active_stops: dict[str, Event] = {}
    app = FastAPI(
        title="AI 导演工作台",
        version="0.1.0",
        description="中文 AI 漫剧的多 Agent 制作流程接口",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    media_root = data_root / "projects"
    media_root.mkdir(parents=True, exist_ok=True)
    app.mount("/media/projects", StaticFiles(directory=media_root), name="media")

    @app.middleware("http")
    async def protect_settings(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.url.path.startswith("/settings/") and origin and origin not in {
            "http://127.0.0.1:3000", "http://localhost:3000",
            "http://127.0.0.1:8000", "http://localhost:8000",
        }:
            return Response(status_code=403)
        return await call_next(request)
    app.state.workflows = repository
    app.state.conversations = conversations

    def find_workflow(episode_id: str) -> ProductionWorkflow:
        try:
            return repository.get(episode_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    def run_transition(workflow: ProductionWorkflow, operation) -> dict:
        try:
            view = operation()
            repository.save(workflow)
            return _response(view)
        except WorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    def find_conversation(conversation_id: str):
        try:
            return conversations.get(conversation_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    def conversation_response(conversation) -> dict:
        return jsonable_encoder(asdict(conversation))

    @app.get("/health", tags=["system"])
    def health() -> dict[str, Literal["ok"]]:
        return {"status": "ok"}

    @app.get("/settings/models", tags=["settings"])
    def get_model_settings() -> dict:
        return jsonable_encoder(model_settings_store.public_settings())

    @app.put("/settings/models", tags=["settings"])
    def update_model_settings(body: ModelSettingsInput) -> dict:
        from .drafting import AgentRole

        try:
            settings = ModelSettings(
                providers=tuple(
                    ProviderSettings(**provider.model_dump(exclude={"api_key", "api_key_set"}))
                    for provider in body.providers
                ),
                assignments=tuple(
                    AgentModelSettings(
                        role=AgentRole(assignment.role),
                        provider_id=assignment.provider_id,
                        model=assignment.model,
                        profile=assignment.profile,
                    )
                    for assignment in body.assignments
                ),
            )
            model_settings_store.save(settings, api_keys={
                provider.id: provider.api_key.get_secret_value()
                for provider in body.providers if provider.api_key is not None
            })
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return get_model_settings()

    @app.post("/settings/models/test", tags=["settings"])
    def test_model_connection(body: TestModelInput) -> dict:
        settings = model_settings_store.load()
        provider = next((item for item in settings.providers if item.id == body.provider_id), None)
        if provider is None:
            raise HTTPException(404, "请先保存供应商配置")
        if provider.kind is ProviderKind.DEMO:
            return {"ok": True, "message": "本地演示模型可用，未发起外部请求"}
        try:
            key = model_settings_store.api_key(provider)
            if not key:
                raise HTTPException(409, "请先保存 API Key 或设置环境变量")
            with httpx.Client(timeout=20) as client:
                OpenAICompatibleAdapter(
                    base_url=provider.base_url, api_key=key, client=client,
                ).complete(
                    model=body.model, system_prompt="连接测试，只回复 OK。",
                    user_prompt="OK", max_tokens=8,
                )
            return {"ok": True, "message": "连接成功，模型可用"}
        except httpx.HTTPStatusError as error:
            code = error.response.status_code
            hint = "请检查密钥或访问权限" if code in {401, 403} else "请检查接口地址、模型名或供应商额度"
            raise HTTPException(502, f"供应商返回 HTTP {code}，{hint}") from None
        except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
            raise HTTPException(502, "连接失败或响应格式不兼容，请检查网络与接口配置") from None

    @app.post("/episodes", status_code=201, tags=["episodes"])
    def create_episode(body: CreateEpisodeInput) -> dict:
        settings = ProjectSettings(**body.settings.model_dump())
        assets = {
            item.id: Asset(**item.model_dump())
            for item in body.assets
        }
        try:
            workflow = repository.create(
                Episode(id=body.id, title=body.title, settings=settings, assets=assets)
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _response(workflow.snapshot())

    @app.get("/episodes", tags=["episodes"])
    def list_episodes() -> list[dict]:
        return [
            {
                "id": episode.id,
                "title": episode.title,
                "target_duration_seconds": episode.settings.target_duration_seconds,
                "active_stage": next(
                    (
                        stage.value
                        for stage in Stage
                        if episode.stages[stage].status.value
                        in {"ready", "in_review", "changes_requested", "stale"}
                    ),
                    None,
                ),
                "stage_statuses": {
                    stage.value: episode.stages[stage].status.value for stage in Stage
                },
            }
            for episode in repository.list()
        ]

    @app.get("/episodes/{episode_id}", tags=["episodes"])
    def get_episode(episode_id: str) -> dict:
        return _response(find_workflow(episode_id).snapshot())

    @app.get("/conversations", tags=["chat"])
    def list_conversations(episode_id: str | None = None) -> list[dict]:
        return [
            conversation_response(conversation)
            for conversation in conversations.list(episode_id)
        ]

    @app.post("/conversations", status_code=201, tags=["chat"])
    def new_conversation(body: CreateConversationInput) -> dict:
        find_workflow(body.episode_id)
        conversation = create_conversation(
            episode_id=body.episode_id,
            title=body.title,
            goal=body.goal,
            members=tuple(body.members),
            template=body.template,
        )
        try:
            conversations.create(conversation)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return conversation_response(conversation)

    @app.get("/conversations/{conversation_id}", tags=["chat"])
    def get_conversation(conversation_id: str) -> dict:
        return conversation_response(find_conversation(conversation_id))

    @app.patch("/conversations/{conversation_id}", tags=["chat"])
    def update_conversation(
        conversation_id: str,
        body: ConversationUpdateInput,
    ) -> dict:
        module = ConversationModule(find_conversation(conversation_id))
        module.update_metadata(
            title=body.title,
            pinned=body.pinned,
            archived=body.archived,
        )
        conversation = module.snapshot()
        conversations.save(conversation)
        return conversation_response(conversation)

    @app.post("/conversations/{conversation_id}/messages", status_code=202, tags=["chat"])
    def send_message(
        conversation_id: str,
        body: SendMessageInput,
        background_tasks: BackgroundTasks,
    ) -> dict:
        conversation = find_conversation(conversation_id)
        unknown_mentions = set(body.mentions) - set(conversation.members)
        if unknown_mentions:
            raise HTTPException(
                status_code=422,
                detail=f"以下 Agent 不在本会话：{', '.join(role.value for role in unknown_mentions)}",
            )
        unknown_assets = set(body.attachment_ids) - set(
            find_workflow(conversation.episode_id).snapshot().episode.assets
        )
        if unknown_assets:
            raise HTTPException(
                status_code=422,
                detail=f"附件资产不存在：{', '.join(sorted(unknown_assets))}",
            )
        module = ConversationModule(conversation)
        try:
            user_message = module.begin_turn(
                content=body.content,
                mode=body.mode,
                autonomous=body.autonomous,
                mentions=tuple(body.mentions),
                reply_to=body.reply_to,
                attachment_ids=tuple(body.attachment_ids),
            )
        except WorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        conversation = module.snapshot()
        conversations.save(conversation)
        stop = Event()
        active_stops[conversation_id] = stop

        def run_turn() -> None:
            try:
                chat_engine.run(
                    conversation_id,
                    TurnOptions(
                        user_message_id=user_message.id,
                        mode=body.mode,
                        autonomous=body.autonomous,
                        mentions=tuple(body.mentions),
                    ),
                    stop,
                )
            finally:
                active_stops.pop(conversation_id, None)

        background_tasks.add_task(run_turn)
        return conversation_response(conversation)

    @app.post("/conversations/{conversation_id}/stop", tags=["chat"])
    def stop_conversation(conversation_id: str) -> dict:
        conversation = find_conversation(conversation_id)
        stop = active_stops.get(conversation_id)
        if stop is not None:
            stop.set()
        if conversation.status.value == "running":
            module = ConversationModule(conversation)
            module.stop()
            conversation = module.snapshot()
            conversations.save(conversation)
        return conversation_response(conversation)

    @app.post(
        "/conversations/{conversation_id}/decisions/{decision_id}/resolve",
        tags=["chat"],
    )
    def resolve_decision(
        conversation_id: str,
        decision_id: str,
        body: ResolveDecisionInput,
    ) -> dict:
        current = find_conversation(conversation_id)
        card = current.decisions.get(decision_id)
        if card is None:
            raise HTTPException(status_code=404, detail=f"决策 {decision_id} 不存在")
        affected_artifacts: tuple[str, ...] = ()
        if card.status.value == "confirmed" and body.action in {"confirm", "reject"}:
            episode = find_workflow(current.episode_id).snapshot().episode
            affected_artifacts = tuple(
                stage.value
                for stage, state in episode.stages.items()
                if state.artifact is not None
            )
        module = ConversationModule(current)
        try:
            module.resolve_decision(
                decision_id,
                action=body.action,
                option_id=body.option_id,
                custom_value=body.custom_value,
                affected_artifacts=affected_artifacts,
            )
        except WorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        conversation = module.snapshot()
        conversations.save(conversation)
        return conversation_response(conversation)

    def set_proposal_status(
        conversation_id: str,
        proposal_id: str,
        status: ProposalStatus,
    ) -> dict:
        module = ConversationModule(find_conversation(conversation_id))
        try:
            module.set_proposal_status(proposal_id, status)
        except WorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        conversation = module.snapshot()
        conversations.save(conversation)
        return conversation_response(conversation)

    @app.post(
        "/conversations/{conversation_id}/proposals/{proposal_id}/adopt",
        tags=["chat"],
    )
    def adopt_proposal(conversation_id: str, proposal_id: str) -> dict:
        conversation = find_conversation(conversation_id)
        proposal = conversation.proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail=f"提案 {proposal_id} 不存在")
        if proposal.status not in {
            ProposalStatus.PENDING,
            ProposalStatus.REVISION_REQUESTED,
        }:
            raise HTTPException(status_code=409, detail="只有待处理或待修改提案可以采纳")
        return set_proposal_status(conversation_id, proposal_id, ProposalStatus.ADOPTED)

    @app.post(
        "/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        tags=["chat"],
    )
    def confirm_proposal(conversation_id: str, proposal_id: str) -> dict:
        conversation = find_conversation(conversation_id)
        proposal = conversation.proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail=f"提案 {proposal_id} 不存在")
        if proposal.status is not ProposalStatus.ADOPTED:
            raise HTTPException(status_code=409, detail="请先将提案采纳为草案")
        workflow = find_workflow(conversation.episode_id)
        try:
            artifact = artifact_from_payload(proposal.stage, proposal.payload)
            workflow.submit(artifact, author="群聊导演团队")
            workflow.approve(proposal.stage, reviewer="用户", note="从群聊确认版本")
            repository.save(workflow)
        except (KeyError, TypeError, ValueError, WorkflowError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return set_proposal_status(conversation_id, proposal_id, ProposalStatus.CONFIRMED)

    @app.post(
        "/conversations/{conversation_id}/proposals/{proposal_id}/revise",
        tags=["chat"],
    )
    def revise_proposal(conversation_id: str, proposal_id: str) -> dict:
        conversation = find_conversation(conversation_id)
        proposal = conversation.proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail=f"提案 {proposal_id} 不存在")
        if proposal.status is ProposalStatus.CONFIRMED:
            raise HTTPException(status_code=409, detail="正式版本不能退回提案状态，请发起新提案")
        return set_proposal_status(
            conversation_id,
            proposal_id,
            ProposalStatus.REVISION_REQUESTED,
        )

    @app.get("/episodes/{episode_id}/shelf", tags=["chat"])
    def get_episode_shelf(episode_id: str) -> dict:
        episode = find_workflow(episode_id).snapshot().episode
        proposals = [
            proposal
            for conversation in conversations.list(episode_id)
            for proposal in conversation.proposals.values()
        ]
        decisions = [
            decision
            for conversation in conversations.list(episode_id)
            for decision in conversation.decisions.values()
        ]
        decisions.sort(
            key=lambda item: (
                item.status.value not in {"pending", "needs_review"},
                -item.created_at.timestamp(),
            )
        )
        artifacts = [
            state.artifact
            for state in episode.stages.values()
            if state.artifact is not None
        ]
        return jsonable_encoder(
            {
                "proposals": [asdict(proposal) for proposal in proposals],
                "decisions": [asdict(decision) for decision in decisions],
                "artifacts": [asdict(artifact) for artifact in artifacts],
                "assets": [asdict(asset) for asset in episode.assets.values()],
            }
        )

    @app.get("/episodes/{episode_id}/export", tags=["episodes"])
    def export_episode(episode_id: str) -> Response:
        episode = find_workflow(episode_id).snapshot().episode
        content = build_episode_package(episode, data_root=data_root)
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{episode.id}-director-package.zip"'
            },
        )

    @app.post("/episodes/{episode_id}/assets", status_code=201, tags=["assets"])
    async def upload_asset(
        episode_id: str,
        file: Annotated[UploadFile, File()],
        name: Annotated[str, Form(min_length=1)],
        kind: Annotated[AssetKind, Form()],
        policy: Annotated[AssetPolicy, Form()] = AssetPolicy.REFERENCE,
    ) -> dict:
        workflow = find_workflow(episode_id)
        extension_by_mime = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        extension = extension_by_mime.get(file.content_type or "")
        if extension is None:
            raise HTTPException(status_code=415, detail="仅支持 JPG、PNG、WebP 或 GIF 图片")
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="资产图片不能超过 10 MB")

        asset_id = f"asset-{uuid4().hex[:12]}"
        relative_path = Path("projects") / episode_id / "assets" / f"{asset_id}{extension}"
        target = data_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        asset = Asset(
            id=asset_id,
            name=name,
            kind=kind,
            policy=policy,
            confirmed=False,
            source_path=relative_path.as_posix(),
            mime_type=file.content_type or "",
        )
        try:
            view = workflow.register_asset(asset)
            repository.save(workflow)
        except WorkflowError as error:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _response(view)

    @app.post("/episodes/{episode_id}/assets/{asset_id}/confirm", tags=["assets"])
    def confirm_asset(episode_id: str, asset_id: str, body: ConfirmAssetInput) -> dict:
        workflow = find_workflow(episode_id)
        return run_transition(
            workflow,
            lambda: workflow.confirm_asset(
                asset_id,
                description=body.description,
                policy=body.policy,
            ),
        )

    @app.post("/episodes/{episode_id}/draft/{stage}", tags=["agents"])
    def draft_stage(episode_id: str, stage: StagePath) -> dict:
        episode = find_workflow(episode_id).snapshot().episode
        try:
            settings = model_settings_store.load()
            configured_team = ConfiguredDirectorTeam(
                settings, api_keys=model_settings_store.api_keys(settings),
            )
            team = configured_team if configured_team.uses_external_models(stage) else director_team
            result = team.draft(episode, stage)
        except WorkflowError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return jsonable_encoder(asdict(result))

    @app.post("/episodes/{episode_id}/outline", tags=["workflow"])
    def submit_outline(episode_id: str, body: OutlineInput) -> dict:
        workflow = find_workflow(episode_id)
        package = OutlinePackage(
            title=body.title,
            logline=body.logline,
            beats=tuple(body.beats),
        )
        return run_transition(workflow, lambda: workflow.submit(package, author=body.author))

    @app.post("/episodes/{episode_id}/script", tags=["workflow"])
    def submit_script(episode_id: str, body: ScriptInput) -> dict:
        workflow = find_workflow(episode_id)
        package = ScriptPackage(
            scenes=tuple(
                Scene(
                    id=item.id,
                    heading=item.heading,
                    action=item.action,
                    dialogue=tuple(item.dialogue),
                )
                for item in body.scenes
            )
        )
        return run_transition(workflow, lambda: workflow.submit(package, author=body.author))

    @app.post("/episodes/{episode_id}/direction", tags=["workflow"])
    def submit_direction(episode_id: str, body: DirectionInput) -> dict:
        workflow = find_workflow(episode_id)
        package = DirectionPackage(
            shots=tuple(
                Shot(
                    id=item.id,
                    scene_id=item.scene_id,
                    title=item.title,
                    estimated_duration_seconds=item.estimated_duration_seconds,
                    visual_description=item.visual_description,
                    standard_prompt=item.standard_prompt,
                    asset_ids=tuple(item.asset_ids),
                    camera=item.camera,
                    dialogue=item.dialogue,
                    voice_direction=item.voice_direction,
                    music_direction=item.music_direction,
                )
                for item in body.shots
            )
        )
        return run_transition(workflow, lambda: workflow.submit(package, author=body.author))

    @app.post("/episodes/{episode_id}/stages/{stage}/approve", tags=["workflow"])
    def approve_stage(episode_id: str, stage: StagePath, body: ReviewInput) -> dict:
        workflow = find_workflow(episode_id)
        return run_transition(
            workflow,
            lambda: workflow.approve(stage, reviewer=body.reviewer, note=body.note)
        )

    @app.post("/episodes/{episode_id}/stages/{stage}/request-changes", tags=["workflow"])
    def request_stage_changes(
        episode_id: str,
        stage: StagePath,
        body: ChangeRequestInput,
    ) -> dict:
        workflow = find_workflow(episode_id)
        return run_transition(
            workflow,
            lambda: workflow.request_changes(
                stage,
                reviewer=body.reviewer,
                note=body.note,
            )
        )

    return app


app = create_app(
    SqliteWorkflowRepository(Path("data/database.sqlite")),
    conversation_repository=SqliteConversationRepository(Path("data/database.sqlite")),
)


def run() -> None:
    import uvicorn

    uvicorn.run("server.director_workbench.api:app", host="127.0.0.1", port=8000, reload=False)
