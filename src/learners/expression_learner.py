from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

import asyncio
import difflib
import json
import re

from sqlmodel import select

from src.chat.utils.utils import is_bot_self
from src.common.data_models.expression_data_model import MaiExpression
from src.common.data_models.llm_service_data_models import LLMGenerationOptions
from src.common.database.database import get_db_session
from src.common.database.database_model import Expression
from src.common.logger import get_logger
from src.common.utils.utils_message import MessageUtils
from src.config.config import global_config
from src.plugin_runtime.hook_schema_utils import build_object_schema
from src.plugin_runtime.host.hook_spec_registry import HookSpec, HookSpecRegistry
from src.prompt.prompt_manager import prompt_manager
from src.services.llm_service import LLMServiceClient

from .expression_utils import check_expression_suitability, parse_expression_response

if TYPE_CHECKING:
    from src.chat.message_receive.message import SessionMessage
    from .jargon_miner import JargonMiner, JargonEntry


logger = get_logger("expressor")

express_learn_model = LLMServiceClient(
    task_name="learner", request_type="expression.learner"
)
summary_model = LLMServiceClient(task_name="utils", request_type="expression.summary")

def register_expression_hook_specs(registry: HookSpecRegistry) -> List[HookSpec]:
    """注册表达方式系统内置 Hook 规格。

    Args:
        registry: 目标 Hook 规格注册中心。

    Returns:
        List[HookSpec]: 实际注册的 Hook 规格列表。
    """

    return registry.register_hook_specs(
        [
            HookSpec(
                name="expression.select.before_select",
                description="表达方式选择流程开始前触发，可改写会话上下文、选择参数或中止本次选择。",
                parameters_schema=build_object_schema(
                    {
                        "chat_id": {"type": "string", "description": "当前聊天流 ID。"},
                        "chat_info": {"type": "string", "description": "用于选择表达方式的聊天上下文。"},
                        "max_num": {"type": "integer", "description": "最大可选表达方式数量。"},
                        "target_message": {"type": "string", "description": "当前目标回复消息文本。"},
                        "reply_reason": {"type": "string", "description": "规划器给出的回复理由。"},
                        "think_level": {"type": "integer", "description": "表达方式选择思考级别。"},
                    },
                    required=["chat_id", "chat_info", "max_num", "think_level"],
                ),
                default_timeout_ms=5000,
                allow_abort=True,
                allow_kwargs_mutation=True,
            ),
            HookSpec(
                name="expression.select.after_selection",
                description="表达方式选择完成后触发，可改写最终选中的表达方式列表与 ID。",
                parameters_schema=build_object_schema(
                    {
                        "chat_id": {"type": "string", "description": "当前聊天流 ID。"},
                        "chat_info": {"type": "string", "description": "用于选择表达方式的聊天上下文。"},
                        "max_num": {"type": "integer", "description": "最大可选表达方式数量。"},
                        "target_message": {"type": "string", "description": "当前目标回复消息文本。"},
                        "reply_reason": {"type": "string", "description": "规划器给出的回复理由。"},
                        "think_level": {"type": "integer", "description": "表达方式选择思考级别。"},
                        "selected_expressions": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "当前已选中的表达方式列表。",
                        },
                        "selected_expression_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "当前已选中的表达方式 ID 列表。",
                        },
                    },
                    required=[
                        "chat_id",
                        "chat_info",
                        "max_num",
                        "think_level",
                        "selected_expressions",
                        "selected_expression_ids",
                    ],
                ),
                default_timeout_ms=5000,
                allow_abort=True,
                allow_kwargs_mutation=True,
            ),
            HookSpec(
                name="expression.learn.after_extract",
                description="表达方式学习解析出表达/黑话候选后触发，可改写候选集或直接终止本轮学习。",
                parameters_schema=build_object_schema(
                    {
                        "session_id": {"type": "string", "description": "当前会话 ID。"},
                        "message_count": {"type": "integer", "description": "本轮参与学习的消息数量。"},
                        "expressions": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "解析出的表达方式候选列表。",
                        },
                        "jargon_entries": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "解析出的黑话候选列表。",
                        },
                    },
                    required=["session_id", "message_count", "expressions", "jargon_entries"],
                ),
                default_timeout_ms=5000,
                allow_abort=True,
                allow_kwargs_mutation=True,
            ),
            HookSpec(
                name="expression.learn.before_upsert",
                description="表达方式写入数据库前触发，可改写情景/风格文本或跳过本条写入。",
                parameters_schema=build_object_schema(
                    {
                        "session_id": {"type": "string", "description": "当前会话 ID。"},
                        "situation": {"type": "string", "description": "即将写入的情景文本。"},
                        "style": {"type": "string", "description": "即将写入的风格文本。"},
                    },
                    required=["session_id", "situation", "style"],
                ),
                default_timeout_ms=5000,
                allow_abort=True,
                allow_kwargs_mutation=True,
            ),
        ]
    )


