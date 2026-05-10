"""黑话（俚语）管理路由"""

from typing import Annotated, Any, Dict, List, Optional, Set

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, col, delete, select

from src.chat.message_receive.chat_manager import chat_manager as _chat_manager
from src.common.database.database import get_db_session
from src.common.database.database_model import ChatSession, Jargon, Messages
from src.common.logger import get_logger
from src.webui.dependencies import require_auth

logger = get_logger("webui.jargon")

router = APIRouter(prefix="/jargon", tags=["Jargon"], dependencies=[Depends(require_auth)])


# ==================== 辅助函数 ====================


def parse_chat_id_to_stream_ids(chat_id_str: str) -> List[str]:
    """解析聊天 ID 字段并提取所有 stream_id。

    Args:
        chat_id_str: JSON 格式或纯字符串格式的聊天 ID。

    Returns:
        List[str]: 解析出的 stream_id 列表。
    """
    if not chat_id_str:
        return []

    try:
        # 尝试解析为 JSON
        parsed = json.loads(chat_id_str)
        if isinstance(parsed, list):
            # 格式: [["stream_id", user_id], ...]
            return [str(item[0]) for item in parsed if isinstance(item, list) and len(item) >= 1]

        # 其他格式，返回原始字符串
        return [chat_id_str]
    except (json.JSONDecodeError, TypeError):
        # 不是有效的 JSON，可能是直接的 stream_id
        return [chat_id_str]


def get_display_name_for_chat_id(chat_id_str: str, session: Session) -> str:
    """获取聊天 ID 的显示名称。

    Args:
        chat_id_str: JSON 格式或纯字符串格式的聊天 ID。
        session: 当前数据库会话。

    Returns:
        str: 聊天显示名称，无法查询时返回截断后的 stream_id。
    """
    stream_ids = parse_chat_id_to_stream_ids(chat_id_str)

    if not stream_ids:
        return chat_id_str[:20]

    stream_id = stream_ids[0]
    message = session.exec(
        select(Messages).where(col(Messages.session_id) == stream_id).order_by(col(Messages.timestamp).desc()).limit(1)
    ).first()
    if message:
        if message.group_id:
            return message.group_name or f"群聊{message.group_id}"
        private_name = message.user_cardname or message.user_nickname or (
            f"用户{message.user_id}" if message.user_id else None
        )
        if private_name:
            return f"{private_name}的私聊"

    if not (chat_session := session.exec(select(ChatSession).where(col(ChatSession.session_id) == stream_id)).first()):
        return stream_id[:20]

    if chat_session.group_id:
        return f"群聊{chat_session.group_id}"
    if chat_session.user_id:
        return f"用户{chat_session.user_id}的私聊"

    return chat_session.session_id[:20]


# ==================== 请求/响应模型 ====================


class JargonResponse(BaseModel):
    """黑话信息响应"""

    id: int
    content: str
    raw_content: Optional[str] = None
    meaning: Optional[str] = None
    chat_id: str
    stream_id: Optional[str] = None  # 解析后的 stream_id，用于前端编辑时匹配
    chat_name: Optional[str] = None  # 解析后的聊天名称，用于前端显示
    count: int = 0
    is_jargon: Optional[bool] = None
    is_complete: bool = False
    inference_with_context: Optional[str] = None
    inference_content_only: Optional[str] = None


class JargonListResponse(BaseModel):
    """黑话列表响应"""

    success: bool = True
    total: int
    page: int
    page_size: int
    data: List[Dict[str, Any]]


class JargonDetailResponse(BaseModel):
    """黑话详情响应"""

    success: bool = True
    data: JargonResponse


class JargonCreateRequest(BaseModel):
    """黑话创建请求"""

    content: str = Field(..., description="黑话内容")
    raw_content: Optional[str] = Field(None, description="原始内容")
    meaning: Optional[str] = Field(None, description="含义")
    chat_id: str = Field(..., description="聊天ID")


class JargonUpdateRequest(BaseModel):
    """黑话更新请求"""

    content: Optional[str] = None
    raw_content: Optional[str] = None
    meaning: Optional[str] = None
    chat_id: Optional[str] = None
    is_jargon: Optional[bool] = None


