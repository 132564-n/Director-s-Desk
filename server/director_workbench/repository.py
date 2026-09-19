from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

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
    StageState,
    StageStatus,
    VersionedArtifact,
)
from .workflow import ProductionWorkflow


class WorkflowRepository(Protocol):
    def create(self, episode: Episode) -> ProductionWorkflow: ...

    def get(self, episode_id: str) -> ProductionWorkflow: ...

    def list(self) -> tuple[Episode, ...]: ...

    def save(self, workflow: ProductionWorkflow) -> None: ...


class InMemoryWorkflowRepository:
    def __init__(self) -> None:
        self._documents: dict[str, str] = {}

    def create(self, episode: Episode) -> ProductionWorkflow:
        if episode.id in self._documents:
            raise ValueError(f"单集 {episode.id} 已存在")
        workflow = ProductionWorkflow(episode)
        self.save(workflow)
        return workflow

    def get(self, episode_id: str) -> ProductionWorkflow:
        try:
            document = self._documents[episode_id]
        except KeyError as error:
            raise KeyError(f"单集 {episode_id} 不存在") from error
        return ProductionWorkflow(_episode_from_json(document))

    def list(self) -> tuple[Episode, ...]:
        return tuple(_episode_from_json(document) for document in self._documents.values())

    def save(self, workflow: ProductionWorkflow) -> None:
        episode = workflow.snapshot().episode
        self._documents[episode.id] = _episode_to_json(episode)


class SqliteWorkflowRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(self, episode: Episode) -> ProductionWorkflow:
        workflow = ProductionWorkflow(episode)
        document = _episode_to_json(workflow.snapshot().episode)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO episodes (id, document) VALUES (?, ?)",
                    (episode.id, document),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError(f"单集 {episode.id} 已存在") from error
        return workflow

    def get(self, episode_id: str) -> ProductionWorkflow:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM episodes WHERE id = ?",
                (episode_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"单集 {episode_id} 不存在")
        return ProductionWorkflow(_episode_from_json(row[0]))

    def list(self) -> tuple[Episode, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT document FROM episodes ORDER BY id").fetchall()
        return tuple(_episode_from_json(row[0]) for row in rows)

    def save(self, workflow: ProductionWorkflow) -> None:
        episode = workflow.snapshot().episode
        document = _episode_to_json(episode)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE episodes SET document = ? WHERE id = ?",
                (document, episode.id),
            )
            updated_rows = cursor.rowcount
        if updated_rows != 1:
            raise KeyError(f"单集 {episode.id} 不存在")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    document TEXT NOT NULL
                )
                """
            )


def _episode_to_json(episode: Episode) -> str:
    document = {
        "id": episode.id,
        "title": episode.title,
        "settings": {
            "target_duration_seconds": episode.settings.target_duration_seconds,
            "prompt_language": episode.settings.prompt_language.value,
            "max_shot_duration_seconds": episode.settings.max_shot_duration_seconds,
        },
        "assets": [
            {
                **asdict(asset),
                "kind": asset.kind.value,
                "policy": asset.policy.value,
            }
            for asset in episode.assets.values()
        ],
        "stages": {
            stage.value: {
                "status": state.status.value,
                "review_note": state.review_note,
                "artifact": _artifact_to_document(state.artifact),
            }
            for stage, state in episode.stages.items()
        },
        "approvals": [
            {
                "stage": approval.stage.value,
                "revision": approval.revision,
                "reviewer": approval.reviewer,
                "note": approval.note,
                "approved_at": approval.approved_at.isoformat(),
            }
            for approval in episode.approvals
        ],
    }
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def _artifact_to_document(artifact: VersionedArtifact | None) -> dict | None:
    if artifact is None:
        return None
    if isinstance(artifact.payload, OutlinePackage):
        payload = {
            "title": artifact.payload.title,
            "logline": artifact.payload.logline,
            "beats": list(artifact.payload.beats),
        }
    elif isinstance(artifact.payload, ScriptPackage):
        payload = {
            "scenes": [
                {
                    "id": scene.id,
                    "heading": scene.heading,
                    "action": scene.action,
                    "dialogue": list(scene.dialogue),
                }
                for scene in artifact.payload.scenes
            ]
        }
    else:
        payload = {
            "shots": [
                {
                    **asdict(shot),
                    "asset_ids": list(shot.asset_ids),
                }
                for shot in artifact.payload.shots
            ]
        }
    return {
        "stage": artifact.stage.value,
        "revision": artifact.revision,
        "author": artifact.author,
        "submitted_at": artifact.submitted_at.isoformat(),
        "payload": payload,
    }


def _episode_from_json(document: str) -> Episode:
    raw = json.loads(document)
    stages = {
        Stage(stage_name): StageState(
            status=StageStatus(state["status"]),
            artifact=_artifact_from_document(state["artifact"]),
            review_note=state["review_note"],
        )
        for stage_name, state in raw["stages"].items()
    }
    return Episode(
        id=raw["id"],
        title=raw["title"],
        settings=ProjectSettings(
            target_duration_seconds=raw["settings"]["target_duration_seconds"],
            prompt_language=PromptLanguage(raw["settings"]["prompt_language"]),
            max_shot_duration_seconds=raw["settings"]["max_shot_duration_seconds"],
        ),
        assets={
            asset["id"]: Asset(
                id=asset["id"],
                name=asset["name"],
                kind=AssetKind(asset["kind"]),
                policy=AssetPolicy(asset["policy"]),
                confirmed=asset["confirmed"],
                description=asset["description"],
                source_path=asset.get("source_path", ""),
                mime_type=asset.get("mime_type", ""),
            )
            for asset in raw["assets"]
        },
        stages=stages,
        approvals=[
            ApprovalRecord(
                stage=Stage(approval["stage"]),
                revision=approval["revision"],
                reviewer=approval["reviewer"],
                note=approval["note"],
                approved_at=_parse_datetime(approval["approved_at"]),
            )
            for approval in raw["approvals"]
        ],
    )


def _artifact_from_document(document: dict | None) -> VersionedArtifact | None:
    if document is None:
        return None
    stage = Stage(document["stage"])
    raw_payload = document["payload"]
    if stage is Stage.OUTLINE:
        payload = OutlinePackage(
            title=raw_payload["title"],
            logline=raw_payload["logline"],
            beats=tuple(raw_payload["beats"]),
        )
    elif stage is Stage.SCRIPT:
        payload = ScriptPackage(
            scenes=tuple(
                Scene(
                    id=scene["id"],
                    heading=scene["heading"],
                    action=scene["action"],
                    dialogue=tuple(scene["dialogue"]),
                )
                for scene in raw_payload["scenes"]
            )
        )
    else:
        payload = DirectionPackage(
            shots=tuple(
                Shot(
                    id=shot["id"],
                    scene_id=shot["scene_id"],
                    title=shot["title"],
                    estimated_duration_seconds=shot["estimated_duration_seconds"],
                    visual_description=shot["visual_description"],
                    standard_prompt=shot["standard_prompt"],
                    asset_ids=tuple(shot["asset_ids"]),
                    camera=shot["camera"],
                    dialogue=shot["dialogue"],
                    voice_direction=shot["voice_direction"],
                    music_direction=shot["music_direction"],
                )
                for shot in raw_payload["shots"]
            )
        )
    return VersionedArtifact(
        stage=stage,
        revision=document["revision"],
        author=document["author"],
        payload=payload,
        submitted_at=_parse_datetime(document["submitted_at"]),
    )


def _parse_datetime(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)
