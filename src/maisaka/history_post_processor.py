"""Maisaka 历史消息轮次结束后处理。"""

from dataclasses import dataclass
from json import dumps
from math import ceil

from src.common.data_models.message_component_data_model import MessageSequence, TextComponent

from .context_messages import AssistantMessage, LLMContextMessage, SessionBackedMessage, ToolResultMessage
from .history_utils import drop_leading_orphan_tool_results, drop_orphan_tool_results, normalize_tool_result_order

TRIM_TARGET_RATIO = 1.0
TRIM_THRESHOLD_RATIO = 2.0
ASSISTANT_OPTIMIZATION_KEEP_COUNT = 3


@dataclass(slots=True)
class HistoryPostProcessResult:
    """历史后处理结果。"""

    history: list[LLMContextMessage]
    removed_messages: list[LLMContextMessage]
    removed_count: int
    changed_count: int
    remaining_context_count: int


def process_chat_history_after_cycle(
    chat_history: list[LLMContextMessage],
    *,
    max_context_size: int,
    enable_context_optimization: bool = False,
) -> HistoryPostProcessResult:
    """在每轮结束后统一执行历史裁切与清理。"""

    processed_history = list(chat_history)
    processed_history, normalized_removed_count, moved_tool_result_count = _normalize_history_structure(
        processed_history
    )
    remaining_context_count = sum(1 for message in processed_history if message.count_in_context)

    optimized_removed_count = 0
    if enable_context_optimization:
        optimized_removed_messages = _trim_assistant_history_to_latest(
            processed_history,
            keep_count=ASSISTANT_OPTIMIZATION_KEEP_COUNT,
        )
        if optimized_removed_messages:
            processed_history, removed_after_optimize_count, moved_after_optimize_count = _normalize_history_structure(
                processed_history
            )
            optimized_removed_count = len(optimized_removed_messages) + removed_after_optimize_count
            moved_tool_result_count += moved_after_optimize_count
            remaining_context_count = sum(1 for message in processed_history if message.count_in_context)

    compact_removed_count = 0
    removed_messages: list[LLMContextMessage] = []
    trim_threshold = ceil(max_context_size * TRIM_THRESHOLD_RATIO)
    if remaining_context_count > trim_threshold:
        target_context_count = max(1, int(max_context_size * TRIM_TARGET_RATIO))
        removed_messages = _trim_history_to_context_target(
            processed_history,
            target_context_count=target_context_count,
        )
        processed_history, removed_after_trim_count, moved_after_trim_count = _normalize_history_structure(
            processed_history
        )
        compact_removed_count = len(removed_messages) + removed_after_trim_count
        moved_tool_result_count += moved_after_trim_count

    remaining_context_count = sum(1 for message in processed_history if message.count_in_context)
    removed_count = normalized_removed_count + optimized_removed_count + compact_removed_count
    changed_count = removed_count + moved_tool_result_count
    return HistoryPostProcessResult(
        history=processed_history,
        removed_messages=removed_messages,
        removed_count=removed_count,
        changed_count=changed_count,
        remaining_context_count=remaining_context_count,
    )


def _trim_assistant_history_to_latest(
    chat_history: list[LLMContextMessage],
    *,
    keep_count: int,
) -> list[LLMContextMessage]:
    """只保留最新的若干条 assistant 历史消息。"""

    normalized_keep_count = max(0, keep_count)
    assistant_indexes = [
        index
        for index, message in enumerate(chat_history)
        if isinstance(message, AssistantMessage)
    ]
    remove_count = len(assistant_indexes) - normalized_keep_count
    if remove_count <= 0:
        return []

    remove_indexes = set(assistant_indexes[:remove_count])
    removed_messages = [
        message
        for index, message in enumerate(chat_history)
        if index in remove_indexes
    ]
    tool_result_by_call_id = {
        message.tool_call_id: message
        for message in chat_history
        if isinstance(message, ToolResultMessage) and message.tool_call_id
    }
    preserved_tool_result_ids = {
        tool_call.call_id
        for message in removed_messages
        if isinstance(message, AssistantMessage)
        for tool_call in message.tool_calls
        if tool_call.call_id in tool_result_by_call_id
    }

    optimized_history: list[LLMContextMessage] = []
    for index, message in enumerate(chat_history):
        if index in remove_indexes:
            if isinstance(message, AssistantMessage):
                preserved_message = _build_trimmed_assistant_tool_user_message(
                    message,
                    tool_result_by_call_id=tool_result_by_call_id,
                )
                if preserved_message is not None:
                    optimized_history.append(preserved_message)
            continue
        if isinstance(message, ToolResultMessage) and message.tool_call_id in preserved_tool_result_ids:
            continue
        optimized_history.append(message)

    chat_history[:] = optimized_history
    return removed_messages


def _build_trimmed_assistant_tool_user_message(
    assistant_message: AssistantMessage,
    *,
    tool_result_by_call_id: dict[str, ToolResultMessage],
) -> SessionBackedMessage | None:
    """将被优化裁掉的 assistant 工具链折叠成普通 user 消息，避免破坏 tool 协议配对。"""

    if not assistant_message.tool_calls:
        return None

    tool_sections: list[str] = []
    for tool_call in assistant_message.tool_calls:
        args_text = dumps(tool_call.args or {}, ensure_ascii=False, sort_keys=True)
        section_lines = [
            f"- tool_call_id: {tool_call.call_id}",
            f"  tool_name: {tool_call.func_name}",
            f"  args: {args_text}",
        ]
        tool_result = tool_result_by_call_id.get(tool_call.call_id)
        if tool_result is not None:
            result_status = "success" if tool_result.success else "failed"
            section_lines.extend(
                [
                    f"  result_status: {result_status}",
                    f"  result: {tool_result.content}",
                ]
            )
        tool_sections.append("\n".join(section_lines))

    folded_text = "[已折叠的历史工具调用]\n" + "\n".join(tool_sections)
    return SessionBackedMessage(
        raw_message=MessageSequence([TextComponent(folded_text)]),
        visible_text=folded_text,
        timestamp=assistant_message.timestamp,
        message_id=f"optimized_tool_history:{assistant_message.timestamp.timestamp()}",
        source_kind="optimized_tool_history",
    )


def _normalize_history_structure(
    chat_history: list[LLMContextMessage],
) -> tuple[list[LLMContextMessage], int, int]:
    """规范化历史消息结构，保证工具调用链符合 LLM 消息协议。"""

    processed_history, orphan_removed_count = drop_orphan_tool_results(chat_history)
    processed_history, moved_tool_result_count = normalize_tool_result_order(processed_history)
    processed_history, leading_orphan_removed_count = drop_leading_orphan_tool_results(processed_history)
    return (
        processed_history,
        orphan_removed_count + leading_orphan_removed_count,
        moved_tool_result_count,
    )


def _trim_history_to_context_target(
    chat_history: list[LLMContextMessage],
    *,
    target_context_count: int,
) -> list[LLMContextMessage]:
    """移除最早的一段历史，直到普通上下文消息数量降到目标值以内。"""

    remaining_context_count = sum(1 for message in chat_history if message.count_in_context)
    if remaining_context_count <= target_context_count:
        return []

    remove_count = 0
    for message in chat_history:
        remove_count += 1
        if message.count_in_context:
            remaining_context_count -= 1
            if remaining_context_count <= target_context_count:
                break

    if remove_count <= 0:
        return []

    removed_messages = list(chat_history[:remove_count])
    del chat_history[:remove_count]
    return removed_messages