class ExpressionLearner:
    def __init__(self, session_id: str) -> None:
        """初始化表达方式学习器。

        Args:
            session_id: 当前会话 ID。
        """

        self.session_id = session_id

        # 学习锁，防止并发执行学习任务
        self._learning_lock = asyncio.Lock()

        # 消息缓存
        self._last_processed_index = 0
        self.min_messages_for_extraction = 10

    @property
    def last_processed_index(self) -> int:
        """返回表达学习已经消费到的消息缓存下标。"""
        return self._last_processed_index

    def mark_all_processed(self, message_cache: List["SessionMessage"]) -> None:
        """在跳过表达学习时，将现有消息标记为已处理，避免阻塞缓存裁剪。"""
        self._last_processed_index = len(message_cache)

    def mark_processed_until(self, processed_end_index: int) -> None:
        """将指定缓存下标之前的消息标记为已处理。"""
        self._last_processed_index = max(self._last_processed_index, processed_end_index)

    def discard_processed_prefix(self, removed_count: int) -> None:
        """同步 runtime 对消息缓存前缀的裁剪。"""
        self._last_processed_index = max(0, self._last_processed_index - removed_count)

    @staticmethod
    def _get_runtime_manager() -> Any:
        """获取插件运行时管理器。

        Returns:
            Any: 插件运行时管理器单例。
        """

        from src.plugin_runtime.integration import get_plugin_runtime_manager

        return get_plugin_runtime_manager()

    @staticmethod
    def _serialize_expressions(expressions: List[Tuple[str, str, str]]) -> List[dict[str, str]]:
        """将表达方式候选序列化为 Hook 载荷。

        Args:
            expressions: 原始表达方式候选列表。

        Returns:
            List[dict[str, str]]: 序列化后的表达方式候选。
        """

        return [
            {
                "situation": str(situation).strip(),
                "style": str(style).strip(),
                "source_id": str(source_id).strip(),
            }
            for situation, style, source_id in expressions
            if str(situation).strip() and str(style).strip()
        ]

    @staticmethod
    def _deserialize_expressions(raw_expressions: Any) -> List[Tuple[str, str, str]]:
        """从 Hook 载荷恢复表达方式候选列表。

        Args:
            raw_expressions: Hook 返回的表达方式候选。

        Returns:
            List[Tuple[str, str, str]]: 恢复后的表达方式候选列表。
        """

        if not isinstance(raw_expressions, list):
            return []

        normalized_expressions: List[Tuple[str, str, str]] = []
        for raw_expression in raw_expressions:
            if not isinstance(raw_expression, dict):
                continue
            situation = str(raw_expression.get("situation") or "").strip()
            style = str(raw_expression.get("style") or "").strip()
            source_id = str(raw_expression.get("source_id") or "").strip()
            if not situation or not style:
                continue
            normalized_expressions.append((situation, style, source_id))
        return normalized_expressions

    @staticmethod
    def _serialize_jargon_entries(jargon_entries: List[Tuple[str, str]]) -> List[dict[str, str]]:
        """将黑话候选序列化为 Hook 载荷。

        Args:
            jargon_entries: 原始黑话候选列表。

        Returns:
            List[dict[str, str]]: 序列化后的黑话候选列表。
        """

        return [
            {
                "content": str(content).strip(),
                "source_id": str(source_id).strip(),
            }
            for content, source_id in jargon_entries
            if str(content).strip()
        ]

    @staticmethod
    def _deserialize_jargon_entries(raw_jargon_entries: Any) -> List[Tuple[str, str]]:
        """从 Hook 载荷恢复黑话候选列表。

        Args:
            raw_jargon_entries: Hook 返回的黑话候选列表。

        Returns:
            List[Tuple[str, str]]: 恢复后的黑话候选列表。
        """

        if not isinstance(raw_jargon_entries, list):
            return []

        normalized_entries: List[Tuple[str, str]] = []
        for raw_entry in raw_jargon_entries:
            if not isinstance(raw_entry, dict):
                continue
            content = str(raw_entry.get("content") or "").strip()
            source_id = str(raw_entry.get("source_id") or "").strip()
            if not content:
                continue
            normalized_entries.append((content, source_id))
        return normalized_entries

    def get_pending_count(self, message_cache: List["SessionMessage"]) -> int:
        """获取待处理消息数量"""
        return max(0, len(message_cache) - self._last_processed_index)

    async def learn(
        self,
        message_cache: List["SessionMessage"],
        jargon_miner: Optional["JargonMiner"] = None,
    ) -> bool:
        """学习表达方式"""
        processed_end_index = len(message_cache)
        pending_messages = message_cache[self._last_processed_index : processed_end_index]
        if not pending_messages:
            logger.debug("没有待处理消息")
            return False
        if len(pending_messages) < self.min_messages_for_extraction:
            return False

        readable_message, _, _ = await MessageUtils.build_readable_message(
            pending_messages,
            anonymize=True,
            show_lineno=True,
            extract_pictures=True,
            replace_bot_name=True,
            target_bot_name="SELF",
        )

        prompt_template = prompt_manager.get_prompt("learn_style")
        prompt_template.add_context("bot_name", global_config.bot.nickname)
        prompt_template.add_context("chat_str", readable_message)
        prompt = await prompt_manager.render_prompt(prompt_template)

        try:
            generation_result = await express_learn_model.generate_response(
                prompt,
                options=LLMGenerationOptions(temperature=0.3),
            )
            response = generation_result.response
        except Exception as e:
            logger.error(f"学习表达方式失败: {e}")
            self._last_processed_index = processed_end_index
            return False

        expressions: List[Tuple[str, str, str]]
        jargon_entries: List[Tuple[str, str]]
        expressions, jargon_entries = parse_expression_response(response)

        cached_jargon_entries = self._check_cached_jargons_in_messages(pending_messages, jargon_miner)
        if cached_jargon_entries:
            existing_contents = {content for content, _ in jargon_entries}
            for content, source_id in cached_jargon_entries:
                if content in existing_contents:
                    continue
                jargon_entries.append((content, source_id))
                existing_contents.add(content)
                logger.info(f"从缓存中找到黑话: {content}")

        if len(expressions) > 20:
            logger.info(f"表达方式数量超过20: {len(expressions)}")
            expressions = []

        if len(jargon_entries) > 30:
            logger.info(f"黑话数量超过30: {len(jargon_entries)}")
            jargon_entries = []

        after_extract_result = await self._get_runtime_manager().invoke_hook(
            "expression.learn.after_extract",
            session_id=self.session_id,
            message_count=len(pending_messages),
            expressions=self._serialize_expressions(expressions),
            jargon_entries=self._serialize_jargon_entries(jargon_entries),
        )
        if after_extract_result.aborted:
            logger.info(f"{self.session_id} 表达方式选择 Hook 中止")
            self._last_processed_index = processed_end_index
            return False

        after_extract_kwargs = after_extract_result.kwargs
        raw_expressions = after_extract_kwargs.get("expressions")
        if raw_expressions is not None:
            expressions = self._deserialize_expressions(raw_expressions)
        raw_jargon_entries = after_extract_kwargs.get("jargon_entries")
        if raw_jargon_entries is not None:
            jargon_entries = self._deserialize_jargon_entries(raw_jargon_entries)

        if jargon_entries:
            await self._process_jargon_entries(jargon_entries, pending_messages, jargon_miner)

        if not expressions:
            logger.info("没有可学习的表达方式")
            self._last_processed_index = processed_end_index
            return False

        logger.info(f"可学习的表达方式: {expressions}")
        logger.info(f"可学习的黑话: {jargon_entries}")

        learnt_expressions = self._filter_expressions(expressions, pending_messages)
        if not learnt_expressions:
            logger.info("没有可学习的表达方式通过过滤")
            self._last_processed_index = processed_end_index
            return False

        learnt_expressions_str = "\n".join(f"{situation}->{style}" for situation, style in learnt_expressions)
        logger.info(f"{self.session_id} 可学习的表达方式: \n{learnt_expressions_str}")

        for situation, style in learnt_expressions:
            before_upsert_result = await self._get_runtime_manager().invoke_hook(
                "expression.learn.before_upsert",
                session_id=self.session_id,
                situation=situation,
                style=style,
            )
            if before_upsert_result.aborted:
                logger.info(f"{self.session_id} 表达方式写入 Hook 中止: situation={situation!r}")
                continue

            upsert_kwargs = before_upsert_result.kwargs
            situation = str(upsert_kwargs.get("situation", situation) or "").strip()
            style = str(upsert_kwargs.get("style", style) or "").strip()
            if not situation or not style:
                logger.info(f"{self.session_id} 表达方式写入 Hook 中止: situation={situation!r}")
                continue
            await self._upsert_expression_to_db(situation, style)

        self._last_processed_index = processed_end_index
        return True

    def _check_cached_jargons_in_messages(
        self,
        messages: List["SessionMessage"],
        jargon_miner: Optional["JargonMiner"] = None,
    ) -> List[Tuple[str, str]]:
        """
        检查缓存中的 jargon 是否出现在 messages 中

        Args:
            jargon_miner: JargonMiner 实例，用于获取缓存的黑话

        Returns:
            List[Tuple[str, str]]: 匹配到的黑话条目列表，每个元素是 (content, source_id)
        """
        if not jargon_miner:
            return []

        # 获取缓存的所有 jargon 实例
        cached_jargons = jargon_miner.get_cached_jargons()
        if not cached_jargons:
            return []

        matched_entries: List[Tuple[str, str]] = []

        for i, msg in enumerate(messages):
            # 跳过机器人自己的消息
            if is_bot_self(msg.platform, msg.message_info.user_info.user_id):
                continue

            # 获取消息文本
            msg_text = (msg.processed_plain_text or "").strip()

            if not msg_text:
                continue

            # 检查每个缓存中的 jargon 是否出现在消息文本中
            for jargon in cached_jargons:
                if not jargon or not jargon.strip():
                    continue

                jargon_content = jargon.strip()

                # 使用正则匹配，考虑单词边界（类似 jargon_explainer 中的逻辑）
                pattern = re.escape(jargon_content)
                # 对于中文，使用更宽松的匹配；对于英文/数字，使用单词边界
                if re.search(r"[\u4e00-\u9fff]", jargon_content):
                    # 包含中文，使用更宽松的匹配
                    search_pattern = pattern
                else:
                    # 纯英文/数字，使用单词边界
                    search_pattern = r"\b" + pattern + r"\b"

                if re.search(search_pattern, msg_text, re.IGNORECASE):
                    # 找到匹配，构建条目（source_id 从 1 开始，因为 build_readable_message 的编号从 1 开始）
                    source_id = str(i + 1)
                    matched_entries.append((jargon_content, source_id))

        return matched_entries

    async def _process_jargon_entries(
        self,
        jargon_entries: List[Tuple[str, str]],
        messages: List["SessionMessage"],
        jargon_miner: Optional["JargonMiner"] = None,
    ):
        """
        处理从 expression learner 提取的黑话条目，路由到 jargon_miner

        Args:
            jargon_entries: 黑话条目列表，每个元素是 (content, source_id)
            jargon_miner: JargonMiner 实例
        """
        if not jargon_entries or not messages:
            return

        if not jargon_miner:
            logger.warning("缺少 JargonMiner 实例，无法处理黑话条目")
            return

        # 构建黑话条目格式
        entries: List["JargonEntry"] = []

        for content, source_id in jargon_entries:
            content = content.strip()
            if not content:
                continue

            # 过滤掉包含 SELF 的黑话，不学习
            if "SELF" in content:
                logger.info(f"跳过包含 SELF 的黑话：{content}")
                continue

            # TODO: 多平台兼容
            # 检查是否包含机器人名称
            bot_nickname = global_config.bot.nickname
            if bot_nickname and bot_nickname in content:
                logger.info(f"跳过包含机器人昵称的黑话：{content}")
                continue

            # 解析 source_id
            if not source_id.isdigit():
                logger.warning(f"黑话条目 source_id 无效：content={content}, source_id={source_id}")
                continue

            # build_readable_message 的编号从 1 开始
            line_index = int(source_id) - 1
            if line_index < 0 or line_index >= len(messages):
                logger.warning(f"黑话条目 source_id 超出范围：content={content}, source_id={source_id}")
                continue

            # 检查是否是机器人自己的消息
            target_msg = messages[line_index]
            if is_bot_self(target_msg.platform, target_msg.message_info.user_info.user_id):
                logger.info(f"跳过引用机器人自身消息的黑话：content={content}, source_id={source_id}")
                continue

            # 构建上下文段落（取前后各 3 条消息）
            start_idx = max(0, line_index - 3)
            end_idx = min(len(messages), line_index + 4)
            context_msgs = messages[start_idx:end_idx]

            context_paragraph = "\n".join(
                [f"[{i + 1}] {msg.processed_plain_text or ''}" for i, msg in enumerate(context_msgs)]
            )

            if not context_paragraph:
                logger.warning(f"黑话条目上下文为空：content={content}, source_id={source_id}")
                continue

            entries.append({"content": content, "raw_content": {context_paragraph}})  # type: ignore

        if not entries:
            return

        await jargon_miner.process_extracted_entries(entries)
        logger.info(f"成功处理 {len(entries)} 个黑话条目")

    # ====== 过滤方法 ======
    def _filter_expressions(
        self,
        expressions: List[Tuple[str, str, str]],
        messages: List["SessionMessage"],
    ) -> List[Tuple[str, str]]:
        """
        过滤表达方式，移除不符合条件的条目

        Args:
            expressions: 表达方式列表，每个元素是 (situation, style, source_id)

        Returns:
            过滤后的表达方式列表，每个元素是 (situation, style)
        """
        filtered_expressions: List[Tuple[str, str]] = []

        # 准备机器人名称集合（用于过滤 style 与机器人名称重复的表达）
        # TODO: 完善这里的机器人名称检测逻辑（考虑别名、不同平台的名称等）
        banned_names: set[str] = set()
        bot_nickname = global_config.bot.nickname
        if bot_nickname:
            banned_names.add(bot_nickname)
        alias_names = global_config.bot.alias_names or []
        for alias in alias_names:
            if alias_stripped := alias.strip():
                banned_names.add(alias_stripped)
        banned_casefold = {name.casefold() for name in banned_names if name}

        for situation, style, source_id in expressions:
            source_id_str = source_id.strip()
            if not source_id_str.isdigit():
                continue  # 无效的来源行编号，跳过
            line_index = int(source_id_str) - 1  # build_readable_message 的编号从 1 开始
            if line_index < 0 or line_index >= len(messages):
                continue  # 超出范围，跳过
            # 当前行的原始消息
            current_msg = messages[line_index]
            # 过滤掉从 bot 自己发言中提取到的表达方式
            if is_bot_self(current_msg.platform, current_msg.message_info.user_info.user_id):
                continue
            # 过滤掉无上下文的表达方式
            context = (current_msg.processed_plain_text or "").strip()
            if not context:
                continue
            # 过滤掉包含 SELF 的内容（不学习）
            if "SELF" in situation or "SELF" in style or "SELF" in context:
                logger.info(f"跳过包含 SELF 的表达方式：situation={situation}, style={style}, source_id={source_id}")
                continue
            # 过滤掉 style 与机器人名称/昵称重复的表达
            normalized_style = (style or "").strip()
            if normalized_style and normalized_style.casefold() in banned_casefold:
                logger.debug(
                    f"跳过 style 与机器人名称重复的表达方式：situation={situation}, style={style}, source_id={source_id}"
                )
                continue
            # 过滤掉包含 "[表情" 的内容
            if "[表情包" in situation or "[表情包" in style or "[表情包" in context:
                logger.info(f"跳过包含表情标记的表达方式：situation={situation}, style={style}, source_id={source_id}")
                continue
            # 过滤掉包含 "[图片" 的内容
            if "[图片" in situation or "[图片" in style or "[图片" in context:
                logger.info(f"跳过包含图片标记的表达方式：situation={situation}, style={style}, source_id={source_id}")
                continue

            filtered_expressions.append((situation, style))

        return filtered_expressions

    # ====== DB 操作相关 ======
    async def _upsert_expression_to_db(self, situation: str, style: str) -> None:
        """将表达方式写入数据库，存在时更新，不存在时新增。

        Args:
            situation: 表达方式对应的使用情景。
            style: 表达方式风格。
        """
        expr, similarity = self._find_similar_expression(situation) or (None, 0)
        if expr:
            # 根据相似度决定是否使用 LLM 总结
            # 完全匹配（相似度 == 1.0）时不总结，相似匹配时总结
            use_llm_summary = similarity < 1.0
            await self._update_existing_expression(expr, situation, use_llm_summary=use_llm_summary)
            return
        # 没有找到匹配的记录，创建新记录
        self._create_expression(situation, style)

    def _create_expression(self, situation: str, style: str) -> None:
        """创建新的表达方式记录。

        Args:
            situation: 表达方式对应的使用情景。
            style: 表达方式风格。
        """
        content_list = [situation]
        try:
            with get_db_session() as db:
                new_expr = Expression(
                    situation=situation,
                    style=style,
                    content_list=json.dumps(content_list),
                    count=1,
                    session_id=self.session_id,
                    last_active_time=datetime.now(),
                )
                db.add(new_expr)
                db.flush()
        except Exception as e:
            logger.error(f"创建表达方式失败: {e}")

    async def _update_existing_expression(self, expr: "MaiExpression", situation: str, use_llm_summary: bool = True):
        expr.content.append(situation)
        expr.count += 1
        expr.checked = False  # count 增加时重置 checked 为 False
        expr.last_active_time = datetime.now()

        if use_llm_summary:
            # 相似匹配时，使用 LLM 重新组合 situation
            new_situation = await self._compose_situation_text(expr.content)
            if new_situation:
                expr.situation = new_situation

        try:
            with get_db_session() as session:
                if expr.item_id is None:
                    raise ValueError("表达方式对象缺少 item_id，无法更新数据库记录")
                statement = select(Expression).filter_by(id=expr.item_id).limit(1)
                if db_expr := session.exec(statement).first():
                    db_expr.content_list = json.dumps(expr.content)
                    db_expr.count = expr.count
                    db_expr.checked = expr.checked
                    db_expr.last_active_time = expr.last_active_time
                    db_expr.situation = expr.situation  # 更新 situation
                    session.add(db_expr)
                else:
                    logger.warning(f"表达方式 ID {expr.item_id} 在数据库中未找到，无法更新")
        except Exception as e:
            logger.error(f"更新表达方式失败: {e}")

        # count 增加后，立即进行一次检查
        await self._check_expression(expr)

    # ====== 概括方法 ======
    async def _compose_situation_text(self, content_list: List[str]) -> Optional[str]:
        texts = [c.strip() for c in content_list if c.strip()]
        if not texts:
            return None
        description = "\n".join(f"- {s}" for s in texts[-10:])  # 只取最近10条进行概括
        prompt = (
            "请阅读以下多个聊天情境描述，并将它们概括成一句简短的话，长度不超过20个字，保留共同特点：\n"
            f"{description}\n"
            "只输出概括内容。"
        )
        try:
            summary_result = await summary_model.generate_response(
                prompt, options=LLMGenerationOptions(temperature=0.2)
            )
            summary = summary_result.response
            if summary := summary.strip():
                return summary
        except Exception as e:
            logger.error(f"使用 LLM 生成表达方式概括失败: {e}")
        return None

    async def _check_expression(self, expr: "MaiExpression"):
        """
        检查表达方式（在 count 增加后调用）

        Args:
            expr (MaiExpression): 要检查的表达方式对象
        """
        if not global_config.expression.expression_self_reflect:
            logger.debug("表达方式自我反思功能未启用，跳过检查")
            return

        suitable, reason, error = await check_expression_suitability(expr.situation, expr.style)
        if error:
            logger.error(f"检查表达方式时发生错误: {error}")
            return
        expr.checked = True
        expr.rejected = not suitable

        try:
            with get_db_session() as session:
                statement = select(Expression).filter_by(id=expr.item_id).limit(1)
                if db_expr := session.exec(statement).first():
                    db_expr.checked = expr.checked
                    db_expr.rejected = expr.rejected
                    session.add(db_expr)
                else:
                    logger.warning(f"表达方式 ID {expr.item_id} 在数据库中未找到，无法更新检查结果")
        except Exception as e:
            logger.error(f"更新表达方式检查结果失败: {e}")

        status = "通过" if suitable else "不通过"
        logger.info(
            f"表达方式检查完成 [ID: {expr.item_id}] - {status} | "
            f"Situation: {expr.situation[:30]}... | "
            f"Style: {expr.style[:30]}... | "
            f"Reason: {reason[:50] if reason else '无'}..."
        )

    def _find_similar_expression(
        self, situation: str, similarity_threshold: float = 0.75
    ) -> Optional[Tuple[MaiExpression, float]]:
        """在数据库中查找相似的表达方式。

        Args:
            situation: 当前待匹配的情景描述。
            similarity_threshold: 认定为相似表达方式的最低相似度阈值。

        Returns:
            Optional[Tuple[MaiExpression, float]]: 若找到最相似的表达方式，则返回
            ``(表达方式对象, 相似度)``；否则返回 ``None``。
        """
        try:
            with get_db_session(auto_commit=False) as session:
                statement = select(Expression).filter_by(session_id=self.session_id)
                expressions = session.exec(statement).all()

                best_match: Optional[MaiExpression] = None
                best_similarity = 0.0

                for db_expression in expressions:
                    expression = MaiExpression.from_db_instance(db_expression)
                    candidate_situations = [expression.situation, *expression.content]
                    for candidate_situation in candidate_situations:
                        normalized_candidate_situation = candidate_situation.strip()
                        if not normalized_candidate_situation:
                            continue
                        similarity = difflib.SequenceMatcher(
                            None,
                            situation,
                            normalized_candidate_situation,
                        ).ratio()
                        if similarity > similarity_threshold and similarity > best_similarity:
                            best_similarity = similarity
                            best_match = expression

            if best_match:
                logger.debug(f"找到相似表达方式情景 [ID: {best_match.item_id}]，相似度: {best_similarity:.2f}")
                return best_match, best_similarity

        except Exception as e:
            logger.error(f"查找相似表达方式失败: {e}")
        return None
