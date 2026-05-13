from types import SimpleNamespace

import pytest
import time

from src.chat.heart_flow import heartflow_manager as heartflow_manager_module
from src.chat.heart_flow.heartflow_manager import HEARTFLOW_ACTIVE_RETENTION_SECONDS, HeartflowManager
from src.maisaka.runtime import MAX_RETAINED_MESSAGE_CACHE_SIZE, MaisakaHeartFlowChatting


def _build_runtime_with_messages(message_count: int) -> MaisakaHeartFlowChatting:
    runtime = object.__new__(MaisakaHeartFlowChatting)
    runtime.log_prefix = "[test]"
    runtime.message_cache = [SimpleNamespace(message_id=f"msg-{index}") for index in range(message_count)]
    runtime._last_processed_index = message_count
    return runtime


def test_prune_processed_message_cache_keeps_bounded_recent_window() -> None:
    runtime = _build_runtime_with_messages(MAX_RETAINED_MESSAGE_CACHE_SIZE + 25)

    runtime._prune_processed_message_cache()

    assert len(runtime.message_cache) == MAX_RETAINED_MESSAGE_CACHE_SIZE
    assert runtime.message_cache[0].message_id == "msg-25"
    assert runtime._last_processed_index == MAX_RETAINED_MESSAGE_CACHE_SIZE


def test_prune_processed_message_cache_keeps_pending_messages() -> None:
    runtime = _build_runtime_with_messages(MAX_RETAINED_MESSAGE_CACHE_SIZE + 25)
    runtime._last_processed_index = 20

    runtime._prune_processed_message_cache()

    assert len(runtime.message_cache) == MAX_RETAINED_MESSAGE_CACHE_SIZE + 5
    assert runtime.message_cache[0].message_id == "msg-20"
    assert runtime._last_processed_index == 0


def test_collect_pending_messages_uses_single_pending_received_time() -> None:
    runtime = _build_runtime_with_messages(2)
    runtime._last_processed_index = 0
    runtime._oldest_pending_message_received_at = 123.0
    runtime._last_message_received_at = 456.0
    runtime._reply_latency_measurement_started_at = None

    pending_messages = runtime._collect_pending_messages()

    assert [message.message_id for message in pending_messages] == ["msg-0", "msg-1"]
    assert runtime._reply_latency_measurement_started_at == 123.0
    assert runtime._oldest_pending_message_received_at is None


@pytest.mark.asyncio
async def test_heartflow_manager_evicts_lru_chat_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = HeartflowManager()
    stopped_session_ids: list[str] = []
    old_active_at = time.time() - HEARTFLOW_ACTIVE_RETENTION_SECONDS - 1

    class FakeChat:
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id

        async def stop(self) -> None:
            stopped_session_ids.append(self.session_id)

    monkeypatch.setattr(heartflow_manager_module, "HEARTFLOW_MAX_ACTIVE_CHATS", 2)
    manager.heartflow_chat_list["session-1"] = FakeChat("session-1")
    manager.heartflow_chat_list["session-2"] = FakeChat("session-2")
    manager.heartflow_chat_list["session-3"] = FakeChat("session-3")
    manager._chat_last_active_at["session-1"] = old_active_at
    manager._chat_last_active_at["session-2"] = old_active_at
    manager._chat_last_active_at["session-3"] = time.time()

    await manager._evict_over_limit_chats(protected_session_id="session-3")

    assert stopped_session_ids == ["session-1"]
    assert list(manager.heartflow_chat_list) == ["session-2", "session-3"]


@pytest.mark.asyncio
async def test_heartflow_manager_keeps_recent_chats_even_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = HeartflowManager()
    stopped_session_ids: list[str] = []

    class FakeChat:
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id

        async def stop(self) -> None:
            stopped_session_ids.append(self.session_id)

    monkeypatch.setattr(heartflow_manager_module, "HEARTFLOW_MAX_ACTIVE_CHATS", 2)
    for session_id in ("session-1", "session-2", "session-3"):
        manager.heartflow_chat_list[session_id] = FakeChat(session_id)
        manager._chat_last_active_at[session_id] = time.time()

    await manager._evict_over_limit_chats(protected_session_id="session-3")

    assert stopped_session_ids == []
    assert list(manager.heartflow_chat_list) == ["session-1", "session-2", "session-3"]
