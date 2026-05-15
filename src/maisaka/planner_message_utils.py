"""Maisaka 规划器消息构造工具。"""

from datetime import datetime
from html import escape
from typing import Optional

from src.chat.message_receive.message import SessionMessage
from src.common.data_models.message_component_data_model import MessageSequence, TextComponent

from .context_messages import SessionBackedMessage
from .message_adapter import format_speaker_content


def build_planner_prefix(
    *,
    timestamp: datetime,
    user_name: str,
    group_card: str = "",
    message_id: Optional[str] = None,
    include_message_id: bool = True,
) -> str:
    """构造 Maisaka 规划器使用的统一消息前缀。

    Args:
        timestamp: 消息时间。
        user_name: 展示给规划器的用户名。
        group_card: 群昵称。
        message_id: 消息 ID。
        include_message_id: 是否输出 `msg_id` 段。

    Returns:
        str: 拼接完成的规划器前缀。
    """

    message_attrs = [
        f'time="{escape(timestamp.strftime("%H:%M:%S"), quote=True)}"',
        f'user="{escape(user_name, quote=True)}"',
    ]
    if include_message_id:
        message_attrs.insert(0, f'msg_id="{escape(message_id or "", quote=True)}"')

    normalized_group_card = group_card.strip()
    if normalized_group_card:
        message_attrs.append(f'group_card="{escape(normalized_group_card, quote=True)}"')
    return f"<message {' '.join(message_attrs)}>\n"


def build_planner_user_prefix_from_session_message(message: SessionMessage) -> str:
    """根据真实会话消息构造规划器前缀。

    Args:
        message: 原始会话消息。

    Returns:
        str: 规划器前缀字符串。
    """

    user_info = message.message_info.user_info
    user_name = user_info.user_nickname or user_info.user_id
    return build_planner_prefix(
        timestamp=message.timestamp,
        user_name=user_name,
        group_card=user_info.user_cardname or "",
        message_id=message.message_id,
        include_message_id=not message.is_notify and bool(message.message_id),
    )


def build_session_backed_text_message(
    *,
    speaker_name: str,
    text: str,
    timestamp: datetime,
    source_kind: str,
    group_card: str = "",
    message_id: Optional[str] = None,
    include_message_id: bool = True,
) -> SessionBackedMessage:
    """构造带规划器前缀的纯文本历史消息。

    Args:
        speaker_name: 发言者名称。
        text: 发言内容。
        timestamp: 发言时间。
        source_kind: 上下文来源类型。
        group_card: 群昵称。
        message_id: 消息 ID。
        include_message_id: 是否输出 `msg_id` 段。

    Returns:
        SessionBackedMessage: 可直接写入历史的上下文消息。
    """

    planner_prefix = build_planner_prefix(
        timestamp=timestamp,
        user_name=speaker_name,
        group_card=group_card,
        message_id=message_id,
        include_message_id=include_message_id,
    )
    return SessionBackedMessage(
        raw_message=MessageSequence([TextComponent(f"{planner_prefix}{text}")]),
        visible_text=format_speaker_content(
            speaker_name,
            text,
            timestamp,
            message_id if include_message_id else None,
        ),
        timestamp=timestamp,
        message_id=message_id,
        source_kind=source_kind,
    )
