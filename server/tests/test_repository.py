from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.director_workbench import (
    Episode,
    OutlinePackage,
    ProjectSettings,
    SqliteWorkflowRepository,
    Stage,
    StageStatus,
)


class SqliteWorkflowRepositoryTests(unittest.TestCase):
    def test_workflow_survives_repository_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "workbench.sqlite"
            repository = SqliteWorkflowRepository(database)
            workflow = repository.create(
                Episode(
                    id="episode-1",
                    title="第一集",
                    settings=ProjectSettings(target_duration_seconds=240),
                )
            )
            workflow.submit(
                OutlinePackage(
                    title="雾城来信",
                    logline="少女寻找失踪的哥哥。",
                    beats=("收到信", "进入雾城"),
                ),
                author="编剧 Agent",
            )
            workflow.approve(Stage.OUTLINE, reviewer="用户", note="方向通过")
            repository.save(workflow)

            reopened = SqliteWorkflowRepository(database).get("episode-1").snapshot()

            self.assertEqual(
                reopened.episode.stages[Stage.OUTLINE].status,
                StageStatus.APPROVED,
            )
            self.assertEqual(
                reopened.episode.stages[Stage.SCRIPT].status,
                StageStatus.READY,
            )
            self.assertEqual(reopened.episode.approvals[0].note, "方向通过")

    def test_duplicate_episode_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteWorkflowRepository(Path(directory) / "workbench.sqlite")
            episode = Episode(
                id="episode-1",
                title="第一集",
                settings=ProjectSettings(target_duration_seconds=240),
            )
            repository.create(episode)

            with self.assertRaisesRegex(ValueError, "已存在"):
                repository.create(episode)


if __name__ == "__main__":
    unittest.main()
