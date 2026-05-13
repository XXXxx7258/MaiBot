"""Maisaka 历史消息轮次结束后处理。"""

from dataclasses import dataclass
from math import ceil

from .context_messages import AssistantMessage, LLMContextMessage
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
    chat_history[:] = [
        message
        for index, message in enumerate(chat_history)
        if index not in remove_indexes
    ]
    return removed_messages


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
