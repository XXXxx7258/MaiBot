from datetime import datetime

import pytest

from src.common.data_models.message_component_data_model import MessageSequence, TextComponent
from src.llm_models.payload_content.tool_option import ToolCall
from src.maisaka.context_messages import AssistantMessage, SessionBackedMessage, ToolResultMessage
from src.maisaka.history_post_processor import process_chat_history_after_cycle


def _user_message(content: str) -> SessionBackedMessage:
    return SessionBackedMessage(
        raw_message=MessageSequence([TextComponent(content)]),
        visible_text=content,
        timestamp=datetime.now(),
    )


def _assistant_message(content: str, tool_calls: list[ToolCall] | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=content,
        timestamp=datetime.now(),
        tool_calls=tool_calls or [],
    )


def test_context_optimization_keeps_latest_three_assistant_messages() -> None:
    chat_history = []
    for index in range(5):
        chat_history.append(_user_message(f"用户消息 {index}"))
        chat_history.append(_assistant_message(f"assistant {index}"))

    result = process_chat_history_after_cycle(
        chat_history,
        max_context_size=100,
        enable_context_optimization=True,
    )

    assistant_contents = [
        message.content
        for message in result.history
        if isinstance(message, AssistantMessage)
    ]
    user_contents = [
        message.visible_text
        for message in result.history
        if isinstance(message, SessionBackedMessage)
    ]

    assert assistant_contents == ["assistant 2", "assistant 3", "assistant 4"]
    assert user_contents == [f"用户消息 {index}" for index in range(5)]
    assert result.removed_count == 2
    assert result.remaining_context_count == 8


def test_context_optimization_disabled_keeps_assistant_messages() -> None:
    chat_history = [_assistant_message(f"assistant {index}") for index in range(5)]

    result = process_chat_history_after_cycle(
        chat_history,
        max_context_size=100,
        enable_context_optimization=False,
    )

    assistant_contents = [
        message.content
        for message in result.history
        if isinstance(message, AssistantMessage)
    ]

    assert assistant_contents == [f"assistant {index}" for index in range(5)]
    assert result.removed_count == 0


def test_context_optimization_preserves_trimmed_assistant_tool_content_as_user_message() -> None:
    removed_tool_call = ToolCall(call_id="removed-call", func_name="query_memory", args={"query": "旧记忆"})
    kept_tool_call = ToolCall(call_id="kept-call", func_name="reply", args={})
    chat_history = [
        _assistant_message("assistant 0", [removed_tool_call]),
        ToolResultMessage(
            content="旧工具结果",
            timestamp=datetime.now(),
            tool_call_id="removed-call",
            tool_name="query_memory",
        ),
        _assistant_message("assistant 1"),
        _assistant_message("assistant 2"),
        _assistant_message("assistant 3", [kept_tool_call]),
        ToolResultMessage(
            content="新工具结果",
            timestamp=datetime.now(),
            tool_call_id="kept-call",
            tool_name="reply",
        ),
    ]

    result = process_chat_history_after_cycle(
        chat_history,
        max_context_size=100,
        enable_context_optimization=True,
    )

    tool_results = [
        message.content
        for message in result.history
        if isinstance(message, ToolResultMessage)
    ]
    folded_tool_messages = [
        message.visible_text
        for message in result.history
        if isinstance(message, SessionBackedMessage) and message.source_kind == "optimized_tool_history"
    ]

    assert tool_results == ["新工具结果"]
    assert len(folded_tool_messages) == 1
    assert "removed-call" in folded_tool_messages[0]
    assert "query_memory" in folded_tool_messages[0]
    assert "旧记忆" in folded_tool_messages[0]
    assert "旧工具结果" in folded_tool_messages[0]
    assert result.removed_count == 1


@pytest.mark.parametrize("tool_name", ["continue", "finish", "no_action", "reply", "wait"])
def test_context_optimization_drops_trimmed_control_tools_without_folding(tool_name: str) -> None:
    control_tool_call = ToolCall(call_id=f"{tool_name}-call", func_name=tool_name, args={})
    chat_history = [
        _assistant_message("assistant 0", [control_tool_call]),
        ToolResultMessage(
            content=f"{tool_name} 工具结果",
            timestamp=datetime.now(),
            tool_call_id=f"{tool_name}-call",
            tool_name=tool_name,
        ),
        _assistant_message("assistant 1"),
        _assistant_message("assistant 2"),
        _assistant_message("assistant 3"),
    ]

    result = process_chat_history_after_cycle(
        chat_history,
        max_context_size=100,
        enable_context_optimization=True,
    )

    folded_tool_messages = [
        message
        for message in result.history
        if isinstance(message, SessionBackedMessage) and message.source_kind == "optimized_tool_history"
    ]
    tool_results = [message for message in result.history if isinstance(message, ToolResultMessage)]

    assert folded_tool_messages == []
    assert tool_results == []
