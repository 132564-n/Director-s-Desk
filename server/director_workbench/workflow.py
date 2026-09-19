from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from .domain import (
    STAGE_ORDER,
    ApprovalRecord,
    Artifact,
    Asset,
    AssetPolicy,
    DirectionPackage,
    Episode,
    Stage,
    StageStatus,
    VersionedArtifact,
)


class WorkflowError(ValueError):
    """Raised when a production workflow invariant would be violated."""


@dataclass(frozen=True, slots=True)
class WorkflowView:
    episode: Episode
    active_stage: Stage | None
    complete: bool


class ProductionWorkflow:
    """Owns every state transition for a single episode production workflow.

    Callers submit artifacts, approve them, request changes, and read snapshots.
    Ordering, validation, revisioning, and downstream invalidation stay private.
    """

    def __init__(
        self,
        episode: Episode,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._episode = deepcopy(episode)
        self._clock = clock or (lambda: datetime.now(UTC))

    def submit(self, artifact: Artifact, *, author: str) -> WorkflowView:
        stage = artifact.stage
        self._require_stage_unblocked(stage)
        self._require_previous_stage_approved(stage)
        self._validate_artifact(artifact)

        current = self._episode.stages[stage]
        revision = 1 if current.artifact is None else current.artifact.revision + 1
        current.artifact = VersionedArtifact(
            stage=stage,
            revision=revision,
            author=author,
            payload=artifact,
            submitted_at=self._clock(),
        )
        current.status = StageStatus.IN_REVIEW
        current.review_note = ""
        self._invalidate_downstream(stage)
        return self.snapshot()

    def register_asset(self, asset: Asset) -> WorkflowView:
        if asset.id in self._episode.assets:
            raise WorkflowError(f"资产 {asset.id} 已存在")
        self._episode.assets[asset.id] = asset
        return self.snapshot()

    def confirm_asset(
        self,
        asset_id: str,
        *,
        description: str,
        policy: AssetPolicy,
    ) -> WorkflowView:
        try:
            asset = self._episode.assets[asset_id]
        except KeyError as error:
            raise WorkflowError(f"资产 {asset_id} 不存在") from error
        if not description.strip():
            raise WorkflowError("确认资产前必须填写可执行的视觉描述")
        self._episode.assets[asset_id] = replace(
            asset,
            confirmed=True,
            description=description.strip(),
            policy=policy,
        )
        return self.snapshot()

    def approve(self, stage: Stage, *, reviewer: str, note: str = "") -> WorkflowView:
        state = self._episode.stages[stage]
        if state.status is not StageStatus.IN_REVIEW or state.artifact is None:
            raise WorkflowError(f"{stage.value} 阶段没有可批准的待审版本")

        state.status = StageStatus.APPROVED
        state.review_note = note
        self._episode.approvals.append(
            ApprovalRecord(
                stage=stage,
                revision=state.artifact.revision,
                reviewer=reviewer,
                note=note,
                approved_at=self._clock(),
            )
        )
        self._unlock_next_stage(stage)
        return self.snapshot()

    def request_changes(
        self,
        stage: Stage,
        *,
        reviewer: str,
        note: str,
    ) -> WorkflowView:
        del reviewer  # Reserved for the persisted review event in the next adapter.
        if not note.strip():
            raise WorkflowError("请求修改时必须说明原因")
        state = self._episode.stages[stage]
        if state.status not in {StageStatus.IN_REVIEW, StageStatus.APPROVED}:
            raise WorkflowError(f"{stage.value} 阶段当前不能请求修改")
        state.status = StageStatus.CHANGES_REQUESTED
        state.review_note = note
        self._invalidate_downstream(stage)
        return self.snapshot()

    def snapshot(self) -> WorkflowView:
        episode = deepcopy(self._episode)
        active_stage = next(
            (
                stage
                for stage in STAGE_ORDER
                if episode.stages[stage].status
                in {
                    StageStatus.READY,
                    StageStatus.IN_REVIEW,
                    StageStatus.CHANGES_REQUESTED,
                    StageStatus.STALE,
                }
            ),
            None,
        )
        complete = all(
            episode.stages[stage].status is StageStatus.APPROVED for stage in STAGE_ORDER
        )
        return WorkflowView(episode=episode, active_stage=active_stage, complete=complete)

    def _require_stage_unblocked(self, stage: Stage) -> None:
        if self._episode.stages[stage].status is StageStatus.BLOCKED:
            raise WorkflowError(f"{stage.value} 阶段尚未解锁")

    def _require_previous_stage_approved(self, stage: Stage) -> None:
        index = STAGE_ORDER.index(stage)
        if index == 0:
            return
        previous = STAGE_ORDER[index - 1]
        if self._episode.stages[previous].status is not StageStatus.APPROVED:
            raise WorkflowError(f"必须先批准 {previous.value} 阶段")

    def _validate_artifact(self, artifact: Artifact) -> None:
        if not isinstance(artifact, DirectionPackage):
            return

        scene_ids = {
            scene.id
            for scene in self._episode.stages[Stage.SCRIPT].artifact.payload.scenes  # type: ignore[union-attr]
        }
        known_assets = self._episode.assets
        max_duration = self._episode.settings.max_shot_duration_seconds

        for shot in artifact.shots:
            if shot.scene_id not in scene_ids:
                raise WorkflowError(f"镜头 {shot.id} 引用了不存在的场次 {shot.scene_id}")
            if max_duration is not None and shot.estimated_duration_seconds > max_duration:
                raise WorkflowError(
                    f"镜头 {shot.id} 预计 {shot.estimated_duration_seconds:g} 秒，"
                    f"超过项目上限 {max_duration:g} 秒，必须拆镜"
                )
            for asset_id in shot.asset_ids:
                asset = known_assets.get(asset_id)
                if asset is None:
                    raise WorkflowError(f"镜头 {shot.id} 引用了不存在的资产 {asset_id}")
                if not asset.confirmed:
                    raise WorkflowError(f"镜头 {shot.id} 引用了尚未确认的资产 {asset_id}")

    def _invalidate_downstream(self, stage: Stage) -> None:
        index = STAGE_ORDER.index(stage)
        for downstream in STAGE_ORDER[index + 1 :]:
            state = self._episode.stages[downstream]
            if state.artifact is not None:
                state.status = StageStatus.STALE
            else:
                state.status = StageStatus.BLOCKED

    def _unlock_next_stage(self, stage: Stage) -> None:
        index = STAGE_ORDER.index(stage)
        if index == len(STAGE_ORDER) - 1:
            return
        next_stage = STAGE_ORDER[index + 1]
        state = self._episode.stages[next_stage]
        if state.artifact is None:
            state.status = StageStatus.READY
        elif state.status is StageStatus.STALE:
            state.status = StageStatus.STALE
