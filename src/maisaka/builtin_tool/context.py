"""Maisaka 内置工具执行上下文。"""

from __future__ import annotations

from base64 import b64decode
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

import re

from src.chat.utils.utils import process_llm_response
from src.common.data_models.message_component_data_model import AtComponent, EmojiComponent, MessageSequence, TextComponent
from src.config.config import global_config
from src.core.tooling import ToolExecutionResult

from ..context_messages import SessionBackedMessage
from ..message_adapter import format_speaker_content
from ..planner_message_utils import build_planner_prefix, build_session_backed_text_message

if TYPE_CHECKING:
    from ..reasoning_engine import MaisakaReasoningEngine
    from ..runtime import MaisakaHeartFlowChatting

AT_MARKER_PATTERN = re.compile(r"at\[([^\]\s]+)\]")


class BuiltinToolRuntimeContext:
    """为拆分后的内置工具提供统一运行时能力。"""

    def __init__(
        self,
        engine: "MaisakaReasoningEngine",
        runtime: "MaisakaHeartFlowChatting",
    ) -> None:
        self.engine = engine
        self.runtime = runtime

    @staticmethod
    def build_success_result(
        tool_name: str,
        content: str = "",
        structured_content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolExecutionResult:
        """构造统一工具成功结果。"""

        return ToolExecutionResult(
            tool_name=tool_name,
            success=True,
            content=content,
            structured_content=structured_content,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def build_failure_result(
        tool_name: str,
        error_message: str,
        structured_content: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolExecutionResult:
        """构造统一工具失败结果。"""

        return ToolExecutionResult(
            tool_name=tool_name,
            success=False,
            error_message=error_message,
            structured_content=structured_content,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def normalize_words(raw_words: Any) -> List[str]:
        """清洗黑话查询词条列表。"""

        if not isinstance(raw_words, list):
            return []

        normalized_words: List[str] = []
        seen_words: set[str] = set()
        for item in raw_words:
            if not isinstance(item, str):
                continue
            word = item.strip()
            if not word or word in seen_words:
                continue
            seen_words.add(word)
            normalized_words.append(word)
        return normalized_words

    @staticmethod
    def normalize_jargon_query_results(raw_results: Any) -> List[Dict[str, object]]:
        """规范化黑话查询结果列表。"""

        if not isinstance(raw_results, list):
            return []

        normalized_results: List[Dict[str, object]] = []
        for raw_item in raw_results:
            if not isinstance(raw_item, dict):
                continue
            word = str(raw_item.get("word") or "").strip()
            matches = raw_item.get("matches")
            normalized_matches: List[Dict[str, str]] = []
            if isinstance(matches, list):
                for match in matches:
                    if not isinstance(match, dict):
                        continue
                    content = str(match.get("content") or "").strip()
                    meaning = str(match.get("meaning") or "").strip()
                    if not content or not meaning:
                        continue
                    normalized_matches.append({"content": content, "meaning": meaning})

            normalized_results.append(
                {
                    "word": word,
                    "found": bool(raw_item.get("found", bool(normalized_matches))),
                    "matches": normalized_matches,
                }
            )
        return normalized_results

    @staticmethod
    def post_process_reply_text(reply_text: str) -> List[str]:
        """沿用旧回复链的文本后处理，执行分段与错别字注入。"""

        processed_segments: List[str] = []
        for segment in process_llm_response(reply_text):
            normalized_segment = segment.strip()
            if normalized_segment:
                processed_segments.append(normalized_segment)

        if processed_segments:
            return processed_segments
        return [reply_text.strip()]

    @staticmethod
    def _post_process_reply_text_chunk(text: str) -> List[str]:
        """处理回复中的普通文本片段。"""

        processed_segments: List[str] = []
        for segment in process_llm_response(text):
            normalized_segment = segment.strip()
            if normalized_segment:
                processed_segments.append(normalized_segment)
        return processed_segments

    def _build_at_component_for_message_id(self, message_id: str) -> Optional[AtComponent]:
        """根据消息编号构造 at 组件。"""

        target_message = self.runtime.find_source_message_by_id(message_id)
        if target_message is None:
            return None

        message_info = getattr(target_message, "message_info", None)
        user_info = getattr(message_info, "user_info", None)
        target_user_id = str(getattr(user_info, "user_id", "") or "").strip()
        if not target_user_id:
            return None

        target_user_nickname = str(getattr(user_info, "user_nickname", "") or "").strip()
        target_user_cardname = str(getattr(user_info, "user_cardname", "") or "").strip()
        return AtComponent(
            target_user_id=target_user_id,
            target_user_nickname=target_user_nickname or None,
            target_user_cardname=target_user_cardname or None,
        )

    def post_process_reply_message_sequences(self, reply_text: str) -> List[MessageSequence]:
        """将回复文本处理为可发送组件序列，并解析 replyer 的 at[msg_id] 标记。"""

        if not global_config.chat.enable_at or not AT_MARKER_PATTERN.search(reply_text):
            return [MessageSequence([TextComponent(segment)]) for segment in self.post_process_reply_text(reply_text)]

        message_sequences: List[MessageSequence] = []
        components: List[Any] = []
        cursor = 0

        def flush_text_chunk(text: str) -> None:
            if not text.strip():
                return
            for segment in self._post_process_reply_text_chunk(text):
                prefix = " " if components else ""
                components.append(TextComponent(f"{prefix}{segment}"))

        for match in AT_MARKER_PATTERN.finditer(reply_text):
            flush_text_chunk(reply_text[cursor : match.start()])
            message_id = match.group(1).strip()
            at_component = self._build_at_component_for_message_id(message_id)
            if at_component is None:
                components.append(TextComponent(match.group(0)))
            else:
                components.append(at_component)
            cursor = match.end()

        flush_text_chunk(reply_text[cursor:])

        if components:
            message_sequences.append(MessageSequence(components))

        if message_sequences:
            return message_sequences
        return [MessageSequence([TextComponent(reply_text.strip())])]

    def get_runtime_manager(self) -> Any:
        """获取插件运行时管理器。"""

        return self.engine._get_runtime_manager()

    def append_guided_reply_to_chat_history(self, reply_text: str) -> None:
        """将引导回复写回 Maisaka 历史。"""

        bot_name = global_config.bot.nickname.strip() or "MaiSaka"
        reply_timestamp = datetime.now()
        history_message = build_session_backed_text_message(
            speaker_name=bot_name,
            text=reply_text,
            timestamp=reply_timestamp,
            source_kind="guided_reply",
        )
        self.runtime._chat_history.append(history_message)

    def append_sent_message_to_chat_history(self, message: Any, *, source_kind: str = "guided_reply") -> bool:
        """将已发送消息写回 Maisaka 历史。"""

        runtime_append = getattr(self.runtime, "append_sent_message_to_chat_history", None)
        if callable(runtime_append):
            return bool(runtime_append(message, source_kind=source_kind))

        from ..context_messages import SessionBackedMessage
        from ..history_utils import build_prefixed_message_sequence, build_session_message_visible_text
        from ..planner_message_utils import build_planner_prefix

        user_info = message.message_info.user_info
        speaker_name = user_info.user_cardname or user_info.user_nickname or user_info.user_id
        planner_prefix = build_planner_prefix(
            timestamp=message.timestamp,
            user_name=speaker_name,
            group_card=user_info.user_cardname or "",
            message_id=message.message_id,
            include_message_id=not message.is_notify and bool(message.message_id),
        )
        history_message = SessionBackedMessage.from_session_message(
            message,
            raw_message=build_prefixed_message_sequence(message.raw_message, planner_prefix),
            visible_text=build_session_message_visible_text(
                message,
                include_reply_components=source_kind != "guided_reply",
            ),
            source_kind=source_kind,
        )
        self.runtime._chat_history.append(history_message)
        return True

    def append_sent_emoji_to_chat_history(
        self,
        *,
        emoji_base64: str,
        success_message: str,
    ) -> None:
        """将 bot 主动发送的表情包同步到 Maisaka 历史。"""

        bot_name = global_config.bot.nickname.strip() or "MaiSaka"
        reply_timestamp = datetime.now()
        planner_prefix = build_planner_prefix(
            timestamp=reply_timestamp,
            user_name=bot_name,
        )
        history_message = SessionBackedMessage(
            raw_message=MessageSequence(
                [
                    TextComponent(planner_prefix),
                    EmojiComponent(
                        binary_hash="",
                        content=success_message,
                        binary_data=b64decode(emoji_base64),
                    ),
                ]
            ),
            visible_text=format_speaker_content(
                bot_name,
                "[表情包]",
                reply_timestamp,
            ),
            timestamp=reply_timestamp,
            source_kind="guided_reply",
        )
        self.runtime._chat_history.append(history_message)