class JargonCreateResponse(BaseModel):
    """黑话创建响应"""

    success: bool = True
    message: str
    data: JargonResponse


class JargonUpdateResponse(BaseModel):
    """黑话更新响应"""

    success: bool = True
    message: str
    data: Optional[JargonResponse] = None


class JargonDeleteResponse(BaseModel):
    """黑话删除响应"""

    success: bool = True
    message: str
    deleted_count: int = 0


class BatchDeleteRequest(BaseModel):
    """批量删除请求"""

    ids: List[int] = Field(..., description="要删除的黑话ID列表")


class JargonStatsResponse(BaseModel):
    """黑话统计响应"""

    success: bool = True
    data: Dict[str, Any]


class ChatInfoResponse(BaseModel):
    """聊天信息响应"""

    chat_id: str
    chat_name: str
    platform: Optional[str] = None
    is_group: bool = False


class ChatListResponse(BaseModel):
    """聊天列表响应"""

    success: bool = True
    data: List[ChatInfoResponse]


# ==================== 工具函数 ====================


def parse_session_id_dict(session_id_dict_str: Optional[str]) -> Dict[str, int]:
    """解析会话计数字典。

    Args:
        session_id_dict_str: 数据库中保存的会话计数字典 JSON 字符串。

    Returns:
        Dict[str, int]: 解析后的会话计数字典。
    """
    if not session_id_dict_str:
        return {}

    try:
        parsed = json.loads(session_id_dict_str)
    except (json.JSONDecodeError, TypeError):
        return {}

    if not isinstance(parsed, dict):
        return {}

    session_counts: Dict[str, int] = {}
    for session_id, count in parsed.items():
        if not isinstance(session_id, str):
            continue
        if isinstance(count, int):
            session_counts[session_id] = count
        else:
            try:
                session_counts[session_id] = int(count)
            except (TypeError, ValueError):
                session_counts[session_id] = 0
    return session_counts


def dump_session_id_dict(session_counts: Dict[str, int]) -> str:
    """序列化会话计数字典。

    Args:
        session_counts: 会话 ID 与出现次数的映射。

    Returns:
        str: 可写入数据库的 JSON 字符串。
    """
    return json.dumps(session_counts, ensure_ascii=False)


def get_primary_chat_id(session_id_dict_str: Optional[str]) -> str:
    """从会话计数字典中选出主聊天 ID。

    Args:
        session_id_dict_str: 数据库中保存的会话计数字典 JSON 字符串。

    Returns:
        str: 出现次数最多的聊天 ID，没有记录时返回空字符串。
    """
    if not (session_counts := parse_session_id_dict(session_id_dict_str)):
        return ""

    return max(session_counts.items(), key=lambda item: item[1])[0]


def has_chat_id(session_id_dict_str: Optional[str], chat_id: str) -> bool:
    """判断记录是否包含指定聊天 ID。

    Args:
        session_id_dict_str: 数据库中保存的会话计数字典 JSON 字符串。
        chat_id: 需要检查的聊天 ID。

    Returns:
        bool: 记录包含该聊天 ID 时返回 True。
    """
    return chat_id in parse_session_id_dict(session_id_dict_str)


def build_session_id_dict_for_chat(chat_id: str, count: int = 1) -> str:
    """为单个聊天 ID 构建会话计数字典。

    Args:
        chat_id: 聊天 ID。
        count: 该聊天 ID 的出现次数。

    Returns:
        str: 可写入数据库的会话计数字典 JSON 字符串。
    """
    return dump_session_id_dict({chat_id: count})


def require_existing_chat_id(chat_id: Optional[str]) -> str:
    """校验资源归属的聊天流 ID 必须是真实存在的会话。"""

    normalized_chat_id = str(chat_id or "").strip()
    if not normalized_chat_id:
        raise HTTPException(status_code=400, detail="缺少聊天流 ID")
    if _chat_manager.get_existing_session_by_session_id(normalized_chat_id) is None:
        raise HTTPException(status_code=400, detail=f"聊天流不存在: {normalized_chat_id}")
    return normalized_chat_id


