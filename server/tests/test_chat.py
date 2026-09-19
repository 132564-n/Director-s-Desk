from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from server.director_workbench.api import create_app
from server.director_workbench.chat import (
    ChatMode,
    ConversationModule,
    ConversationStatus,
    MessageKind,
    ProposalStatus,
    create_conversation,
)
from server.director_workbench.chat_engine import GroupChatEngine, TurnOptions
from server.director_workbench.chat_repository import (
    InMemoryConversationRepository,
    SqliteConversationRepository,
)
from server.director_workbench.domain import Episode, ProjectSettings, Stage
from server.director_workbench.drafting import AgentRole
from server.director_workbench.model_settings import LocalModelSettingsStore
from server.director_workbench.repository import InMemoryWorkflowRepository

MEMBERS = (
    AgentRole.CHIEF_DIRECTOR,
    AgentRole.WRITER,
    AgentRole.STORYBOARD_DIRECTOR,
    AgentRole.CONTINUITY_EDITOR,
)


def make_conversation():
    return create_conversation(
        episode_id="episode-1",
        title="开场讨论",
        goal="确定前三秒钩子",
        members=MEMBERS,
        template="剧情会",
    )


class ConversationModuleTests(unittest.TestCase):
    def test_turn_and_proposal_transitions_are_auditable(self) -> None:
        module = ConversationModule(make_conversation())
        user_message = module.begin_turn(
            content="讨论开场剧情",
            mode=ChatMode.PROPOSAL,
            autonomous=True,
            mentions=(AgentRole.WRITER,),
        )
        module.add_agent_message(
            role=AgentRole.WRITER,
            content="从误会切入。",
            model="demo-writer",
            round_number=1,
            reply_to=user_message.id,
        )
        decision = module.complete_turn(
            decision="采用误会开场。",
            model="demo-chief",
            proposal_stage=Stage.OUTLINE,
            proposal_title="开场大纲",
            proposal_payload={"title": "开场", "logline": "误会", "beats": ["冲突"]},
        )
        proposal_id = decision.proposal_id
        assert proposal_id is not None
        module.set_proposal_status(proposal_id, ProposalStatus.ADOPTED)

        snapshot = module.snapshot()
        self.assertEqual(snapshot.status, ConversationStatus.COMPLETE)
        self.assertEqual(snapshot.proposals[proposal_id].status, ProposalStatus.ADOPTED)
        self.assertEqual(snapshot.messages[-1].kind, MessageKind.SYSTEM)
        self.assertIn("已采纳为草案", snapshot.messages[-1].content)

    def test_running_turn_can_be_stopped(self) -> None:
        module = ConversationModule(make_conversation())
        module.begin_turn(content="继续讨论", mode=ChatMode.DISCUSS, autonomous=True)
        module.stop()
        snapshot = module.snapshot()
        self.assertEqual(snapshot.status, ConversationStatus.STOPPED)
        self.assertIsNone(snapshot.active_turn_id)


class ConversationRepositoryTests(unittest.TestCase):
    def test_sqlite_round_trip_and_pinned_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteConversationRepository(Path(directory) / "chat.sqlite")
            first = make_conversation()
            second = create_conversation(
                episode_id="episode-1",
                title="第二场",
                goal="检查衔接",
                members=MEMBERS,
                template="审校会",
            )
            repository.create(first)
            repository.create(second)
            module = ConversationModule(first)
            module.update_metadata(pinned=True)
            repository.save(module.snapshot())

            loaded = repository.get(first.id)
            self.assertTrue(loaded.pinned)
            self.assertEqual(repository.list("episode-1")[0].id, first.id)


