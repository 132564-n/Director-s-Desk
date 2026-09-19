import unittest
from datetime import UTC, datetime

from server.director_workbench import (
    Asset,
    AssetKind,
    AssetPolicy,
    DirectionPackage,
    Episode,
    OutlinePackage,
    ProductionWorkflow,
    ProjectSettings,
    Scene,
    ScriptPackage,
    Shot,
    Stage,
    StageStatus,
    WorkflowError,
)

NOW = datetime(2026, 9, 19, 8, 0, tzinfo=UTC)


def outline(title: str = "雾城来信") -> OutlinePackage:
    return OutlinePackage(
        title=title,
        logline="少女循着一封不可能存在的信寻找失踪的哥哥。",
        beats=("收到旧信", "进入雾城", "发现真相"),
    )


def script() -> ScriptPackage:
    return ScriptPackage(
        scenes=(
            Scene(
                id="scene-1",
                heading="内景·旧车站·夜",
                action="少女拆开一封沾着雨水的信。",
                dialogue=("哥，你还活着吗？",),
            ),
        )
    )


def shot(*, duration: float = 8, asset_ids: tuple[str, ...] = ("char-1",)) -> Shot:
    return Shot(
        id="shot-1",
        scene_id="scene-1",
        title="拆信",
        estimated_duration_seconds=duration,
        visual_description="少女在废弃车站拆开湿透的信封。",
        standard_prompt="中景，少女拆开信封，雨夜旧车站，冷色侧光。",
        asset_ids=asset_ids,
        camera="缓慢推近",
        dialogue="哥，你还活着吗？",
        voice_direction="压低声音，迟疑后读出",
        music_direction="稀疏钢琴，远处雷声",
    )


def workflow(*, max_shot_duration: float | None = None, asset_confirmed: bool = True):
    episode = Episode(
        id="episode-1",
        title="第一集",
        settings=ProjectSettings(
            target_duration_seconds=240,
            max_shot_duration_seconds=max_shot_duration,
        ),
        assets={
            "char-1": Asset(
                id="char-1",
                name="林雾",
                kind=AssetKind.CHARACTER,
                policy=AssetPolicy.LOCKED,
                confirmed=asset_confirmed,
                description="黑色短发，灰色风衣",
            )
        },
    )
    return ProductionWorkflow(episode, clock=lambda: NOW)


def reach_direction(workflow: ProductionWorkflow) -> None:
    workflow.submit(outline(), author="编剧 Agent")
    workflow.approve(Stage.OUTLINE, reviewer="用户")
    workflow.submit(script(), author="编剧 Agent")
    workflow.approve(Stage.SCRIPT, reviewer="用户")


class ProductionWorkflowTests(unittest.TestCase):
    def test_script_is_blocked_until_outline_is_approved(self) -> None:
        flow = workflow()

        with self.assertRaisesRegex(WorkflowError, "尚未解锁"):
            flow.submit(script(), author="编剧 Agent")

        flow.submit(outline(), author="编剧 Agent")
        flow.approve(Stage.OUTLINE, reviewer="用户")

        view = flow.submit(script(), author="编剧 Agent")
        self.assertEqual(view.episode.stages[Stage.SCRIPT].status, StageStatus.IN_REVIEW)

    def test_default_settings_do_not_limit_shot_duration(self) -> None:
        flow = workflow(max_shot_duration=None)
        reach_direction(flow)

        view = flow.submit(DirectionPackage(shots=(shot(duration=30),)), author="分镜导演 Agent")

        self.assertEqual(view.episode.stages[Stage.DIRECTION].status, StageStatus.IN_REVIEW)

    def test_configured_shot_duration_is_a_hard_limit(self) -> None:
        flow = workflow(max_shot_duration=5)
        reach_direction(flow)

        with self.assertRaisesRegex(WorkflowError, "超过项目上限 5 秒"):
            flow.submit(DirectionPackage(shots=(shot(duration=5.1),)), author="分镜导演 Agent")

    def test_unconfirmed_asset_cannot_be_used(self) -> None:
        flow = workflow(asset_confirmed=False)
        reach_direction(flow)

        with self.assertRaisesRegex(WorkflowError, "尚未确认的资产"):
            flow.submit(DirectionPackage(shots=(shot(),)), author="分镜导演 Agent")

    def test_revising_outline_marks_downstream_artifacts_stale(self) -> None:
        flow = workflow()
        reach_direction(flow)
        flow.submit(DirectionPackage(shots=(shot(),)), author="分镜导演 Agent")
        flow.approve(Stage.DIRECTION, reviewer="用户")

        view = flow.submit(outline(title="雾城来信·新版"), author="编剧 Agent")

        self.assertEqual(view.episode.stages[Stage.SCRIPT].status, StageStatus.STALE)
        self.assertEqual(view.episode.stages[Stage.DIRECTION].status, StageStatus.STALE)
        self.assertFalse(view.complete)

    def test_approval_records_the_exact_revision(self) -> None:
        flow = workflow()
        flow.submit(outline(), author="编剧 Agent")
        view = flow.approve(Stage.OUTLINE, reviewer="用户", note="方向通过")

        self.assertEqual(len(view.episode.approvals), 1)
        approval = view.episode.approvals[0]
        self.assertEqual(approval.revision, 1)
        self.assertEqual(approval.note, "方向通过")
        self.assertEqual(approval.approved_at, NOW)

    def test_snapshot_cannot_mutate_workflow_state(self) -> None:
        flow = workflow()
        view = flow.snapshot()
        view.episode.title = "外部篡改"

        self.assertEqual(flow.snapshot().episode.title, "第一集")

    def test_uploaded_asset_requires_description_before_confirmation(self) -> None:
        flow = workflow()
        flow.register_asset(
            Asset(
                id="new-asset",
                name="旧车站",
                kind=AssetKind.LOCATION,
                policy=AssetPolicy.REFERENCE,
            )
        )

        with self.assertRaisesRegex(WorkflowError, "必须填写"):
            flow.confirm_asset(
                "new-asset",
                description="  ",
                policy=AssetPolicy.LOCKED,
            )

        view = flow.confirm_asset(
            "new-asset",
            description="雨夜中的废弃车站，蓝绿色灯光",
            policy=AssetPolicy.LOCKED,
        )
        self.assertTrue(view.episode.assets["new-asset"].confirmed)
        self.assertEqual(view.episode.assets["new-asset"].policy, AssetPolicy.LOCKED)


if __name__ == "__main__":
    unittest.main()
