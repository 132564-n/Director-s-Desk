import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from server.director_workbench.api import create_app
from server.director_workbench.model_gateway import ChatCompletion
from server.director_workbench.model_settings import LocalModelSettingsStore
from server.director_workbench.repository import InMemoryWorkflowRepository


@unittest.skipUnless(os.name == "nt", "DPAPI is a Windows credential store")
class WebCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.client = TestClient(create_app(InMemoryWorkflowRepository(), data_root=self.root))
        self.settings = self.client.get("/settings/models").json()
        self.settings["providers"].append({
            "id": "test-provider", "label": "测试供应商", "kind": "openai_compatible",
            "base_url": "https://model.example/v1", "api_key_env": "",
            "api_key": "test-only-not-a-real-key",
        })
        for item in self.settings["assignments"]:
            item.update(provider_id="test-provider", model="test-model")

    def save(self):
        response = self.client.put("/settings/models", json=self.settings)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_encrypted_persistence_no_readback_and_preserve_on_edit(self):
        saved = self.save()
        self.assertTrue(saved["providers"][1]["api_key_set"])
        self.assertNotIn("test-only-not-a-real-key", json.dumps(saved))
        self.assertNotIn("test-only-not-a-real-key", (self.root / "model-settings.json").read_text(encoding="utf-8"))
        self.client.put("/settings/models", json=saved).raise_for_status()
        store = LocalModelSettingsStore(self.root / "model-settings.json")
        self.assertEqual(store.api_key(store.load().providers[1]), "test-only-not-a-real-key")

    def test_clear_key_and_change_destination_do_not_reuse_secret(self):
        saved = self.save()
        saved["providers"][1]["base_url"] = "https://different.example/v1"
        response = self.client.put("/settings/models", json=saved)
        self.assertFalse(response.json()["providers"][1]["api_key_set"])
        saved = self.save()
        saved["providers"][1]["api_key"] = ""
        response = self.client.put("/settings/models", json=saved)
        self.assertFalse(response.json()["providers"][1]["api_key_set"])

    def test_private_files_not_served_and_cross_origin_denied(self):
        self.save()
        for path in ["/media/model-settings.json", "/media/database.sqlite", "/media/logs/api.out.log"]:
            self.assertEqual(self.client.get(path).status_code, 404)
        result = self.client.put("/settings/models", json=self.settings,
                                 headers={"Origin": "https://other.example"})
        self.assertEqual(result.status_code, 403)

    def test_connection_uses_saved_secret_and_never_returns_it(self):
        self.save()
        observed = []

        def respond(request):
            observed.append(request)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "OK"}}], "model": "test-model",
            })

        upstream = httpx.Client(transport=httpx.MockTransport(respond))
        with patch("server.director_workbench.api.httpx.Client", return_value=upstream):
            result = self.client.post("/settings/models/test", json={
                "provider_id": "test-provider", "model": "test-model",
            })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(observed[0].headers["Authorization"], "Bearer test-only-not-a-real-key")
        self.assertEqual(json.loads(observed[0].content)["max_tokens"], 8)
        self.assertNotIn("test-only-not-a-real-key", result.text)

    def test_missing_key_and_invalid_destination(self):
        self.settings["providers"][1].pop("api_key")
        self.save()
        result = self.client.post("/settings/models/test", json={
            "provider_id": "test-provider", "model": "test-model",
        })
        self.assertEqual(result.status_code, 409)
        self.settings["providers"][1]["base_url"] = "http://remote.example/v1"
        self.assertEqual(self.client.put("/settings/models", json=self.settings).status_code, 422)

    def test_duplicate_roles_rejected(self):
        self.settings["assignments"].append(self.settings["assignments"][0])
        self.assertEqual(self.client.put("/settings/models", json=self.settings).status_code, 422)

    def test_group_chat_uses_web_key_history_and_real_chief(self):
        self.save()
        self.client.post("/episodes", json={
            "id": "test-episode", "title": "测试项目",
            "settings": {"target_duration_seconds": 120},
        }).raise_for_status()
        conversation = self.client.post("/conversations", json={
            "episode_id": "test-episode", "title": "创作会", "goal": "保留悬念",
            "members": ["总导演", "编剧", "连续性审校"],
        }).json()
        path = f"/conversations/{conversation['id']}"
        with patch("server.director_workbench.chat_engine.OpenAICompatibleAdapter") as adapter:
            def complete(**kwargs):
                text = (
                    '{"decisions":[]}'
                    if "决策编辑" in kwargs["system_prompt"] else "模型针对性意见"
                )
                return ChatCompletion(
                    text=text, input_tokens=1, output_tokens=1, model="test-model",
                )

            adapter.return_value.complete.side_effect = complete
            for content in ["历史约束：主角不能失忆", "请讨论故事开头"]:
                self.client.post(f"{path}/messages", json={
                    "content": content, "mode": "discuss", "autonomous": True,
                }).raise_for_status()
            current = self.client.get(path).json()
            self.assertEqual(current["status"], "complete")
            for call in adapter.call_args_list:
                self.assertEqual(call.kwargs["api_key"], "test-only-not-a-real-key")
            calls = adapter.return_value.complete.call_args_list
            chief = next(
                call.kwargs for call in reversed(calls)
                if "总导演" in call.kwargs["system_prompt"]
            )
            self.assertIn("总导演", chief["system_prompt"])
            self.assertIn("模型针对性意见", chief["user_prompt"])
            self.assertIn("主角不能失忆", chief["user_prompt"])
            self.assertIn("保留悬念", chief["user_prompt"])
            self.assertGreaterEqual(len(calls), 10)
            self.assertTrue(any(call.kwargs.get("json_mode") for call in calls))
