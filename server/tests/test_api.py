from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server.director_workbench import InMemoryWorkflowRepository
from server.director_workbench.api import create_app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryWorkflowRepository()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = TestClient(
            create_app(self.repository, data_root=Path(self.directory.name))
        )
        response = self.client.post(
            "/episodes",
            json={
                "id": "episode-1",
                "title": "第一集",
                "settings": {
                    "target_duration_seconds": 240,
                    "max_shot_duration_seconds": 5,
                },
                "assets": [
                    {
                        "id": "char-1",
                        "name": "林雾",
                        "kind": "character",
                        "policy": "locked",
                        "confirmed": True,
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_script_is_rejected_before_outline_approval(self) -> None:
        response = self.client.post(
            "/episodes/episode-1/script",
            json={
                "author": "编剧 Agent",
                "scenes": [
                    {"id": "scene-1", "heading": "内景", "action": "拆信"}
                ],
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("尚未解锁", response.json()["detail"])

    def test_outline_submission_and_approval_unlock_script(self) -> None:
        submit = self.client.post(
            "/episodes/episode-1/outline",
            json={
                "title": "雾城来信",
                "logline": "少女寻找失踪的哥哥。",
                "beats": ["收到信", "进入雾城"],
                "author": "编剧 Agent",
            },
        )
        self.assertEqual(submit.status_code, 200)
        self.assertEqual(submit.json()["episode"]["stages"]["outline"]["status"], "in_review")

        approve = self.client.post(
            "/episodes/episode-1/stages/outline/approve",
            json={"reviewer": "用户", "note": "方向通过"},
        )
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.json()["episode"]["stages"]["script"]["status"], "ready")

    def test_unknown_fields_are_rejected(self) -> None:
        response = self.client.post(
            "/episodes/episode-1/outline",
            json={
                "title": "雾城来信",
                "logline": "少女寻找失踪的哥哥。",
                "beats": ["收到信"],
                "author": "编剧 Agent",
                "silent_extra": "不应被接受",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_list_and_draft_outline(self) -> None:
        listed = self.client.get("/episodes")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], "episode-1")

        drafted = self.client.post("/episodes/episode-1/draft/outline")
        self.assertEqual(drafted.status_code, 200)
        self.assertEqual(drafted.json()["stage"], "outline")
        self.assertEqual(len(drafted.json()["participants"]), 4)

    def test_upload_and_confirm_asset(self) -> None:
        uploaded = self.client.post(
            "/episodes/episode-1/assets",
            data={"name": "车站", "kind": "location", "policy": "reference"},
            files={"file": ("station.png", b"fake-png", "image/png")},
        )
        self.assertEqual(uploaded.status_code, 201)
        assets = uploaded.json()["episode"]["assets"]
        asset_id = next(key for key in assets if key != "char-1")
        self.assertFalse(assets[asset_id]["confirmed"])

        confirmed = self.client.post(
            f"/episodes/episode-1/assets/{asset_id}/confirm",
            json={
                "description": "雨夜中的废弃车站，蓝绿色灯光",
                "policy": "locked",
            },
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["episode"]["assets"][asset_id]["confirmed"])

    def test_model_settings_default_to_all_demo_agents(self) -> None:
        response = self.client.get("/settings/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["providers"][0]["kind"], "demo")
        self.assertEqual(len(response.json()["assignments"]), 9)


if __name__ == "__main__":
    unittest.main()
