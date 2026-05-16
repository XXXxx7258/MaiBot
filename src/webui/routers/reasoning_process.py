"""推理过程日志浏览接口。"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, col, select

from src.common.database.database import get_db_session
from src.common.database.database_model import ChatSession, Messages
from src.webui.dependencies import require_auth

router = APIRouter(prefix="/reasoning-process", tags=["reasoning-process"], dependencies=[Depends(require_auth)])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROMPT_LOG_ROOT = (PROJECT_ROOT / "logs" / "maisaka_prompt").resolve()
ALLOWED_SUFFIXES = {".txt", ".html"}
SESSION_CHAT_TYPES = ("group", "private")


class ReasoningPromptStageInfo(BaseModel):
    """推理过程类型概要。"""

    name: str
    session_count: int = 0
    latest_modified_at: float = 0


class ReasoningPromptSessionInfo(BaseModel):
    """推理过程日志目录对应的聊天流信息。"""

    name: str
    platform: str = ""
    chat_type: str = ""
    target_id: str = ""
    resolved_session_id: str | None = None
    display_name: str = ""
    account_id: str | None = None
    matched_current_account: bool = False


class ReasoningPromptFile(BaseModel):
    """推理过程日志条目。"""

    stage: str
    session_id: str
    resolved_session_id: str | None = None
    session_display_name: str | None = None
    platform: str | None = None
    chat_type: str | None = None
    target_id: str | None = None
    stem: str
    timestamp: int | None = None
    text_path: str | None = None
    html_path: str | None = None
    output_preview: str | None = None
    size: int = 0
    modified_at: float = 0


class ReasoningPromptListResponse(BaseModel):
    """推理过程日志列表响应。"""

    items: list[ReasoningPromptFile]
    total: int
    page: int
    page_size: int
    stages: list[str] = Field(default_factory=list)
    stage_infos: list[ReasoningPromptStageInfo] = Field(default_factory=list)
    sessions: list[str] = Field(default_factory=list)
    session_infos: list[ReasoningPromptSessionInfo] = Field(default_factory=list)
    selected_session: str = ""


class ReasoningPromptStagesResponse(BaseModel):
    """推理过程类型概览响应。"""

    stages: list[str] = Field(default_factory=list)
    stage_infos: list[ReasoningPromptStageInfo] = Field(default_factory=list)


class ReasoningPromptContentResponse(BaseModel):
    """推理过程文本内容响应。"""

    path: str
    content: str
    size: int
    modified_at: float


def _to_safe_relative_path(relative_path: str) -> Path:
    safe_path = Path(relative_path)
    if safe_path.is_absolute() or ".." in safe_path.parts:
        raise HTTPException(status_code=400, detail="路径不合法")
    return safe_path


def _resolve_prompt_log_path(relative_path: str, allowed_suffixes: set[str]) -> Path:
    safe_path = _to_safe_relative_path(relative_path)
    resolved_path = (PROMPT_LOG_ROOT / safe_path).resolve()

    try:
        resolved_path.relative_to(PROMPT_LOG_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="路径不合法") from exc

    if resolved_path.suffix.lower() not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    if not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    return resolved_path


def _relative_posix_path(path: Path) -> str:
    return path.relative_to(PROMPT_LOG_ROOT).as_posix()


def _is_safe_name(name: str) -> bool:
    path = Path(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and len(path.parts) == 1


def _list_stage_names() -> list[str]:
    if not PROMPT_LOG_ROOT.is_dir():
        return []

    return sorted(path.name for path in PROMPT_LOG_ROOT.iterdir() if path.is_dir() and _is_safe_name(path.name))


def _list_stage_infos() -> list[ReasoningPromptStageInfo]:
    if not PROMPT_LOG_ROOT.is_dir():
        return []

    stage_infos: list[ReasoningPromptStageInfo] = []
    for stage_dir in PROMPT_LOG_ROOT.iterdir():
        if not stage_dir.is_dir() or not _is_safe_name(stage_dir.name):
            continue

        session_dirs = [path for path in stage_dir.iterdir() if path.is_dir() and _is_safe_name(path.name)]
        latest_modified_at = 0.0
        for session_dir in session_dirs:
            try:
                latest_modified_at = max(latest_modified_at, session_dir.stat().st_mtime)
            except OSError:
                continue

        stage_infos.append(
            ReasoningPromptStageInfo(
                name=stage_dir.name,
                session_count=len(session_dirs),
                latest_modified_at=latest_modified_at,
            )
        )

    stage_infos.sort(key=lambda item: item.name)
    return stage_infos


def _resolve_stage_name(stage: str) -> str:
    normalized_stage = str(stage or "").strip()
    if not normalized_stage or normalized_stage == "all":
        return "planner"
    if not _is_safe_name(normalized_stage):
        raise HTTPException(status_code=400, detail="阶段名称不合法")
    return normalized_stage


def _list_session_names(stage: str) -> list[str]:
    stage_dir = PROMPT_LOG_ROOT / stage
    if not stage_dir.is_dir():
        return []

    session_dirs = [path for path in stage_dir.iterdir() if path.is_dir() and _is_safe_name(path.name)]
    session_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return [path.name for path in session_dirs]


def _resolve_session_name(session: str, sessions: list[str]) -> str:
    normalized_session = str(session or "").strip()
    if not normalized_session or normalized_session in {"all", "auto"}:
        return sessions[0] if sessions else ""
    if not _is_safe_name(normalized_session):
        raise HTTPException(status_code=400, detail="会话名称不合法")
    return normalized_session if normalized_session in sessions else ""


def _get_configured_platform_accounts() -> set[tuple[str, str]]:
    """读取当前配置中的平台账号对。"""

    from src.config.config import global_config

    pairs: set[tuple[str, str]] = set()
    base_platform = str(global_config.bot.platform or "").strip()
    base_account = str(global_config.bot.qq_account or "").strip()
    if base_platform and base_account:
        pairs.add((base_platform, base_account))

    for item in global_config.bot.platforms:
        platform, separator, account_id = str(item or "").partition(":")
        platform = platform.strip()
        account_id = account_id.strip()
        if separator and platform and account_id:
            pairs.add((platform, account_id))

    return pairs


def _parse_session_directory_name(name: str) -> tuple[str, str, str] | None:
    """解析 ``platform_type_id`` 形式的日志目录名。"""

    normalized_name = str(name or "").strip()
    for chat_type in SESSION_CHAT_TYPES:
        marker = f"_{chat_type}_"
        if marker not in normalized_name:
            continue

        platform, target_id = normalized_name.split(marker, 1)
        platform = platform.strip()
        target_id = target_id.strip()
        if platform and target_id:
            return platform, chat_type, target_id

    return None


def _get_chat_manager() -> Any:
    from src.chat.message_receive.chat_manager import chat_manager

    return chat_manager


def _session_sort_key(session: Any) -> float:
    timestamp = session.last_active_timestamp or session.created_timestamp
    return timestamp.timestamp() if timestamp else 0.0


def _select_current_account_session(
    sessions: list[Any],
    configured_accounts: set[tuple[str, str]],
) -> tuple[Any | None, bool]:
    configured_matches = [
        session
        for session in sessions
        if (
            str(session.platform or "").strip(),
            str(session.account_id or "").strip(),
        )
        in configured_accounts
    ]
    if configured_matches:
        return max(configured_matches, key=_session_sort_key), True

    legacy_sessions = [session for session in sessions if not str(session.account_id or "").strip()]
    if len(sessions) == 1:
        return sessions[0], False
    if len(legacy_sessions) == 1:
        return legacy_sessions[0], False
    return None, False


def _get_chat_name_from_latest_message(session_id: str, db_session: Session) -> str | None:
    statement = (
        select(Messages).where(col(Messages.session_id) == session_id).order_by(col(Messages.timestamp).desc()).limit(1)
    )
    message = db_session.exec(statement).first()
    if not message:
        return None
    if message.group_id:
        return message.group_name or f"群聊{message.group_id}"

    private_name = message.user_cardname or message.user_nickname or (f"用户{message.user_id}" if message.user_id else None)
    return f"{private_name}的私聊" if private_name else None


def _get_chat_name_from_session_record(chat_session: Any | ChatSession) -> str:
    if chat_session.group_id:
        return f"群聊{chat_session.group_id}"
    if chat_session.user_id:
        return f"用户{chat_session.user_id}的私聊"
    return chat_session.session_id


def _get_chat_display_name(chat_session: Any, db_session: Session) -> str:
    chat_manager = _get_chat_manager()
    if name := chat_manager.get_session_name(chat_session.session_id):
        return name
    if name := _get_chat_name_from_latest_message(chat_session.session_id, db_session):
        return name
    return _get_chat_name_from_session_record(chat_session)


def _fallback_session_display_name(name: str, parsed: tuple[str, str, str] | None) -> str:
    if parsed is None:
        return name

    platform, chat_type, target_id = parsed
    chat_type_label = "群聊" if chat_type == "group" else "私聊"
    return f"{platform} {chat_type_label} {target_id}"


def _extract_output_preview(file_path: Path, max_chars: int = 160) -> str | None:
    """从新版 prompt 预览 txt 中提取输出结果摘要。"""

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    marker = "[输出结果]"
    marker_index = content.find(marker)
    if marker_index < 0:
        return None

    output_text = content[marker_index + len(marker) :]
    separator_index = output_text.find("================================================================================")
    if separator_index >= 0:
        output_text = output_text[:separator_index]

    normalized_output = " ".join(line.strip() for line in output_text.splitlines() if line.strip())
    if not normalized_output:
        return None

    if len(normalized_output) <= max_chars:
        return normalized_output
    return f"{normalized_output[:max_chars].rstrip()}..."


def _resolve_reasoning_session_info(
    name: str,
    *,
    configured_accounts: set[tuple[str, str]],
    db_session: Session,
) -> ReasoningPromptSessionInfo:
    parsed = _parse_session_directory_name(name)
    if parsed is None:
        return ReasoningPromptSessionInfo(name=name, display_name=name)

    platform, chat_type, target_id = parsed
    chat_manager = _get_chat_manager()
    matched_sessions = chat_manager.resolve_sessions_by_target(
        platform=platform,
        target_id=target_id,
        chat_type=chat_type,
    )
    matched_session, matched_current_account = _select_current_account_session(matched_sessions, configured_accounts)

    if matched_session is None:
        return ReasoningPromptSessionInfo(
            name=name,
            platform=platform,
            chat_type=chat_type,
            target_id=target_id,
            display_name=_fallback_session_display_name(name, parsed),
        )

    return ReasoningPromptSessionInfo(
        name=name,
        platform=platform,
        chat_type=chat_type,
        target_id=target_id,
        resolved_session_id=matched_session.session_id,
        display_name=_get_chat_display_name(matched_session, db_session),
        account_id=matched_session.account_id,
        matched_current_account=matched_current_account,
    )


def _list_session_infos(stage: str, session_names: list[str] | None = None) -> list[ReasoningPromptSessionInfo]:
    if session_names is None:
        session_names = _list_session_names(stage)
    if not session_names:
        return []

    configured_accounts = _get_configured_platform_accounts()
    with get_db_session(auto_commit=False) as db_session:
        return [
            _resolve_reasoning_session_info(
                name,
                configured_accounts=configured_accounts,
                db_session=db_session,
            )
            for name in session_names
        ]


def _collect_prompt_files(
    stage: str,
    session: str,
    session_info_map: dict[str, ReasoningPromptSessionInfo],
) -> list[ReasoningPromptFile]:
    session_dir = PROMPT_LOG_ROOT / stage / session
    if not session or not session_dir.is_dir():
        return []

    records: dict[tuple[str, str, str], dict[str, object]] = {}

    for file_path in session_dir.iterdir():
        if not file_path.is_file() or file_path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue

        try:
            relative_path = file_path.relative_to(PROMPT_LOG_ROOT)
        except ValueError:
            continue

        parts = relative_path.parts
        if len(parts) < 3:
            continue

        stage_name, session_id = parts[0], parts[1]
        stem = file_path.stem
        key = (stage_name, session_id, stem)
        stat = file_path.stat()
        session_info = session_info_map.get(session_id)

        record = records.setdefault(
            key,
            {
                "stage": stage_name,
                "session_id": session_id,
                "resolved_session_id": session_info.resolved_session_id if session_info else None,
                "session_display_name": session_info.display_name if session_info else None,
                "platform": session_info.platform if session_info else None,
                "chat_type": session_info.chat_type if session_info else None,
                "target_id": session_info.target_id if session_info else None,
                "stem": stem,
                "timestamp": int(stem) if stem.isdigit() else None,
                "text_path": None,
                "html_path": None,
                "output_preview": None,
                "size": 0,
                "modified_at": 0.0,
            },
        )
        record["size"] = int(record["size"]) + stat.st_size
        record["modified_at"] = max(float(record["modified_at"]), stat.st_mtime)

        if file_path.suffix.lower() == ".txt":
            record["text_path"] = _relative_posix_path(file_path)
            if stage_name == "replyer":
                record["output_preview"] = _extract_output_preview(file_path)
        elif file_path.suffix.lower() == ".html":
            record["html_path"] = _relative_posix_path(file_path)

    items = [ReasoningPromptFile(**record) for record in records.values()]
    items.sort(key=lambda item: (item.modified_at, item.timestamp or 0), reverse=True)
    return items


@router.get("/stages", response_model=ReasoningPromptStagesResponse)
async def list_reasoning_prompt_stages():
    """只列出 logs/maisaka_prompt 下的推理过程类型概览。"""

    stage_infos = _list_stage_infos()
    return ReasoningPromptStagesResponse(
        stages=[item.name for item in stage_infos],
        stage_infos=stage_infos,
    )


@router.get("/files", response_model=ReasoningPromptListResponse)
async def list_reasoning_prompt_files(
    stage: str = Query("planner"),
    session: str = Query("auto"),
    search: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
):
    """列出 logs/maisaka_prompt 下的推理过程日志。"""

    stage_infos = _list_stage_infos()
    stages = [item.name for item in stage_infos]
    selected_stage = _resolve_stage_name(stage)
    sessions = _list_session_names(selected_stage)
    selected_session = _resolve_session_name(session, sessions)
    normalized_search = search.strip().lower()
    sessions_to_resolve = sessions if normalized_search else ([selected_session] if selected_session else [])
    session_infos = _list_session_infos(selected_stage, sessions_to_resolve)
    session_info_map = {item.name: item for item in session_infos}
    items = _collect_prompt_files(selected_stage, selected_session, session_info_map)

    if normalized_search:
        items = [
            item
            for item in items
            if normalized_search in item.stage.lower()
            or normalized_search in item.session_id.lower()
            or normalized_search in (item.session_display_name or "").lower()
            or normalized_search in (item.resolved_session_id or "").lower()
            or normalized_search in (item.output_preview or "").lower()
            or normalized_search in item.stem.lower()
        ]

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size

    return ReasoningPromptListResponse(
        items=items[start:end],
        total=total,
        page=page,
        page_size=page_size,
        stages=stages,
        stage_infos=stage_infos,
        sessions=sessions,
        session_infos=session_infos,
        selected_session=selected_session,
    )


@router.get("/file", response_model=ReasoningPromptContentResponse)
async def get_reasoning_prompt_file(path: str = Query(...)):
    """读取推理过程 txt 日志内容。"""

    file_path = _resolve_prompt_log_path(path, {".txt"})
    stat = file_path.stat()

    return ReasoningPromptContentResponse(
        path=_relative_posix_path(file_path),
        content=file_path.read_text(encoding="utf-8", errors="replace"),
        size=stat.st_size,
        modified_at=stat.st_mtime,
    )


@router.get("/html")
async def get_reasoning_prompt_html(path: str = Query(...)):
    """预览推理过程 html 日志内容。"""

    file_path = _resolve_prompt_log_path(path, {".html"})
    return FileResponse(
        file_path,
        media_type="text/html; charset=utf-8",
        headers={"X-Robots-Tag": "noindex, nofollow"},
    )
