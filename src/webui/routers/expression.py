"""表达方式管理 API 路由"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlmodel import col, delete, select

from src.chat.message_receive.chat_manager import chat_manager as _chat_manager
from src.common.database.database import get_db_session
from src.common.database.database_model import ChatSession, Expression, Messages, ModifiedBy
from src.common.logger import get_logger
from src.common.utils.utils_config import ChatConfigUtils, ExpressionConfigUtils
from src.config.config import global_config
from src.webui.dependencies import require_auth

logger = get_logger("webui.expression")
EXCLUDE_IDS_QUERY = Query(None, description="需要排除的表达方式 ID")

# 创建路由器
router = APIRouter(prefix="/expression", tags=["Expression"], dependencies=[Depends(require_auth)])


class ExpressionResponse(BaseModel):
    """表达方式响应"""

    id: int
    situation: str
    style: str
    last_active_time: float
    chat_id: str
    chat_name: Optional[str] = None
    create_date: Optional[float]
    checked: bool
    rejected: bool
    modified_by: Optional[str] = None  # 'ai' 或 'user' 或 None


class ExpressionListResponse(BaseModel):
    """表达方式列表响应"""

    success: bool
    total: int
    page: int
    page_size: int
    data: List[ExpressionResponse]


class ExpressionDetailResponse(BaseModel):
    """表达方式详情响应"""

    success: bool
    data: ExpressionResponse


class ExpressionCreateRequest(BaseModel):
    """表达方式创建请求"""

    situation: str
    style: str
    chat_id: str


class ExpressionUpdateRequest(BaseModel):
    """表达方式更新请求"""

    situation: Optional[str] = None
    style: Optional[str] = None
    chat_id: Optional[str] = None


class ExpressionUpdateResponse(BaseModel):
    """表达方式更新响应"""

    success: bool
    message: str
    data: Optional[ExpressionResponse] = None


class ExpressionDeleteResponse(BaseModel):
    """表达方式删除响应"""

    success: bool
    message: str


class ExpressionCreateResponse(BaseModel):
    """表达方式创建响应"""

    success: bool
    message: str
    data: ExpressionResponse


class ExpressionExportItem(BaseModel):
    """表达方式导出条目，不包含会话 ID。"""

    situation: str
    style: str
    content_list: str = "[]"
    count: int = 0
    last_active_time: Optional[str] = None
    create_time: Optional[str] = None
    checked: bool = False
    rejected: bool = False
    modified_by: Optional[str] = None


class ExpressionExportRequest(BaseModel):
    """表达方式导出请求。"""

    chat_id: str
    ids: Optional[List[int]] = None


class ExpressionExportResponse(BaseModel):
    """表达方式导出响应。"""

    success: bool = True
    version: int = 1
    type: str = "maibot.expression.export"
    exported_at: str
    source_chat_name: str
    count: int
    expressions: List[ExpressionExportItem]


class ExpressionImportRequest(BaseModel):
    """表达方式导入请求。"""

    chat_id: str
    expressions: List[ExpressionExportItem]


class ExpressionImportResponse(BaseModel):
    """表达方式导入响应。"""

    success: bool = True
    message: str
    imported_count: int
    skipped_count: int = 0
    failed_count: int = 0


class ExpressionClearRequest(BaseModel):
    """清除指定聊天流表达方式请求。"""

    chat_id: str


class ExpressionClearResponse(BaseModel):
    """清除指定聊天流表达方式响应。"""

    success: bool = True
    message: str
    deleted_count: int = 0


def require_existing_chat_id(chat_id: Optional[str]) -> str:
    """校验资源归属的聊天流 ID 必须是真实存在的会话。"""

    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise HTTPException(status_code=400, detail="缺少聊天流 ID")
    if _chat_manager.get_existing_session_by_session_id(normalized_chat_id) is None:
        raise HTTPException(status_code=400, detail=f"聊天流不存在: {normalized_chat_id}")
    return normalized_chat_id


def require_non_empty_chat_id(chat_id: Optional[str]) -> str:
    """校验聊天流 ID 非空，不要求会话仍存在。"""

    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise HTTPException(status_code=400, detail="缺少聊天流 ID")
    return normalized_chat_id


def get_chat_name_from_latest_message(chat_id: str, db_session: Any) -> Optional[str]:
    """从最近消息中解析聊天显示名称。"""

    statement = (
        select(Messages).where(col(Messages.session_id) == chat_id).order_by(col(Messages.timestamp).desc()).limit(1)
    )
    message = db_session.exec(statement).first()
    if not message:
        return None
    if message.group_id:
        return message.group_name or f"群聊{message.group_id}"
    private_name = message.user_cardname or message.user_nickname or (f"用户{message.user_id}" if message.user_id else None)
    return f"{private_name}的私聊" if private_name else None


def get_chat_name_from_session_record(chat_session: ChatSession) -> str:
    """从会话记录推断兜底显示名称。"""

    if chat_session.group_id:
        return f"群聊{chat_session.group_id}"
    if chat_session.user_id:
        return f"用户{chat_session.user_id}的私聊"
    return chat_session.session_id


def get_chat_name(chat_id: str, db_session: Optional[Any] = None) -> str:
    """根据聊天 ID 获取聊天名称。

    Args:
        chat_id: 聊天会话 ID。
        db_session: 可选数据库会话，用于从历史消息中解析群名或私聊用户名。

    Returns:
        str: 聊天显示名称，获取失败时返回原始聊天 ID。
    """

    try:
        if name := _chat_manager.get_session_name(chat_id):
            return name
        if db_session and (name := get_chat_name_from_latest_message(chat_id, db_session)):
            return name
        session = _chat_manager.get_session_by_session_id(chat_id)
        if session:
            if session.group_id:
                return f"群聊{session.group_id}"
            if session.user_id:
                return f"用户{session.user_id}"
        return chat_id
    except Exception:
        return chat_id


def expression_to_response(expression: Expression, db_session: Optional[Any] = None) -> ExpressionResponse:
    """将表达方式模型转换为响应对象。

    Args:
        expression: 数据库中的表达方式记录。

    Returns:
        ExpressionResponse: WebUI 可直接序列化的响应对象。
    """
    last_active_time = expression.last_active_time.timestamp() if expression.last_active_time else 0.0
    create_date = expression.create_time.timestamp() if expression.create_time else None
    chat_id = expression.session_id or ""
    return ExpressionResponse(
        id=expression.id if expression.id is not None else 0,
        situation=expression.situation,
        style=expression.style,
        last_active_time=last_active_time,
        chat_id=chat_id,
        chat_name=get_chat_name(chat_id, db_session) if chat_id else None,
        create_date=create_date,
        checked=expression.checked,
        rejected=expression.rejected,
        modified_by=expression.modified_by.value if expression.modified_by else None,
    )


def expression_to_export_item(expression: Expression) -> ExpressionExportItem:
    """将表达方式转换为可迁移的导出条目，不包含聊天流 ID。"""

    return ExpressionExportItem(
        situation=expression.situation,
        style=expression.style,
        content_list=expression.content_list,
        count=expression.count,
        last_active_time=expression.last_active_time.isoformat() if expression.last_active_time else None,
        create_time=expression.create_time.isoformat() if expression.create_time else None,
        checked=expression.checked,
        rejected=expression.rejected,
        modified_by=expression.modified_by.value if expression.modified_by else None,
    )


def parse_export_datetime(value: Optional[str]) -> datetime:
    """解析导入文件中的时间字段，失败时使用当前时间。"""

    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now()


def parse_modified_by(value: Optional[str]) -> Optional[ModifiedBy]:
    """解析导入文件中的修改来源字段。"""

    if not value:
        return None
    try:
        return ModifiedBy(value)
    except ValueError:
        return None


def get_chat_names_batch(chat_ids: List[str]) -> Dict[str, str]:
    """批量获取聊天名称。

    Args:
        chat_ids: 需要查询的聊天会话 ID 列表。

    Returns:
        Dict[str, str]: 以聊天 ID 为键、显示名称为值的映射。
    """
    result = {cid: cid for cid in chat_ids}  # 默认值为原始ID
    try:
        for chat_id in chat_ids:
            result[chat_id] = get_chat_name(chat_id)
    except Exception as e:
        logger.warning(f"批量获取聊天名称失败: {e}")
    return result


class ChatInfo(BaseModel):
    """聊天信息"""

    chat_id: str
    chat_name: str
    platform: Optional[str] = None
    is_group: bool = False
    use_expression: bool = True
    enable_learning: bool = True


def build_chat_info(chat_id: str, db_session: Any, chat_session: Optional[ChatSession] = None) -> ChatInfo:
    """根据聊天流 ID 构建 WebUI 展示用的聊天信息。"""

    use_expression, enable_learning, _ = ExpressionConfigUtils.get_expression_config_for_chat(chat_id)
    return ChatInfo(
        chat_id=chat_id,
        chat_name=get_chat_name(chat_id, db_session),
        platform=chat_session.platform if chat_session else None,
        is_group=bool(chat_session and chat_session.group_id),
        use_expression=use_expression,
        enable_learning=enable_learning,
    )


class ChatListResponse(BaseModel):
    """聊天列表响应"""

    success: bool
    data: List[ChatInfo]


class ExpressionGroupInfo(BaseModel):
    """表达互通组信息。"""

    index: int
    name: str
    chat_ids: List[str]
    members: List[ChatInfo]
    is_global: bool = False


class ExpressionGroupListResponse(BaseModel):
    """表达互通组列表响应。"""

    success: bool
    data: List[ExpressionGroupInfo]


@router.get("/chats", response_model=ChatListResponse)
async def get_chat_list() -> ChatListResponse:
    """获取所有聊天列表。

    Returns:
        ChatListResponse: 可用于下拉选择的聊天列表。
    """
    try:
        chat_by_id: Dict[str, ChatInfo] = {}
        with get_db_session() as session:
            expression_chat_ids = {chat_id for chat_id in session.exec(select(Expression.session_id)).all() if chat_id}
            for session_id in expression_chat_ids:
                chat_session = session.exec(select(ChatSession).where(col(ChatSession.session_id) == session_id)).first()
                chat_by_id[session_id] = build_chat_info(session_id, session, chat_session)

        # 按名称排序
        chat_list = list(chat_by_id.values())
        chat_list.sort(key=lambda x: x.chat_name)

        return ChatListResponse(success=True, data=chat_list)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取聊天列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取聊天列表失败: {str(e)}") from e


def is_global_expression_group_marker(platform: str, item_id: str) -> bool:
    """判断互通组成员是否为全局共享标记。"""
    return platform == "*" and item_id == "*"


@router.get("/groups", response_model=ExpressionGroupListResponse)
async def get_expression_groups() -> ExpressionGroupListResponse:
    """获取已解析的表达互通组。"""
    try:
        groups: List[ExpressionGroupInfo] = []
        with get_db_session() as session:
            all_expression_chat_ids = {
                chat_id for chat_id in session.exec(select(Expression.session_id)).all() if chat_id
            }
            for index, expression_group in enumerate(global_config.expression.expression_groups):
                chat_ids: set[str] = set()
                is_global = False

                for target_item in expression_group.expression_groups:
                    platform = str(target_item.platform or "").strip()
                    item_id = str(target_item.item_id or "").strip()
                    if not platform and not item_id:
                        continue
                    if is_global_expression_group_marker(platform, item_id):
                        is_global = True
                        continue
                    chat_ids.update(ChatConfigUtils.get_target_session_ids(target_item))

                if not expression_group.expression_groups:
                    is_global = True

                resolved_chat_ids = sorted(all_expression_chat_ids if is_global else chat_ids & all_expression_chat_ids)
                members = [build_chat_info(chat_id, session) for chat_id in resolved_chat_ids]
                groups.append(
                    ExpressionGroupInfo(
                        index=index,
                        name=f"互通组 {index + 1}",
                        chat_ids=resolved_chat_ids,
                        members=members,
                        is_global=is_global,
                    )
                )

        return ExpressionGroupListResponse(success=True, data=groups)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取表达互通组失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取表达互通组失败: {str(e)}") from e


@router.get("/list", response_model=ExpressionListResponse)
async def get_expression_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    chat_id: Optional[str] = Query(None, description="聊天ID筛选"),
    chat_ids: Optional[List[str]] = Query(None, description="multiple chat ids"),
) -> ExpressionListResponse:
    """获取表达方式列表。

    Args:
        page: 页码，从 1 开始。
        page_size: 每页数量，范围为 1-100。
        search: 搜索关键词，用于匹配情景和风格。
        chat_id: 聊天 ID 筛选条件。

    Returns:
        ExpressionListResponse: 分页后的表达方式列表。
    """
    try:
        # 构建查询
        statement = select(Expression)

        # 搜索过滤
        if search:
            statement = statement.where(
                (col(Expression.situation).contains(search)) | (col(Expression.style).contains(search))
            )

        # 聊天ID过滤
        if chat_id:
            statement = statement.where(col(Expression.session_id) == chat_id)
        elif chat_ids:
            statement = statement.where(col(Expression.session_id).in_(chat_ids))

        # 排序：最后活跃时间倒序（NULL 值放在最后）
        statement = statement.order_by(
            case((col(Expression.last_active_time).is_(None), 1), else_=0),
            col(Expression.last_active_time).desc(),
        )

        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        with get_db_session() as session:
            expressions = session.exec(statement).all()

            count_statement = select(Expression.id)
            if search:
                count_statement = count_statement.where(
                    (col(Expression.situation).contains(search)) | (col(Expression.style).contains(search))
                )
            if chat_id:
                count_statement = count_statement.where(col(Expression.session_id) == chat_id)
            elif chat_ids:
                count_statement = count_statement.where(col(Expression.session_id).in_(chat_ids))
            total = len(session.exec(count_statement).all())
            data = [expression_to_response(expr, session) for expr in expressions]

        return ExpressionListResponse(success=True, total=total, page=page, page_size=page_size, data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取表达方式列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取表达方式列表失败: {str(e)}") from e


@router.post("/export", response_model=ExpressionExportResponse)
async def export_expressions(request: ExpressionExportRequest) -> ExpressionExportResponse:
    """按单个聊天流导出表达方式，导出内容不包含 session_id。"""

    try:
        chat_id = require_non_empty_chat_id(request.chat_id)

        statement = select(Expression).where(col(Expression.session_id) == chat_id)
        if request.ids:
            statement = statement.where(col(Expression.id).in_(request.ids))
        statement = statement.order_by(
            case((col(Expression.last_active_time).is_(None), 1), else_=0),
            col(Expression.last_active_time).desc(),
        )

        with get_db_session() as session:
            expressions = session.exec(statement).all()
            if request.ids and len(expressions) != len(set(request.ids)):
                found_ids = {expression.id for expression in expressions}
                missing_ids = sorted(set(request.ids) - found_ids)
                raise HTTPException(status_code=400, detail=f"部分表达方式不属于该聊天或不存在: {missing_ids}")

            items = [expression_to_export_item(expression) for expression in expressions]
            chat_name = get_chat_name(chat_id, session)

        return ExpressionExportResponse(
            exported_at=datetime.now().isoformat(),
            source_chat_name=chat_name,
            count=len(items),
            expressions=items,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"导出表达方式失败: {e}")
        raise HTTPException(status_code=500, detail=f"导出表达方式失败: {str(e)}") from e


@router.post("/import", response_model=ExpressionImportResponse)
async def import_expressions(request: ExpressionImportRequest) -> ExpressionImportResponse:
    """将表达方式 JSON 导入到指定聊天流。"""

    try:
        chat_id = require_existing_chat_id(request.chat_id)
        if not request.expressions:
            raise HTTPException(status_code=400, detail="导入文件中没有表达方式")

        imported_count = 0
        skipped_count = 0
        failed_count = 0

        with get_db_session() as session:
            existing_pairs = {
                (situation, style)
                for situation, style in session.exec(
                    select(Expression.situation, Expression.style).where(col(Expression.session_id) == chat_id)
                ).all()
            }

            for item in request.expressions:
                situation = item.situation.strip()
                style = item.style.strip()
                if not situation or not style:
                    failed_count += 1
                    continue

                dedupe_key = (situation, style)
                if dedupe_key in existing_pairs:
                    skipped_count += 1
                    continue

                expression = Expression(
                    situation=situation,
                    style=style,
                    content_list=item.content_list,
                    count=item.count,
                    last_active_time=parse_export_datetime(item.last_active_time),
                    create_time=parse_export_datetime(item.create_time),
                    session_id=chat_id,
                    checked=item.checked,
                    rejected=item.rejected,
                    modified_by=parse_modified_by(item.modified_by),
                )
                session.add(expression)
                existing_pairs.add(dedupe_key)
                imported_count += 1

        logger.info(
            f"导入表达方式完成: chat_id={chat_id}, imported={imported_count}, "
            f"skipped={skipped_count}, failed={failed_count}"
        )
        return ExpressionImportResponse(
            message=f"导入完成：成功 {imported_count} 个，跳过 {skipped_count} 个，失败 {failed_count} 个",
            imported_count=imported_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"导入表达方式失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入表达方式失败: {str(e)}") from e


@router.post("/clear", response_model=ExpressionClearResponse)
async def clear_expressions(request: ExpressionClearRequest) -> ExpressionClearResponse:
    """清除指定聊天流下的全部表达方式，允许清除旧的无效 session_id 数据。"""

    try:
        chat_id = require_non_empty_chat_id(request.chat_id)
        with get_db_session() as session:
            existing_ids = list(session.exec(select(Expression.id).where(col(Expression.session_id) == chat_id)).all())
            if existing_ids:
                session.exec(delete(Expression).where(col(Expression.session_id) == chat_id))

        deleted_count = len(existing_ids)
        logger.info(f"清除聊天流表达方式完成: chat_id={chat_id}, deleted={deleted_count}")
        return ExpressionClearResponse(message=f"成功清除 {deleted_count} 个表达方式", deleted_count=deleted_count)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"清除表达方式失败: {e}")
        raise HTTPException(status_code=500, detail=f"清除表达方式失败: {str(e)}") from e


@router.get("/{expression_id}", response_model=ExpressionDetailResponse)
async def get_expression_detail(expression_id: int) -> ExpressionDetailResponse:
    """获取表达方式详细信息。

    Args:
        expression_id: 表达方式 ID。

    Returns:
        ExpressionDetailResponse: 指定表达方式的详细信息。
    """
    try:
        with get_db_session() as session:
            statement = select(Expression).where(col(Expression.id) == expression_id).limit(1)
            expression = session.exec(statement).first()

            if not expression:
                raise HTTPException(status_code=404, detail=f"未找到 ID 为 {expression_id} 的表达方式")

            data = expression_to_response(expression, session)

        return ExpressionDetailResponse(success=True, data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取表达方式详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取表达方式详情失败: {str(e)}") from e


@router.post("/", response_model=ExpressionCreateResponse)
async def create_expression(
    request: ExpressionCreateRequest,
) -> ExpressionCreateResponse:
    """创建新的表达方式。

    Args:
        request: 创建表达方式所需的请求数据。

    Returns:
        ExpressionCreateResponse: 创建结果和新表达方式数据。
    """
    try:
        current_time = datetime.now()
        chat_id = require_existing_chat_id(request.chat_id)

        # 创建表达方式
        with get_db_session() as session:
            expression = Expression(
                situation=request.situation,
                style=request.style,
                content_list="[]",
                count=0,
                last_active_time=current_time,
                create_time=current_time,
                session_id=chat_id,
            )
            session.add(expression)
            session.flush()
            expression_id = expression.id
            data = expression_to_response(expression, session)

        logger.info(f"表达方式已创建: ID={expression_id}, situation={request.situation}")

        return ExpressionCreateResponse(success=True, message="表达方式创建成功", data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"创建表达方式失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建表达方式失败: {str(e)}") from e


@router.patch("/{expression_id}", response_model=ExpressionUpdateResponse)
async def update_expression(
    expression_id: int,
    request: ExpressionUpdateRequest,
) -> ExpressionUpdateResponse:
    """增量更新表达方式。

    Args:
        expression_id: 表达方式 ID。
        request: 只包含需要更新字段的请求数据。

    Returns:
        ExpressionUpdateResponse: 更新结果和更新后的表达方式数据。
    """
    try:
        # 只更新提供的字段
        update_data = request.model_dump(exclude_unset=True)

        # 映射 API 字段名到数据库字段名
        if "chat_id" in update_data:
            update_data["session_id"] = require_existing_chat_id(update_data.pop("chat_id"))

        if not update_data:
            raise HTTPException(status_code=400, detail="未提供任何需要更新的字段")

        # 更新最后活跃时间
        update_data["last_active_time"] = datetime.now()

        # 执行更新
        with get_db_session() as session:
            db_expression = session.exec(select(Expression).where(col(Expression.id) == expression_id).limit(1)).first()
            if not db_expression:
                raise HTTPException(status_code=404, detail=f"未找到 ID 为 {expression_id} 的表达方式")
            if "situation" in update_data:
                db_expression.situation = update_data["situation"]
            if "style" in update_data:
                db_expression.style = update_data["style"]
            if "session_id" in update_data:
                db_expression.session_id = update_data["session_id"]
            db_expression.last_active_time = update_data["last_active_time"]
            session.add(db_expression)
            data = expression_to_response(db_expression, session)

        logger.info(f"表达方式已更新: ID={expression_id}, 字段: {list(update_data.keys())}")

        return ExpressionUpdateResponse(success=True, message=f"成功更新 {len(update_data)} 个字段", data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"更新表达方式失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新表达方式失败: {str(e)}") from e


@router.delete("/{expression_id}", response_model=ExpressionDeleteResponse)
async def delete_expression(expression_id: int) -> ExpressionDeleteResponse:
    """删除表达方式。

    Args:
        expression_id: 表达方式 ID。

    Returns:
        ExpressionDeleteResponse: 删除结果。
    """
    try:
        with get_db_session() as session:
            statement = select(Expression).where(col(Expression.id) == expression_id).limit(1)
            expression = session.exec(statement).first()

            if not expression:
                raise HTTPException(status_code=404, detail=f"未找到 ID 为 {expression_id} 的表达方式")

            # 记录删除信息
            situation = expression.situation

            session.exec(delete(Expression).where(col(Expression.id) == expression_id))

        logger.info(f"表达方式已删除: ID={expression_id}, situation={situation}")

        return ExpressionDeleteResponse(success=True, message=f"成功删除表达方式: {situation}")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"删除表达方式失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除表达方式失败: {str(e)}") from e


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""

    ids: List[int]


@router.post("/batch/delete", response_model=ExpressionDeleteResponse)
async def batch_delete_expressions(
    request: BatchDeleteRequest,
) -> ExpressionDeleteResponse:
    """批量删除表达方式。

    Args:
        request: 包含要删除表达方式 ID 列表的请求。

    Returns:
        ExpressionDeleteResponse: 批量删除结果。
    """
    try:
        if not request.ids:
            raise HTTPException(status_code=400, detail="未提供要删除的表达方式ID")

        # 查找所有要删除的表达方式
        with get_db_session() as session:
            statements = select(Expression.id).where(col(Expression.id).in_(request.ids))
            found_ids = list(session.exec(statements).all())

        # 检查是否有未找到的ID
        if not_found_ids := set(request.ids) - set(found_ids):
            logger.warning(f"部分表达方式未找到: {not_found_ids}")

        # 执行批量删除
        with get_db_session() as session:
            result = session.exec(delete(Expression).where(col(Expression.id).in_(found_ids)))
            deleted_count = result.rowcount or 0

        logger.info(f"批量删除了 {deleted_count} 个表达方式")

        return ExpressionDeleteResponse(success=True, message=f"成功删除 {deleted_count} 个表达方式")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"批量删除表达方式失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量删除表达方式失败: {str(e)}") from e


@router.get("/stats/summary")
async def get_expression_stats() -> Dict[str, Any]:
    """获取表达方式统计数据。

    Returns:
        Dict[str, Any]: 表达方式数量、近期新增和聊天分布统计。
    """
    try:
        with get_db_session() as session:
            total = len(session.exec(select(Expression.id)).all())

            chat_stats = {}
            for chat_id in session.exec(select(Expression.session_id)).all():
                if chat_id:
                    chat_stats[chat_id] = chat_stats.get(chat_id, 0) + 1

            seven_days_ago = datetime.now() - timedelta(days=7)
            recent_statement = (
                select(func.count())
                .select_from(Expression)
                .where(col(Expression.create_time).is_not(None), col(Expression.create_time) >= seven_days_ago)
            )
            recent = session.exec(recent_statement).one()

        return {
            "success": True,
            "data": {
                "total": total,
                "recent_7days": recent,
                "chat_count": len(chat_stats),
                "top_chats": dict(sorted(chat_stats.items(), key=lambda x: x[1], reverse=True)[:10]),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取统计数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计数据失败: {str(e)}") from e


# ============ 审核相关接口 ============


class ReviewStatsResponse(BaseModel):
    """审核统计响应"""

    total: int
    unchecked: int
    passed: int
    rejected: int
    ai_checked: int
    user_checked: int


def apply_review_filter(statement: Any, filter_type: str) -> Any:
    """按审核状态过滤表达方式查询。"""
    if filter_type == "unchecked":
        return statement.where(col(Expression.checked).is_(False))
    if filter_type == "passed":
        return statement.where(col(Expression.checked).is_(True), col(Expression.rejected).is_(False))
    if filter_type == "rejected":
        return statement.where(col(Expression.checked).is_(True), col(Expression.rejected).is_(True))
    return statement


def count_expressions(session: Any, statement: Any) -> int:
    """统计表达方式查询结果数量。"""
    return len(session.exec(statement).all())


@router.get("/review/stats", response_model=ReviewStatsResponse)
async def get_review_stats() -> ReviewStatsResponse:
    """获取审核统计数据。

    Returns:
        ReviewStatsResponse: 审核统计数据。
    """
    try:
        with get_db_session() as session:
            total = count_expressions(session, select(Expression.id))
            unchecked = count_expressions(session, apply_review_filter(select(Expression.id), "unchecked"))
            passed = count_expressions(session, apply_review_filter(select(Expression.id), "passed"))
            rejected = count_expressions(session, apply_review_filter(select(Expression.id), "rejected"))
            ai_checked = count_expressions(
                session,
                select(Expression.id).where(
                    col(Expression.checked).is_(True),
                    col(Expression.modified_by) == ModifiedBy.AI,
                ),
            )
            user_checked = count_expressions(
                session,
                select(Expression.id).where(
                    col(Expression.checked).is_(True),
                    col(Expression.modified_by) == ModifiedBy.USER,
                ),
            )

        return ReviewStatsResponse(
            total=total,
            unchecked=unchecked,
            passed=passed,
            rejected=rejected,
            ai_checked=ai_checked,
            user_checked=user_checked,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取审核统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取审核统计失败: {str(e)}") from e


class ReviewListResponse(BaseModel):
    """审核列表响应"""

    success: bool
    total: int
    page: int
    page_size: int
    data: List[ExpressionResponse]


@router.get("/review/list", response_model=ReviewListResponse)
async def get_review_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    filter_type: str = Query("unchecked", description="筛选类型: unchecked/passed/rejected/all"),
    order: str = Query("latest", description="排序方式: latest/random"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    chat_id: Optional[str] = Query(None, description="聊天ID筛选"),
    exclude_ids: Optional[List[int]] = EXCLUDE_IDS_QUERY,
) -> ReviewListResponse:
    """获取待审核或已审核的表达方式列表。

    Args:
        page: 页码。
        page_size: 每页数量。
        filter_type: 筛选类型，可选 unchecked、passed、rejected 或 all。
        order: 排序方式，可选 latest 或 random。
        search: 搜索关键词。
        chat_id: 聊天 ID 筛选条件。
        exclude_ids: 需要排除的表达方式 ID。

    Returns:
        ReviewListResponse: 审核列表响应。
    """
    try:
        statement = apply_review_filter(select(Expression), filter_type)
        # all 不需要额外过滤

        # 搜索过滤
        if search:
            statement = statement.where(
                (col(Expression.situation).contains(search)) | (col(Expression.style).contains(search))
            )

        # 聊天ID过滤
        if chat_id:
            statement = statement.where(col(Expression.session_id) == chat_id)

        if exclude_ids:
            statement = statement.where(~col(Expression.id).in_(exclude_ids))

        if order == "random":
            statement = statement.order_by(func.random())
        else:
            # 排序：创建时间倒序
            statement = statement.order_by(
                case((col(Expression.create_time).is_(None), 1), else_=0),
                col(Expression.create_time).desc(),
            )

        offset = (page - 1) * page_size
        statement = statement.offset(offset).limit(page_size)

        with get_db_session() as session:
            expressions = session.exec(statement).all()

            count_statement = apply_review_filter(select(Expression.id), filter_type)
            if search:
                count_statement = count_statement.where(
                    (col(Expression.situation).contains(search)) | (col(Expression.style).contains(search))
                )
            if chat_id:
                count_statement = count_statement.where(col(Expression.session_id) == chat_id)
            total = len(session.exec(count_statement).all())
            data = [expression_to_response(expr, session) for expr in expressions]

        return ReviewListResponse(
            success=True,
            total=total,
            page=page,
            page_size=page_size,
            data=data,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"获取审核列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取审核列表失败: {str(e)}") from e


class BatchReviewItem(BaseModel):
    """批量审核项"""

    id: int
    rejected: bool
    require_unchecked: bool = True  # 前端保留的来源标记，人工审核提交时不再阻断覆盖


class BatchReviewRequest(BaseModel):
    """批量审核请求"""

    items: List[BatchReviewItem]


class BatchReviewResultItem(BaseModel):
    """批量审核结果项"""

    id: int
    success: bool
    message: str


class BatchReviewResponse(BaseModel):
    """批量审核响应"""

    success: bool
    total: int
    succeeded: int
    failed: int
    results: List[BatchReviewResultItem]


@router.post("/review/batch", response_model=BatchReviewResponse)
async def batch_review_expressions(
    request: BatchReviewRequest,
) -> BatchReviewResponse:
    """批量审核表达方式。

    Args:
        request: 批量审核请求。

    Returns:
        BatchReviewResponse: 每条表达方式的审核结果。
    """
    try:
        if not request.items:
            raise HTTPException(status_code=400, detail="未提供要审核的表达方式")

        results = []
        succeeded = 0
        failed = 0

        for item in request.items:
            try:
                with get_db_session() as session:
                    expression = session.exec(select(Expression).where(col(Expression.id) == item.id).limit(1)).first()

                if not expression:
                    results.append(
                        BatchReviewResultItem(id=item.id, success=False, message=f"未找到 ID 为 {item.id} 的表达方式")
                    )
                    failed += 1
                    continue

                # 更新状态
                with get_db_session() as session:
                    db_expression = session.exec(
                        select(Expression).where(col(Expression.id) == item.id).limit(1)
                    ).first()
                    if not db_expression:
                        results.append(
                            BatchReviewResultItem(
                                id=item.id, success=False, message=f"未找到 ID 为 {item.id} 的表达方式"
                            )
                        )
                        failed += 1
                        continue
                    db_expression.checked = True
                    db_expression.rejected = item.rejected
                    db_expression.modified_by = ModifiedBy.USER
                    db_expression.last_active_time = datetime.now()
                    session.add(db_expression)

                results.append(
                    BatchReviewResultItem(id=item.id, success=True, message="拒绝" if item.rejected else "通过")
                )
                succeeded += 1

            except Exception as e:
                results.append(BatchReviewResultItem(id=item.id, success=False, message=str(e)))
                failed += 1

        logger.info(f"批量审核完成: 成功 {succeeded}, 失败 {failed}")

        return BatchReviewResponse(
            success=True, total=len(request.items), succeeded=succeeded, failed=failed, results=results
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"批量审核失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量审核失败: {str(e)}") from e