def jargon_to_dict(jargon: Jargon, session: Session) -> Dict[str, Any]:
    """将黑话模型转换为字典。

    Args:
        jargon: 数据库中的黑话记录。
        session: 当前数据库会话，用于查询聊天显示名称。

    Returns:
        Dict[str, Any]: WebUI 可直接序列化的黑话数据。
    """
    chat_id = get_primary_chat_id(jargon.session_id_dict)
    chat_name = get_display_name_for_chat_id(chat_id, session) if chat_id else None

    return {
        "id": jargon.id,
        "content": jargon.content,
        "raw_content": jargon.raw_content,
        "meaning": jargon.meaning,
        "chat_id": chat_id,
        "stream_id": chat_id or None,
        "chat_name": chat_name,
        "count": jargon.count,
        "is_jargon": jargon.is_jargon,
        "is_complete": jargon.is_complete,
        "inference_with_context": jargon.inference_with_context,
        "inference_content_only": jargon.inference_with_content_only,
    }


# ==================== API 端点 ====================


@router.get("/list", response_model=JargonListResponse)
async def get_jargon_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    search: Optional[str] = Query(None, description="搜索关键词"),
    chat_id: Optional[str] = Query(None, description="按聊天ID筛选"),
    is_jargon: Optional[bool] = Query(None, description="按是否是黑话筛选"),
    is_global: Optional[bool] = Query(None, description="按是否全局筛选"),
) -> JargonListResponse:
    """获取黑话列表。

    Args:
        page: 页码，从 1 开始。
        page_size: 每页数量，范围为 1-100。
        search: 搜索关键词。
        chat_id: 聊天 ID 筛选条件。
        is_jargon: 是否为黑话的筛选条件。
        is_global: 是否为全局黑话的筛选条件。

    Returns:
        JargonListResponse: 分页后的黑话列表。
    """
    try:
        statement = select(Jargon)

        if search:
            search_filter = (
                (col(Jargon.content).contains(search))
                | (col(Jargon.meaning).contains(search))
                | (col(Jargon.raw_content).contains(search))
            )
            statement = statement.where(search_filter)

        if is_jargon is not None:
            statement = statement.where(col(Jargon.is_jargon) == is_jargon)

        if is_global is not None:
            statement = statement.where(col(Jargon.is_global) == is_global)

        statement = statement.order_by(col(Jargon.count).desc(), col(Jargon.id).desc())

        with get_db_session() as session:
            jargons = session.exec(statement).all()

            if chat_id:
                stream_ids = parse_chat_id_to_stream_ids(chat_id)
                chat_ids = stream_ids or [chat_id]
                jargons = [
                    jargon
                    for jargon in jargons
                    if any(has_chat_id(jargon.session_id_dict, current_chat_id) for current_chat_id in chat_ids)
                ]

            total = len(jargons)
            offset = (page - 1) * page_size
            page_jargons = jargons[offset : offset + page_size]
            data = [jargon_to_dict(jargon, session) for jargon in page_jargons]

        return JargonListResponse(
            success=True,
            total=total,
            page=page,
            page_size=page_size,
            data=data,
        )

    except Exception as e:
        logger.error(f"获取黑话列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取黑话列表失败: {str(e)}") from e


@router.get("/chats", response_model=ChatListResponse)
async def get_chat_list() -> ChatListResponse:
    """获取所有有黑话记录的聊天列表。

    Returns:
        ChatListResponse: 包含黑话记录的聊天列表。
    """
    try:
        with get_db_session() as session:
            jargons = session.exec(select(Jargon)).all()

            seen_stream_ids: Set[str] = set()
            for jargon in jargons:
                seen_stream_ids.update(parse_session_id_dict(jargon.session_id_dict).keys())

            result: List[ChatInfoResponse] = []
            for stream_id in seen_stream_ids:
                if chat_session := session.exec(
                    select(ChatSession).where(col(ChatSession.session_id) == stream_id)
                ).first():
                    chat_name = get_display_name_for_chat_id(stream_id, session)
                    result.append(
                        ChatInfoResponse(
                            chat_id=stream_id,
                            chat_name=chat_name,
                            platform=chat_session.platform,
                            is_group=bool(chat_session.group_id),
                        )
                    )
                else:
                    result.append(
                        ChatInfoResponse(
                            chat_id=stream_id,
                            chat_name=get_display_name_for_chat_id(stream_id, session),
                            platform=None,
                            is_group=False,
                        )
                    )

        return ChatListResponse(success=True, data=result)

    except Exception as e:
        logger.error(f"获取聊天列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取聊天列表失败: {str(e)}") from e


