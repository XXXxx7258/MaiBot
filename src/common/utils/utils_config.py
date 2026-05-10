from typing import Iterator, Optional

import time

from src.common.logger import get_logger
from src.config.config import global_config

logger = get_logger("config_utils")


class ExpressionConfigUtils:
    @staticmethod
    def _find_expression_config_item(session_id: Optional[str] = None):
        if not global_config.expression.learning_list:
            return None

        if session_id:
            for config_item in global_config.expression.learning_list:
                if not config_item.platform and not config_item.item_id:
                    continue
                if ChatConfigUtils.target_matches_session(config_item, session_id):
                    return config_item

        for config_item in global_config.expression.learning_list:
            if not config_item.platform and not config_item.item_id:
                return config_item

        return None

    @staticmethod
    def get_expression_config_for_chat(session_id: Optional[str] = None) -> tuple[bool, bool, bool]:
        # sourcery skip: use-next
        """
        根据聊天会话 ID 获取表达配置。

        Args:
            session_id: 聊天会话 ID，格式为哈希值

        Returns:
            tuple: (是否使用表达, 是否学习表达, 是否启用 jargon 学习)
        """
        config_item = ExpressionConfigUtils._find_expression_config_item(session_id)
        if config_item is None:
            return True, True, True

        return (
            config_item.use_expression,
            config_item.enable_learning,
            config_item.enable_jargon_learning,
        )

    @staticmethod
    def _get_stream_id(platform: str, id_str: str, is_group: bool = False) -> Optional[str]:
        """
        根据平台、ID 字符串和是否为群聊解析已存在的聊天流 ID。

        注意：业务模块不应自行计算 session_id，这里只返回已存在的真实聊天流。
        """
        chat_type = "group" if is_group else "private"
        session_ids = ChatConfigUtils.resolve_existing_session_ids(platform, id_str, chat_type)
        return next(iter(session_ids), None)