class GroupChatEngineTests(unittest.TestCase):
    def test_autonomous_turn_creates_two_rounds_and_director_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workflows = InMemoryWorkflowRepository()
            workflows.create(
                Episode(
                    id="episode-1",
                    title="雾城来信",
                    settings=ProjectSettings(target_duration_seconds=240),
                )
            )
            conversations = InMemoryConversationRepository()
            conversation = make_conversation()
            module = ConversationModule(conversation)
            user_message = module.begin_turn(
                content="讨论剧情和镜头",
                mode=ChatMode.DISCUSS,
                autonomous=True,
            )
            conversations.create(module.snapshot())
            engine = GroupChatEngine(
                conversations=conversations,
                workflows=workflows,
                model_settings=LocalModelSettingsStore(Path(directory) / "models.json"),
            )

            engine.run(
                conversation.id,
                TurnOptions(
                    user_message_id=user_message.id,
                    mode=ChatMode.DISCUSS,
                    autonomous=True,
                    mentions=(),
                ),
                Event(),
            )

            result = conversations.get(conversation.id)
            agent_messages = [
                message for message in result.messages if message.kind is MessageKind.AGENT
            ]
            self.assertTrue(
                any(message.round == 2 for message in agent_messages),
                result.messages,
            )
            self.assertEqual(result.messages[-1].kind, MessageKind.DIRECTOR_DECISION)
            self.assertEqual(result.status, ConversationStatus.COMPLETE)


class ChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workflows = InMemoryWorkflowRepository()
        self.conversations = InMemoryConversationRepository()
        self.client = TestClient(
            create_app(
                self.workflows,
                data_root=Path(self.directory.name),
                conversation_repository=self.conversations,
            )
        )
        created = self.client.post(
            "/episodes",
            json={
                "id": "episode-1",
                "title": "雾城来信",
                "settings": {"target_duration_seconds": 240},
            },
        )
        self.assertEqual(created.status_code, 201)

    def _create_conversation(self) -> dict:
        response = self.client.post(
            "/conversations",
            json={
                "episode_id": "episode-1",
                "title": "第一场创作会",
                "goal": "产出可确认的大纲",
                "members": ["总导演", "策划", "编剧", "连续性审校"],
                "template": "剧情会",
            },
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    def test_conversation_message_proposal_and_shelf_flow(self) -> None:
        conversation = self._create_conversation()
        conversation_id = conversation["id"]
        sent = self.client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "content": "请讨论故事钩子并生成大纲草案",
                "mode": "proposal",
                "autonomous": True,
            },
        )
        self.assertEqual(sent.status_code, 202)

        current = self.client.get(f"/conversations/{conversation_id}").json()
        self.assertEqual(current["status"], "complete")
        self.assertGreaterEqual(
            len([message for message in current["messages"] if message["kind"] == "agent"]),
            2,
            current["messages"],
        )
        proposal_id = next(iter(current["proposals"]))

        confirm_too_early = self.client.post(
            f"/conversations/{conversation_id}/proposals/{proposal_id}/confirm"
        )
        self.assertEqual(confirm_too_early.status_code, 409)
        adopted = self.client.post(
            f"/conversations/{conversation_id}/proposals/{proposal_id}/adopt"
        )
        self.assertEqual(adopted.status_code, 200)
        confirmed = self.client.post(
            f"/conversations/{conversation_id}/proposals/{proposal_id}/confirm"
        )
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(
            confirmed.json()["proposals"][proposal_id]["status"],
            "confirmed",
        )

        shelf = self.client.get("/episodes/episode-1/shelf")
        self.assertEqual(shelf.status_code, 200)
        self.assertEqual(shelf.json()["proposals"][0]["status"], "confirmed")
        self.assertEqual(shelf.json()["artifacts"][0]["stage"], "outline")

    def test_conversation_can_be_renamed_pinned_and_archived(self) -> None:
        conversation = self._create_conversation()
        response = self.client.patch(
            f"/conversations/{conversation['id']}",
            json={"title": "锁定版创作会", "pinned": True, "archived": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "锁定版创作会")
        self.assertTrue(response.json()["pinned"])
        self.assertTrue(response.json()["archived"])


if __name__ == "__main__":
    unittest.main()