@router.get("/stats/summary", response_model=JargonStatsResponse)
async def get_jargon_stats() -> JargonStatsResponse:
    """获取黑话统计数据。

    Returns:
        JargonStatsResponse: 黑话总数、确认状态和聊天分布统计。
    """
    try:
        with get_db_session() as session:
            jargons = session.exec(select(Jargon)).all()

            total = len(jargons)
            confirmed_jargon = sum(jargon.is_jargon is True for jargon in jargons)
            confirmed_not_jargon = sum(jargon.is_jargon is False for jargon in jargons)
            pending = sum(jargon.is_jargon is None for jargon in jargons)
            global_count = sum(jargon.is_global for jargon in jargons)
            complete_count = sum(jargon.is_complete for jargon in jargons)

            top_chats_counter: Dict[str, int] = {}
            for jargon in jargons:
                for session_id in parse_session_id_dict(jargon.session_id_dict):
                    top_chats_counter[session_id] = top_chats_counter.get(session_id, 0) + 1

            top_chats_dict = dict(sorted(top_chats_counter.items(), key=lambda item: item[1], reverse=True)[:5])
            chat_count = len(top_chats_counter)

        return JargonStatsResponse(
            success=True,
            data={
                "total": total,
                "confirmed_jargon": confirmed_jargon,
                "confirmed_not_jargon": confirmed_not_jargon,
                "pending": pending,
                "global_count": global_count,
                "complete_count": complete_count,
                "chat_count": chat_count,
                "top_chats": top_chats_dict,
            },
        )

    except Exception as e:
        logger.error(f"获取黑话统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取黑话统计失败: {str(e)}") from e


