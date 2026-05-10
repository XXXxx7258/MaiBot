"""Maisaka 历史消息处理辅助工具。"""

from typing import TYPE_CHECKING

from src.common.data_models.message_component_data_model import MessageSequence, ReplyComponent, TextComponent

from .context_messages import AssistantMessage, LLMContextMessage, SessionBackedMessage, ToolResultMessage
from .message_adapter import build_visible_text_from_sequence, clone_message_sequence, format_speaker_content

if TYPE_CHECKING:
    from src.chat.message_receive.message import SessionMessage

TOOL_RESULT_MEDIA_SOURCE_KIND = "tool_result_media"


def build_prefixed_message_sequence(
    source_sequence: MessageSequence,
    planner_prefix: str,
) -> MessageSequence:
    """基于原始消息序列构造带规划器前缀的新序列。"""

    planner_components = clone_message_sequence(source_sequence).components
    if planner_components and isinstance(planner_components[0], TextComponent):
        planner_components[0].text = f"{planner_prefix}{planner_components[0].text}"
    else:
        planner_components.insert(0, TextComponent(planner_prefix))
    return MessageSequence(planner_components)


def build_session_message_visible_text(
    message: "SessionMessage",
    source_sequence: MessageSequence | None = None,
    *,
    include_reply_components: bool = True,
) -> str:
    """将真实会话消息转换为 Maisaka 可见文本。"""

    normalized_sequence = source_sequence if source_sequence is not None else message.raw_message
    user_info = message.message_info.user_info
    speaker_name = user_info.user_cardname or user_info.user_nickname or user_info.user_id
    visible_message_id = None if message.is_notify else message.message_id

    visible_sequence = MessageSequence([])
    visible_sequence.text(
        format_speaker_content(
            speaker_name,
            "",
            message.timestamp,
            visible_message_id,
        )
    )
    for component in clone_message_sequence(normalized_sequence).components:
        if not include_reply_components and isinstance(component, ReplyComponent):
            continue
        visible_sequence.components.append(component)
    return build_visible_text_from_sequence(visible_sequence).strip()


def drop_leading_orphan_tool_results(
    chat_history: list[LLMContextMessage],
) -> tuple[list[LLMContextMessage], int]:
    """移除历史前缀中缺少对应 tool_call 的工具结果消息。"""

    if not chat_history:
        return chat_history, 0

    available_tool_call_ids = {
        tool_call.call_id
        for message in chat_history
        if isinstance(message, AssistantMessage)
        for tool_call in message.tool_calls
        if tool_call.call_id
    }

    first_valid_index = 0
    while first_valid_index < len(chat_history):
        message = chat_history[first_valid_index]
        if not isinstance(message, ToolResultMessage):
            break
        if message.tool_call_id in available_tool_call_ids:
            break
        first_valid_index += 1

    if first_valid_index == 0:
        return chat_history, 0
    return chat_history[first_valid_index:], first_valid_index


def drop_orphan_tool_results(
    chat_history: list[LLMContextMessage],
) -> tuple[list[LLMContextMessage], int]:
    """移除窗口任意位置中缺少对应 tool_call 的工具结果消息。"""

    if not chat_history:
        return chat_history, 0

    available_tool_call_ids = {
        tool_call.call_id
        for message in chat_history
        if isinstance(message, AssistantMessage)
        for tool_call in message.tool_calls
        if tool_call.call_id
    }

    filtered_history: list[LLMContextMessage] = []
    removed_count = 0
    for message in chat_history:
        if isinstance(message, ToolResultMessage) and message.tool_call_id not in available_tool_call_ids:
            removed_count += 1
            continue
        if _is_orphan_tool_result_media_message(message, available_tool_call_ids):
            removed_count += 1
            continue
        filtered_history.append(message)

    return filtered_history, removed_count


def _is_orphan_tool_result_media_message(
    message: LLMContextMessage,
    available_tool_call_ids: set[str],
) -> bool:
    """判断 tool result 拆分出的媒体消息是否已经失去对应 tool_call。"""

    if not isinstance(message, SessionBackedMessage):
        return False
    if message.source_kind != TOOL_RESULT_MEDIA_SOURCE_KIND:
        return False

    message_id = str(message.message_id or "").strip()
    if not message_id.startswith("tool_result:"):
        return False

    _, _, remaining = message_id.partition("tool_result:")
    tool_call_id, _, _ = remaining.rpartition(":")
    return bool(tool_call_id) and tool_call_id not in available_tool_call_ids


def normalize_tool_result_order(
    chat_history: list[LLMContextMessage],
) -> tuple[list[LLMContextMessage], int]:
    """把被其他消息隔开的 tool 结果移动到对应 assistant tool_calls 后面。"""

    if not chat_history:
        return chat_history, 0

    consumed_indexes: set[int] = set()
    normalized_history: list[LLMContextMessage] = []
    moved_count = 0

    for index, message in enumerate(chat_history):
        if index in consumed_indexes:
            continue

        normalized_history.append(message)
        if not isinstance(message, AssistantMessage) or not message.tool_calls:
            continue

        appended_tool_result_count = 0
        for tool_call in message.tool_calls:
            tool_call_id = str(tool_call.call_id or "").strip()
            if not tool_call_id:
                continue

            matching_index = _find_tool_result_index(
                chat_history,
                tool_call_id=tool_call_id,
                start_index=index + 1,
                consumed_indexes=consumed_indexes,
            )
            if matching_index is None:
                continue

            consumed_indexes.add(matching_index)
            normalized_history.append(chat_history[matching_index])
            expected_index = index + appended_tool_result_count + 1
            if matching_index != expected_index:
                moved_count += 1
            appended_tool_result_count += 1

    if moved_count <= 0:
        return chat_history, 0
    return normalized_history, moved_count


def _find_tool_result_index(
    chat_history: list[LLMContextMessage],
    *,
    tool_call_id: str,
    start_index: int,
    consumed_indexes: set[int],
) -> int | None:
    """查找指定 tool_call_id 对应的 tool 结果消息位置。"""

    for index in range(start_index, len(chat_history)):
        if index in consumed_indexes:
            continue
        message = chat_history[index]
        if not isinstance(message, ToolResultMessage):
            continue
        if message.tool_call_id == tool_call_id:
            return index
    return None
