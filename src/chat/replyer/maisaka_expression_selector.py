from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, List, Optional

import json

from json_repair import repair_json
from sqlmodel import select

from src.chat.message_receive.message import SessionMessage
from src.common.database.database import get_db_session
from src.common.database.database_model import Expression, ModifiedBy
from src.common.logger import get_logger
from src.common.utils.utils_config import ChatConfigUtils, ExpressionConfigUtils
from src.config.config import global_config
from src.learners.learner_utils_old import weighted_sample
from src.maisaka.context_messages import LLMContextMessage

logger = get_logger("maisaka_expression_selector")

SubAgentRunner = Callable[[str], Awaitable[str]]


@dataclass
class MaisakaExpressionSelectionResult:
    """Maisaka replyer 的表达方式选择结果。"""

    expression_habits: str = ""
    selected_expression_ids: List[int] = field(default_factory=list)


class MaisakaExpressionSelector:
    """负责在 replyer 侧完成表达方式筛选与子代理二次选择。"""

    def _can_use_expressions(self, session_id: str) -> bool:
        try:
            use_expression, _ = ExpressionConfigUtils.get_expression_config_for_chat(session_id)
            return use_expression
        except Exception as exc:
            logger.error(f"检查表达方式使用开关失败: {exc}")
            return False

    @staticmethod
    def _is_global_expression_group_marker(platform: str, item_id: str) -> bool:
        return platform == "*" and item_id == "*"

    def _resolve_expression_group_scope(self, session_id: str) -> tuple[set[str], bool]:
        related_session_ids = {session_id}
        has_global_share = False
        expression_groups = global_config.expression.expression_groups

        for expression_group in expression_groups:
            target_items = expression_group.targets
            group_session_ids: set[str] = set()
            contains_current_session = False
            contains_global_share_marker = False

            for target_item in target_items:
                platform = target_item.platform.strip()
                item_id = target_item.item_id.strip()
                if self._is_global_expression_group_marker(platform, item_id):
                    contains_global_share_marker = True
                    continue
                if not platform or not item_id:
                    continue

                target_session_ids = ChatConfigUtils.get_target_session_ids(target_item)
                group_session_ids.update(target_session_ids)
                if ChatConfigUtils.target_matches_session(target_item, session_id):
                    contains_current_session = True

            if contains_global_share_marker:
                has_global_share = True
            if contains_current_session:
                related_session_ids.update(group_session_ids)

        return related_session_ids, has_global_share

    def _load_expression_candidates(self, session_id: str) -> List[dict[str, Any]]:
        related_session_ids, has_global_share = self._resolve_expression_group_scope(session_id)

        with get_db_session(auto_commit=False) as session:
            base_query = select(Expression)
            if has_global_share:
                scoped_query = base_query
            else:
                scoped_query = base_query.where(
                    (Expression.session_id.in_(related_session_ids)) | (Expression.session_id.is_(None))  # type: ignore[attr-defined]
                )
            if global_config.expression.expression_checked_only:
                scoped_query = scoped_query.where(
                    Expression.checked.is_(True),  # type: ignore[attr-defined]
                    Expression.modified_by == ModifiedBy.USER,
                )
            expressions = session.exec(scoped_query).all()

        all_candidates = [
            {
                "id": expression.id,
                "situation": expression.situation,
                "style": expression.style,
                "count": expression.count if expression.count is not None else 1,
            }
            for expression in expressions
            if expression.id is not None and expression.situation and expression.style
        ]
        if len(all_candidates) < 10:
            return []

        high_count_candidates = [item for item in all_candidates if (item.get("count", 1) or 1) > 1]
        selected_high = (
            weighted_sample(high_count_candidates, min(len(high_count_candidates), 5))
            if len(high_count_candidates) >= 10
            else []
        )
        selected_random = weighted_sample(all_candidates, min(len(all_candidates), 5))

        candidate_pool: List[dict[str, Any]] = []
        seen_ids: set[int] = set()
        for candidate in [*selected_high, *selected_random]:
            candidate_id = candidate.get("id")
            if not isinstance(candidate_id, int) or candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            candidate_pool.append(candidate)

        return candidate_pool

    @staticmethod
    def _format_candidate_preview(candidates: List[dict[str, Any]]) -> str:
        """构建候选表达方式的简短日志预览。"""
        preview_items: List[str] = []
        for candidate in candidates[:5]:
            candidate_id = candidate.get("id")
            situation = str(candidate.get("situation") or "").strip()
            style = str(candidate.get("style") or "").strip()
            count = candidate.get("count")
            preview_items.append(
                f"id={candidate_id}, situation={situation!r}, style={style!r}, count={count}"
            )
        return "; ".join(preview_items)

    @staticmethod
    def _build_expression_habits_block(selected_expressions: List[dict[str, Any]]) -> str:
        if not selected_expressions:
            return ""
        lines = [
            f"- 当{expression['situation']}时，可以自然地用{expression['style']}这种表达习惯。"
            for expression in selected_expressions
        ]
        return "【表达习惯参考】\n" + "\n".join(lines)

    @staticmethod
    def _normalize_history_line(message: LLMContextMessage) -> str:
        content = " ".join((message.processed_plain_text or "").split()).strip()
        if len(content) > 120:
            content = content[:120] + "..."
        timestamp = message.timestamp.strftime("%H:%M:%S") if isinstance(message.timestamp, datetime) else ""
        return f"- {timestamp} {message.role}: {content}".strip()

    def _build_selector_prompt(
        self,
        *,
        chat_history: List[LLMContextMessage],
        reply_message: Optional[SessionMessage],
        reply_reason: str,
        candidates: List[dict[str, Any]],
    ) -> str:
        history_lines = [
            self._normalize_history_line(message)
            for message in chat_history[-10:]
            if (message.processed_plain_text or "").strip()
        ]
        history_block = "\n".join(history_lines) if history_lines else "- 无可用上下文"
        candidate_lines = [
            f"{candidate['id']}: 情景={candidate['situation']} | 风格={candidate['style']} | count={candidate['count']}"
            for candidate in candidates
        ]
        target_text = (reply_message.processed_plain_text or "").strip() if reply_message is not None else ""

        return (
            "你是 Maisaka 的表达方式选择子代理。\n"
            "你只负责根据最近聊天上下文，为这一次可见回复挑选最合适的表达方式。\n"
            "请只从下面候选中选择 0 到 3 条最适合当前语境的表达方式。\n"
            "优先考虑自然、贴合上下文、不生硬、不模板化。\n"
            "如果没有明显合适的，就返回空数组。\n"
            '严格只输出 JSON，对象格式为 {"selected_ids":[123,456]}。\n\n'
            f"最近上下文：\n{history_block}\n\n"
            f"目标消息：{target_text or '无'}\n"
            f"回复理由：{reply_reason.strip() or '无'}\n\n"
            f"候选表达方式：\n{chr(10).join(candidate_lines)}"
        )

    def _parse_selected_ids(self, raw_response: str, candidates: List[dict[str, Any]]) -> List[int]:
        if not raw_response.strip():
            return []
        try:
            parsed_result = json.loads(repair_json(raw_response))
        except Exception:
            logger.warning(f"表达方式选择结果解析失败: {raw_response!r}")
            return []

        raw_selected_ids = parsed_result.get("selected_ids", []) if isinstance(parsed_result, dict) else []
        if not isinstance(raw_selected_ids, list):
            return []

        candidate_map = {
            candidate["id"]: candidate
            for candidate in candidates
            if isinstance(candidate.get("id"), int)
        }
        selected_ids: List[int] = []
        for candidate_id in raw_selected_ids:
            if not isinstance(candidate_id, int):
                continue
            if candidate_id not in candidate_map or candidate_id in selected_ids:
                continue
            selected_ids.append(candidate_id)
            if len(selected_ids) >= 3:
                break
        return selected_ids

    def _build_direct_selection_result(
        self,
        *,
        session_id: str,
        candidates: List[dict[str, Any]],
    ) -> MaisakaExpressionSelectionResult:
        selected_ids = [
            candidate["id"]
            for candidate in candidates
            if isinstance(candidate.get("id"), int)
        ]
        selected_expressions = [
            candidate
            for candidate in candidates
            if candidate.get("id") in selected_ids
        ]
        self._update_last_active_time(selected_ids)
        logger.debug(
            f"表达方式直接注入：session_id={session_id} 已选数={len(selected_ids)} "
            f"selected_ids={selected_ids!r} 已选预览={self._format_candidate_preview(selected_expressions)}"
        )
        return MaisakaExpressionSelectionResult(
            expression_habits=self._build_expression_habits_block(selected_expressions),
            selected_expression_ids=selected_ids,
        )

    def _update_last_active_time(self, selected_ids: List[int]) -> None:
        if not selected_ids:
            return
        with get_db_session() as session:
            expressions = session.exec(select(Expression).where(Expression.id.in_(selected_ids))).all()  # type: ignore[attr-defined]
            now = datetime.now()
            for expression in expressions:
                expression.last_active_time = now
                session.add(expression)

    async def select_for_reply(
        self,
        *,
        session_id: str,
        chat_history: List[LLMContextMessage],
        reply_message: Optional[SessionMessage],
        reply_reason: str,
        sub_agent_runner: Optional[SubAgentRunner],
    ) -> MaisakaExpressionSelectionResult:
        del chat_history
        del reply_message
        del reply_reason
        del sub_agent_runner

        if not session_id:
            logger.info("表达方式选择已跳过：缺少 session_id")
            return MaisakaExpressionSelectionResult()
        if not self._can_use_expressions(session_id):
            logger.info(f"表达方式选择已跳过：当前会话未启用表达方式，session_id={session_id}")
            return MaisakaExpressionSelectionResult()

        candidates = self._load_expression_candidates(session_id)
        if not candidates:
            logger.info(f"表达方式选择已跳过：本地候选不足，session_id={session_id}")
            return MaisakaExpressionSelectionResult()

        return self._build_direct_selection_result(
            session_id=session_id,
            candidates=candidates,
        )


maisaka_expression_selector = MaisakaExpressionSelector()
