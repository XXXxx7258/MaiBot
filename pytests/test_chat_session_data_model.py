"""聊天会话数据模型回归测试。"""

from contextlib import contextmanager
from importlib import import_module

import pytest

from src.chat.message_receive.chat_manager import BotChatSession, ChatManager
from src.plugin_runtime.capabilities import data as capability_data_module
from src.plugin_runtime.capabilities.data import RuntimeDataCapabilityMixin

chat_manager_module = import_module("src.chat.message_receive.chat_manager")


def test_group_chat_session_does_not_store_sender_user_id() -> None:
    """群聊会话不应把首个发言人保存为聊天流归属用户。"""

    session = BotChatSession(
        session_id="group-session",
        platform="qq",
        user_id="first-speaker",
        group_id="group-1",
        account_id="bot-account",
        scope="main",
    )

    assert session.user_id is None
    assert session.group_id == "group-1"
    assert session.account_id == "bot-account"
    assert session.scope == "main"
    assert session.is_group_session is True


def test_private_chat_session_keeps_user_id() -> None:
    """私聊会话仍然以 ``user_id`` 表示目标用户。"""

    session = BotChatSession(
        session_id="private-session",
        platform="qq",
        user_id="target-user",
        group_id=None,
    )

    assert session.user_id == "target-user"
    assert session.group_id is None
    assert session.is_group_session is False


@pytest.mark.asyncio
async def test_chat_manager_fills_route_metadata_when_creating_group_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """收到带路由元数据的群消息时，会话应记录账号与 scope。"""

    class _EmptyExecResult:
        def first(self):
            return None

    class _EmptyDbSession:
        def exec(self, statement):
            del statement
            return _EmptyExecResult()

    @contextmanager
    def _fake_db_session():
        yield _EmptyDbSession()

    manager = ChatManager()
    saved_sessions: list[BotChatSession] = []
    monkeypatch.setattr(chat_manager_module, "get_db_session", _fake_db_session)
    monkeypatch.setattr(manager, "_save_session", saved_sessions.append)

    session = await manager.get_or_create_session(
        platform="qq",
        user_id="first-speaker",
        group_id="group-1",
        account_id="bot-account",
        scope="main",
    )

    assert session.user_id is None
    assert session.account_id == "bot-account"
    assert session.scope == "main"
    assert saved_sessions == [session]


@pytest.mark.asyncio
async def test_chat_open_session_creates_private_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat.open_session 可以创建私聊流并返回 stream_id。"""

    class _EmptyExecResult:
        def first(self):
            return None

        def all(self):
            return []

    class _EmptyDbSession:
        def exec(self, statement):
            del statement
            return _EmptyExecResult()

    @contextmanager
    def _fake_db_session():
        yield _EmptyDbSession()

    manager = ChatManager()
    monkeypatch.setattr(chat_manager_module, "get_db_session", _fake_db_session)
    monkeypatch.setattr(manager, "_save_session", lambda session: None)
    monkeypatch.setattr(capability_data_module, "chat_manager", manager)

    result = await RuntimeDataCapabilityMixin()._cap_chat_open_session(
        "test-plugin",
        "chat.open_session",
        {"platform": "qq", "chat_type": "private", "user_id": "user-1"},
    )

    assert result["success"] is True
    assert result["created"] is True
    assert result["stream_id"] == result["session_id"]
    assert result["chat_type"] == "private"
    assert result["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_chat_open_session_creates_group_stream_without_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """群聊流只需要 group_id，不应要求或保存 user_id。"""

    class _EmptyExecResult:
        def first(self):
            return None

        def all(self):
            return []

    class _EmptyDbSession:
        def exec(self, statement):
            del statement
            return _EmptyExecResult()

    @contextmanager
    def _fake_db_session():
        yield _EmptyDbSession()

    manager = ChatManager()
    monkeypatch.setattr(chat_manager_module, "get_db_session", _fake_db_session)
    monkeypatch.setattr(manager, "_save_session", lambda session: None)
    monkeypatch.setattr(capability_data_module, "chat_manager", manager)

    result = await RuntimeDataCapabilityMixin()._cap_chat_open_session(
        "test-plugin",
        "chat.open_session",
        {"platform": "qq", "chat_type": "group", "group_id": "group-1"},
    )

    assert result["success"] is True
    assert result["created"] is True
    assert result["chat_type"] == "group"
    assert result["group_id"] == "group-1"
    assert result["user_id"] is None
