from datetime import datetime
from types import SimpleNamespace

from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.common.data_models.message_component_data_model import AtComponent, MessageSequence, ReplyComponent, TextComponent
from src.config.config import global_config
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.maisaka.runtime import MaisakaHeartFlowChatting


def _build_sent_message() -> SessionMessage:
    message = SessionMessage(
        message_id="real-message-id",
        timestamp=datetime(2026, 4, 5, 12, 0, 0),
        platform="qq",
    )
    message.message_info = MessageInfo(
        user_info=UserInfo(
            user_id="bot-qq",
            user_nickname="MaiSaka",
            user_cardname=None,
        ),
        group_info=None,
        additional_config={},
    )
    message.raw_message = MessageSequence(
        [
            ReplyComponent(target_message_id="m123"),
            TextComponent(text="你好"),
        ]
    )
    message.session_id = "test-session"
    message.initialized = True
    return message


def test_append_sent_message_to_chat_history_keeps_message_id() -> None:
    runtime = SimpleNamespace(_chat_history=[])
    engine = SimpleNamespace(_get_runtime_manager=lambda: None)
    tool_ctx = BuiltinToolRuntimeContext(engine=engine, runtime=runtime)

    tool_ctx.append_sent_message_to_chat_history(_build_sent_message())

    assert len(runtime._chat_history) == 1
    history_message = runtime._chat_history[0]
    assert history_message.message_id == "real-message-id"
    assert '<message msg_id="real-message-id" time="12:00:00" user="MaiSaka">' in history_message.raw_message.components[0].text
    assert "[msg_id:real-message-id]" in history_message.visible_text


def test_post_process_reply_message_sequences_converts_at_marker_before_bracket_cleanup(monkeypatch) -> None:
    monkeypatch.setattr(global_config.chat, "enable_at", True)
    monkeypatch.setattr(
        "src.maisaka.builtin_tool.context.process_llm_response",
        lambda text: [text.strip()] if text.strip() else [],
    )
    target_message = SimpleNamespace(
        message_info=SimpleNamespace(
            user_info=SimpleNamespace(
                user_id="target-user",
                user_nickname="目标昵称",
                user_cardname="群名片",
            )
        )
    )
    runtime = SimpleNamespace(
        find_source_message_by_id=lambda message_id: target_message if message_id == "12160142" else None
    )
    engine = SimpleNamespace(_get_runtime_manager=lambda: None)
    tool_ctx = BuiltinToolRuntimeContext(engine=engine, runtime=runtime)

    sequences = tool_ctx.post_process_reply_message_sequences("at[12160142] 就这个群")

    assert len(sequences) == 1
    components = sequences[0].components
    assert isinstance(components[0], AtComponent)
    assert components[0].target_user_id == "target-user"
    assert components[0].target_user_nickname == "目标昵称"
    assert components[0].target_user_cardname == "群名片"
    assert isinstance(components[1], TextComponent)
    assert components[1].text == " 就这个群"


def test_post_process_reply_message_sequences_ignores_at_marker_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(global_config.chat, "enable_at", False)
    monkeypatch.setattr(
        "src.maisaka.builtin_tool.context.process_llm_response",
        lambda text: [text.strip()] if text.strip() else [],
    )
    runtime = SimpleNamespace(find_source_message_by_id=lambda message_id: None)
    engine = SimpleNamespace(_get_runtime_manager=lambda: None)
    tool_ctx = BuiltinToolRuntimeContext(engine=engine, runtime=runtime)

    sequences = tool_ctx.post_process_reply_message_sequences("at[12160142] 就这个群")

    assert len(sequences) == 1
    components = sequences[0].components
    assert len(components) == 1
    assert isinstance(components[0], TextComponent)
    assert components[0].text == "at[12160142] 就这个群"


def test_runtime_finds_source_message_from_history() -> None:
    target_message = _build_sent_message()
    runtime = object.__new__(MaisakaHeartFlowChatting)
    runtime._chat_history = [
        SimpleNamespace(message_id="other-message-id", original_message=SimpleNamespace()),
        SimpleNamespace(message_id="real-message-id", original_message=target_message),
    ]

    assert runtime.find_source_message_by_id("real-message-id") is target_message
    assert runtime.find_source_message_by_id("missing-message-id") is None