@router.get("/{jargon_id}", response_model=JargonDetailResponse)
async def get_jargon_detail(jargon_id: int) -> JargonDetailResponse:
    """获取黑话详情。

    Args:
        jargon_id: 黑话记录 ID。

    Returns:
        JargonDetailResponse: 指定黑话记录的详细信息。
    """
    try:
        with get_db_session() as session:
            if not (jargon := session.exec(select(Jargon).where(col(Jargon.id) == jargon_id)).first()):
                raise HTTPException(status_code=404, detail="黑话不存在")
            data = JargonResponse(**jargon_to_dict(jargon, session))

        return JargonDetailResponse(success=True, data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取黑话详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取黑话详情失败: {str(e)}") from e


@router.post("/", response_model=JargonCreateResponse)
async def create_jargon(request: JargonCreateRequest) -> JargonCreateResponse:
    """创建黑话。

    Args:
        request: 创建黑话所需的请求数据。

    Returns:
        JargonCreateResponse: 创建结果和新黑话数据。
    """
    try:
        chat_id = require_existing_chat_id(request.chat_id)
        with get_db_session() as session:
            same_content_jargons = session.exec(select(Jargon).where(col(Jargon.content) == request.content)).all()
            existing = next(
                (jargon for jargon in same_content_jargons if has_chat_id(jargon.session_id_dict, chat_id)),
                None,
            )
            if existing is not None:
                raise HTTPException(status_code=400, detail="该聊天中已存在相同内容的黑话")

            jargon = Jargon(
                content=request.content,
                raw_content=request.raw_content,
                meaning=request.meaning or "",
                session_id_dict=build_session_id_dict_for_chat(chat_id),
                count=0,
                is_jargon=None,
                is_complete=False,
            )
            session.add(jargon)
            session.flush()

            logger.info(f"创建黑话成功: id={jargon.id}, content={request.content}")
            data = JargonResponse(**jargon_to_dict(jargon, session))

        return JargonCreateResponse(success=True, message="创建成功", data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建黑话失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建黑话失败: {str(e)}") from e


@router.patch("/{jargon_id}", response_model=JargonUpdateResponse)
async def update_jargon(jargon_id: int, request: JargonUpdateRequest) -> JargonUpdateResponse:
    """增量更新黑话。

    Args:
        jargon_id: 黑话记录 ID。
        request: 只包含需要更新字段的请求数据。

    Returns:
        JargonUpdateResponse: 更新结果和更新后的黑话数据。
    """
    try:
        with get_db_session() as session:
            jargon = session.exec(select(Jargon).where(col(Jargon.id) == jargon_id)).first()
            if not jargon:
                raise HTTPException(status_code=404, detail="黑话不存在")

            if update_data := request.model_dump(exclude_unset=True):
                if "chat_id" in update_data and update_data["chat_id"] is not None:
                    chat_id = require_existing_chat_id(update_data["chat_id"])
                    jargon.session_id_dict = build_session_id_dict_for_chat(chat_id, max(jargon.count, 1))
                if "content" in update_data and update_data["content"] is not None:
                    jargon.content = update_data["content"]
                if "raw_content" in update_data:
                    jargon.raw_content = update_data["raw_content"]
                if "meaning" in update_data:
                    jargon.meaning = update_data["meaning"] or ""
                if "is_jargon" in update_data:
                    jargon.is_jargon = update_data["is_jargon"]
                session.add(jargon)

            logger.info(f"更新黑话成功: id={jargon_id}")
            data = JargonResponse(**jargon_to_dict(jargon, session))

        return JargonUpdateResponse(success=True, message="更新成功", data=data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新黑话失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新黑话失败: {str(e)}") from e


@router.delete("/{jargon_id}", response_model=JargonDeleteResponse)
async def delete_jargon(jargon_id: int) -> JargonDeleteResponse:
    """删除黑话。

    Args:
        jargon_id: 黑话记录 ID。

    Returns:
        JargonDeleteResponse: 删除结果。
    """
    try:
        with get_db_session() as session:
            jargon = session.exec(select(Jargon).where(col(Jargon.id) == jargon_id)).first()
            if not jargon:
                raise HTTPException(status_code=404, detail="黑话不存在")

            content = jargon.content
            session.delete(jargon)

            logger.info(f"删除黑话成功: id={jargon_id}, content={content}")

        return JargonDeleteResponse(success=True, message="删除成功", deleted_count=1)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除黑话失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除黑话失败: {str(e)}") from e


@router.post("/batch/delete", response_model=JargonDeleteResponse)
async def batch_delete_jargons(request: BatchDeleteRequest) -> JargonDeleteResponse:
    """批量删除黑话。

    Args:
        request: 包含要删除黑话 ID 列表的请求。

    Returns:
        JargonDeleteResponse: 批量删除结果。
    """
    try:
        if not request.ids:
            raise HTTPException(status_code=400, detail="ID列表不能为空")

        with get_db_session() as session:
            result = session.exec(delete(Jargon).where(col(Jargon.id).in_(request.ids)))
            deleted_count = result.rowcount or 0

            logger.info(f"批量删除黑话成功: 删除了 {deleted_count} 条记录")

        return JargonDeleteResponse(
            success=True,
            message=f"成功删除 {deleted_count} 条黑话",
            deleted_count=deleted_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除黑话失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量删除黑话失败: {str(e)}") from e


@router.post("/batch/set-jargon", response_model=JargonUpdateResponse)
async def batch_set_jargon_status(
    ids: Annotated[List[int], Query(description="黑话ID列表")],
    is_jargon: Annotated[bool, Query(description="是否是黑话")],
) -> JargonUpdateResponse:
    """批量设置黑话状态。

    Args:
        ids: 需要更新状态的黑话 ID 列表。
        is_jargon: 目标黑话状态。

    Returns:
        JargonUpdateResponse: 批量更新结果。
    """
    try:
        if not ids:
            raise HTTPException(status_code=400, detail="ID列表不能为空")

        with get_db_session() as session:
            jargons = session.exec(select(Jargon).where(col(Jargon.id).in_(ids))).all()
            for jargon in jargons:
                jargon.is_jargon = is_jargon
                session.add(jargon)
            updated_count = len(jargons)

            logger.info(f"批量更新黑话状态成功: 更新了 {updated_count} 条记录，is_jargon={is_jargon}")

        return JargonUpdateResponse(success=True, message=f"成功更新 {updated_count} 条黑话状态")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量更新黑话状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"批量更新黑话状态失败: {str(e)}") from e
