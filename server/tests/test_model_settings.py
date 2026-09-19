from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from server.director_workbench import (
    AgentModelSettings,
    AgentRole,
    LocalModelSettingsStore,
    ModelSettings,
    OpenAICompatibleAdapter,
    ProviderKind,
    ProviderSettings,
)


class ModelSettingsTests(unittest.TestCase):
    def test_settings_persist_without_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            store = LocalModelSettingsStore(path)
            settings = ModelSettings(
                providers=(
                    ProviderSettings(
                        id="studio",
                        label="工作室模型",
                        kind=ProviderKind.OPENAI_COMPATIBLE,
                        base_url="https://models.example/v1",
                        api_key_env="STUDIO_MODEL_KEY",
                    ),
                ),
                assignments=tuple(
                    AgentModelSettings(
                        role=role,
                        provider_id="studio",
                        model=f"model-{index}",
                    )
                    for index, role in enumerate(AgentRole)
                ),
            )
            store.save(settings)

            reopened = store.load()
            raw = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(reopened.providers[0].api_key_env, "STUDIO_MODEL_KEY")
            self.assertNotIn("api_key", raw["providers"][0])

    def test_every_agent_must_have_an_assignment(self) -> None:
        settings = ModelSettings(
            providers=(ProviderSettings("demo", "演示", ProviderKind.DEMO),),
            assignments=(),
        )
        with self.assertRaisesRegex(ValueError, "尚未分配模型"):
            settings.validate()


class OpenAICompatibleAdapterTests(unittest.TestCase):
    def test_chat_completion_contract(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.headers["Authorization"], "Bearer local-secret")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "director-model")
            self.assertEqual(body["response_format"], {"type": "json_object"})
            return httpx.Response(
                200,
                json={
                    "model": "director-model",
                    "choices": [{"message": {"content": '{"title":"草案"}'}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        adapter = OpenAICompatibleAdapter(
            base_url="https://models.example/v1/",
            api_key="local-secret",
            client=client,
        )

        result = adapter.complete(
            model="director-model",
            system_prompt="你是总导演",
            user_prompt="生成大纲",
            json_mode=True,
        )

        self.assertEqual(result.text, '{"title":"草案"}')
        self.assertEqual(result.input_tokens, 12)
