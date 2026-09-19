from __future__ import annotations

import json
import unittest

from server.director_workbench import (
    AgentModelSettings,
    AgentRole,
    ChatCompletion,
    ConfiguredDirectorTeam,
    Episode,
    ModelSettings,
    OutlinePackage,
    ProjectSettings,
    ProviderKind,
    ProviderSettings,
    Stage,
)


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(self, **kwargs) -> ChatCompletion:
        self.calls.append(kwargs)
        text = (
            json.dumps(
                {
                    "title": "模型生成的大纲",
                    "logline": "主角必须在午夜前找回失踪的记忆。",
                    "beats": ["收到线索", "进入旧城", "选择代价"],
                },
                ensure_ascii=False,
            )
            if kwargs.get("json_mode")
            else "建议强化人物目标，并把钩子提前到第一场。"
        )
        return ChatCompletion(text=text, input_tokens=10, output_tokens=8, model=kwargs["model"])


class ConfiguredDirectorTeamTests(unittest.TestCase):
    def test_external_agents_feed_chief_director_json_draft(self) -> None:
        provider = ProviderSettings(
            id="studio",
            label="工作室模型",
            kind=ProviderKind.OPENAI_COMPATIBLE,
            base_url="https://models.example/v1",
            api_key_env="STUDIO_KEY",
        )
        settings = ModelSettings(
            providers=(provider,),
            assignments=tuple(
                AgentModelSettings(role, "studio", f"model-{index}")
                for index, role in enumerate(AgentRole)
            ),
        )
        gateway = FakeGateway()
        team = ConfiguredDirectorTeam(
            settings,
            environment={"STUDIO_KEY": "secret"},
            gateway_factory=lambda _provider, _key: gateway,
        )
        episode = Episode(
            id="episode-1",
            title="雾城来信",
            settings=ProjectSettings(target_duration_seconds=240),
        )

        result = team.draft(episode, Stage.OUTLINE)

        self.assertIsInstance(result.artifact, OutlinePackage)
        self.assertEqual(result.artifact.title, "模型生成的大纲")
        self.assertEqual(len(result.discussion), 4)
        self.assertEqual(len(gateway.calls), 4)
        self.assertTrue(gateway.calls[-1]["json_mode"])

    def test_missing_environment_key_is_reported(self) -> None:
        provider = ProviderSettings(
            id="studio",
            label="工作室模型",
            kind=ProviderKind.OPENAI_COMPATIBLE,
            base_url="https://models.example/v1",
            api_key_env="MISSING_KEY",
        )
        settings = ModelSettings(
            providers=(provider,),
            assignments=tuple(
                AgentModelSettings(role, "studio", "model") for role in AgentRole
            ),
        )
        team = ConfiguredDirectorTeam(settings, environment={})
        episode = Episode(
            id="episode-1",
            title="雾城来信",
            settings=ProjectSettings(target_duration_seconds=240),
        )

        with self.assertRaisesRegex(Exception, "MISSING_KEY"):
            team.draft(episode, Stage.OUTLINE)


if __name__ == "__main__":
    unittest.main()
