from __future__ import annotations

import unittest

from server.director_workbench import (
    Asset,
    AssetKind,
    AssetPolicy,
    DemoDirectorTeam,
    Episode,
    OutlinePackage,
    ProductionWorkflow,
    ProjectSettings,
    ScriptPackage,
    Stage,
    WorkflowError,
)


class DemoDirectorTeamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.episode = Episode(
            id="episode-1",
            title="雾城来信",
            settings=ProjectSettings(
                target_duration_seconds=240,
                max_shot_duration_seconds=3,
            ),
            assets={
                "char-1": Asset(
                    id="char-1",
                    name="林雾",
                    kind=AssetKind.CHARACTER,
                    policy=AssetPolicy.LOCKED,
                    confirmed=True,
                )
            },
        )
        self.team = DemoDirectorTeam()

    def test_outline_draft_includes_stage_team_and_asset_context(self) -> None:
        result = self.team.draft(self.episode, Stage.OUTLINE)

        self.assertIsInstance(result.artifact, OutlinePackage)
        self.assertIn("林雾", result.artifact.logline)
        self.assertEqual(len(result.participants), 4)
        self.assertLessEqual(max(message.round for message in result.discussion), 2)

    def test_blocked_stage_cannot_be_drafted(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "尚未解锁"):
            self.team.draft(self.episode, Stage.SCRIPT)

    def test_direction_draft_respects_configured_maximum_duration(self) -> None:
        workflow = ProductionWorkflow(self.episode)
        outline = self.team.draft(workflow.snapshot().episode, Stage.OUTLINE).artifact
        workflow.submit(outline, author="演示团队")
        workflow.approve(Stage.OUTLINE, reviewer="用户")
        script = self.team.draft(workflow.snapshot().episode, Stage.SCRIPT).artifact
        self.assertIsInstance(script, ScriptPackage)
        workflow.submit(script, author="演示团队")
        workflow.approve(Stage.SCRIPT, reviewer="用户")

        direction = self.team.draft(workflow.snapshot().episode, Stage.DIRECTION).artifact

        self.assertTrue(direction.shots)
        self.assertTrue(
            all(shot.estimated_duration_seconds <= 3 for shot in direction.shots)
        )
        self.assertTrue(all("char-1" in shot.asset_ids for shot in direction.shots))


if __name__ == "__main__":
    unittest.main()
