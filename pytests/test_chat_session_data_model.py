"""聊天会话数据模型回归测试。"""

from contextlib import contextmanager
from importlib import import_module

import pytest

from src.chat.message_receive.chat_manager import BotChatSession, ChatManager

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