class ChatConfigUtils:
    @staticmethod
    def _iter_matching_chat_prompts(session_id: str, is_group_chat: Optional[bool]) -> Iterator[str]:
        try:
            from src.chat.message_receive.chat_manager import chat_manager

            chat_stream = chat_manager.get_session_by_session_id(session_id)
        except Exception as e:
            logger.debug(f"解析额外 Prompt 聊天流失败: session_id={session_id} error={e}")
            chat_stream = None

        for chat_prompt_item in global_config.chat.chat_prompts:
            if hasattr(chat_prompt_item, "platform"):
                platform = str(chat_prompt_item.platform or "").strip()
                item_id = str(chat_prompt_item.item_id or "").strip()
                rule_type = str(chat_prompt_item.rule_type or "").strip()
                prompt_content = str(chat_prompt_item.prompt or "").strip()
            elif isinstance(chat_prompt_item, str):
                parts = chat_prompt_item.split(":", 3)
                if len(parts) != 4:
                    continue

                platform, item_id, rule_type, prompt_content = parts
                platform = platform.strip()
                item_id = item_id.strip()
                rule_type = rule_type.strip()
                prompt_content = prompt_content.strip()
            else:
                continue

            if not platform or not item_id or not prompt_content:
                continue

            if rule_type == "group":
                config_is_group = True
                target_attr = "group_id"
            elif rule_type == "private":
                config_is_group = False
                target_attr = "user_id"
            else:
                continue

            if is_group_chat is not None and config_is_group != is_group_chat:
                continue

            if chat_stream is not None:
                chat_stream_platform = str(chat_stream.platform or "").strip()
                chat_stream_target_id = str(getattr(chat_stream, target_attr) or "").strip()
                if chat_stream_platform == platform and chat_stream_target_id == item_id:
                    yield prompt_content
                    continue

            if session_id in ChatConfigUtils.resolve_existing_session_ids(platform, item_id, rule_type):
                yield prompt_content

    @staticmethod
    def get_chat_prompt_for_chat(session_id: str, is_group_chat: Optional[bool]) -> str:
        """根据聊天流 ID 获取匹配的额外 Prompt，允许同一聊天流配置多条。"""
        if not session_id or not global_config.chat.chat_prompts:
            return ""

        prompt_contents = list(ChatConfigUtils._iter_matching_chat_prompts(session_id, is_group_chat))
        if not prompt_contents:
            return ""

        logger.debug(f"匹配到 {len(prompt_contents)} 条聊天额外 Prompt: session_id={session_id}")
        return "\n".join(prompt_contents)

    @staticmethod
    def _target_values(target_item) -> tuple[str, str, str]:
        platform = str(target_item.platform or "").strip()
        item_id = str(target_item.item_id or "").strip()
        rule_type = str(target_item.rule_type or "").strip()
        return platform, item_id, rule_type

    @staticmethod
    def _get_chat_stream(session_id: str):
        try:
            from src.chat.message_receive.chat_manager import chat_manager

            return chat_manager.get_session_by_session_id(session_id)
        except Exception as e:
            logger.debug(f"获取聊天流失败: session_id={session_id} error={e}")
            return None

    @staticmethod
    def _get_stream_id(platform: str, id_str: str, is_group: bool = False) -> Optional[str]:
        """解析已存在的真实聊天流 ID。

        保留该方法仅为旧调用兼容；不要在新代码中用它生成资源归属 ID。
        """

        chat_type = "group" if is_group else "private"
        session_ids = ChatConfigUtils.resolve_existing_session_ids(platform, id_str, chat_type)
        return next(iter(session_ids), None)

    @staticmethod
    def resolve_existing_session_ids(platform: str, item_id: str, rule_type: str) -> set[str]:
        """按配置目标解析系统已知的真实聊天流 ID。"""

        try:
            from src.chat.message_receive.chat_manager import chat_manager

            return chat_manager.resolve_session_ids_by_target(
                platform=str(platform or "").strip(),
                target_id=str(item_id or "").strip(),
                chat_type=str(rule_type or "").strip(),
            )
        except Exception as e:
            logger.debug(
                f"解析配置目标真实聊天流失败: platform={platform} item_id={item_id} rule_type={rule_type} error={e}"
            )
            return set()

    @staticmethod
    def target_matches_session(target_item, session_id: str, is_group_chat: Optional[bool] = None) -> bool:
        """判断 platform/item_id/rule_type 配置目标是否命中当前聊天流。"""
        if not session_id:
            return False

        platform, item_id, rule_type = ChatConfigUtils._target_values(target_item)
        if not platform or not item_id:
            return False

        if rule_type == "group":
            config_is_group = True
            target_attr = "group_id"
        elif rule_type == "private":
            config_is_group = False
            target_attr = "user_id"
        else:
            return False

        if is_group_chat is not None and config_is_group != is_group_chat:
            return False

        chat_stream = ChatConfigUtils._get_chat_stream(session_id)
        if chat_stream is not None:
            chat_stream_platform = str(chat_stream.platform or "").strip()
            chat_stream_target_id = str(getattr(chat_stream, target_attr) or "").strip()
            return chat_stream_platform == platform and chat_stream_target_id == item_id

        return session_id in ChatConfigUtils.resolve_existing_session_ids(platform, item_id, rule_type)

    @staticmethod
    def get_target_session_ids(target_item) -> set[str]:
        """获取配置目标对应的已知真实聊天流 ID。"""
        platform, item_id, rule_type = ChatConfigUtils._target_values(target_item)
        if not platform or not item_id:
            return set()

        return ChatConfigUtils.resolve_existing_session_ids(platform, item_id, rule_type)

    @staticmethod
    def _resolve_is_group_chat(session_id: Optional[str]) -> Optional[bool]:
        if not session_id:
            return None

        try:
            from src.chat.message_receive.chat_manager import chat_manager

            chat_stream = chat_manager.get_session_by_session_id(session_id)
        except Exception as e:
            logger.debug(f"解析聊天流类型失败: session_id={session_id} error={e}")
            return None
        if chat_stream is None:
            return None
        return bool(chat_stream.is_group_session)

    @staticmethod
    def get_talk_value(session_id: Optional[str], is_group_chat: Optional[bool] = None) -> float:
        if is_group_chat is None:
            is_group_chat = ChatConfigUtils._resolve_is_group_chat(session_id)

        result = (
            global_config.chat.talk_value
            if is_group_chat is not False
            else global_config.chat.private_talk_value
        ) or 0.0
        if not global_config.chat.enable_talk_value_rules or not global_config.chat.talk_value_rules:
            return result
        local_time = time.localtime()
        now_min = local_time.tm_hour * 60 + local_time.tm_min

        # 优先匹配会话相关的规则
        if session_id:
            for rule in global_config.chat.talk_value_rules:
                if not rule.platform and not rule.item_id:
                    continue  # 一起留空表示全局
                if not ChatConfigUtils.target_matches_session(rule, session_id, is_group_chat):
                    continue  # 不匹配的会话 ID，跳过
                parsed_range = ChatConfigUtils.parse_range(rule.time)
                if not parsed_range:
                    continue  # 无法解析的时间范围，跳过
                start_min, end_min = parsed_range
                in_range: bool = False
                if start_min <= end_min:
                    in_range = start_min <= now_min <= end_min
                else:  # 跨天的时间范围
                    in_range = now_min >= start_min or now_min <= end_min
                if in_range:
                    return rule.value or 0.0  # 如果规则生效但没有设置值，返回 0.0

        # 没有匹配到会话相关的规则，继续匹配全局规则
        for rule in global_config.chat.talk_value_rules:
            if rule.platform or rule.item_id:
                continue  # 只匹配全局规则
            if is_group_chat is not None and (rule.rule_type == "group") != is_group_chat:
                continue
            parsed_range = ChatConfigUtils.parse_range(rule.time)
            if not parsed_range:
                continue  # 无法解析的时间范围，跳过
            start_min, end_min = parsed_range
            in_range: bool = False
            if start_min <= end_min:
                in_range = start_min <= now_min <= end_min
            else:  # 跨天的时间范围
                in_range = now_min >= start_min or now_min <= end_min
            if in_range:
                return rule.value or 0.0  # 如果规则生效但没有设置值，返回 0.0
        return result  # 如果没有任何规则生效，返回默认值

    @staticmethod
    def parse_range(range_str: str) -> Optional[tuple[int, int]]:
        """解析 "HH:MM-HH:MM" 到 (start_min, end_min)。"""
        try:
            start_str, end_str = [s.strip() for s in range_str.split("-")]
            sh, sm = [int(x) for x in start_str.split(":")]
            eh, em = [int(x) for x in end_str.split(":")]
            return sh * 60 + sm, eh * 60 + em
        except Exception:
            return None
