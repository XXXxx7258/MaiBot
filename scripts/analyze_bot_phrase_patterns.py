from __future__ import annotations

from argparse import ArgumentParser, Namespace
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import asyncio
import json
import re
import sqlite3
import sys
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "MaiBot.db"
DEFAULT_BOT_CONFIG_PATH = PROJECT_ROOT / "config" / "bot_config.toml"
DEFAULT_MODEL_CONFIG_PATH = PROJECT_ROOT / "config" / "model_config.toml"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "analysis"
REQUEST_TYPE = "bot_phrase_pattern_analysis"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass


@dataclass(frozen=True)
class BotAccount:
    platform: Optional[str]
    user_id: str
    source: str

    def display(self) -> str:
        platform = self.platform if self.platform else "*"
        return f"{platform}:{self.user_id}"


@dataclass(frozen=True)
class BotMessage:
    index: int
    message_id: str
    timestamp: str
    platform: str
    user_id: str
    user_nickname: str
    user_cardname: str
    group_id: str
    group_name: str
    session_id: str
    chat_user_id: str
    text: str

    @property
    def chat_label(self) -> str:
        if self.group_name:
            return self.group_name
        if self.group_id:
            return f"{self.group_id}群聊"
        if self.chat_user_id:
            return f"{self.chat_user_id}的私聊"
        return self.session_id

    def to_prompt_dict(self, max_text_chars: int) -> Dict[str, Any]:
        return {
            "idx": self.index,
            "time": self.timestamp,
            "chat": self.chat_label,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "text": truncate_text(self.text, max_text_chars),
        }

    def to_example_dict(self) -> Dict[str, str]:
        return {
            "index": str(self.index),
            "time": self.timestamp,
            "chat": self.chat_label,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "text": self.text,
        }


@dataclass(frozen=True)
class MessageChunk:
    chunk_id: int
    messages: List[BotMessage]


@dataclass(frozen=True)
class LLMJsonResult:
    payload: Dict[str, Any]
    raw_response: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def parse_datetime_filter(value: Optional[str]) -> Optional[datetime]:
    if value is None:
        return None

    normalized_value = value.strip()
    if not normalized_value:
        return None

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized_value, fmt)
        except ValueError:
            continue

    raise ValueError(f"无法解析时间: {value!r}，请使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")


def parse_recent_filter(value: Optional[str], now: datetime) -> Optional[datetime]:
    if value is None:
        return None

    normalized_value = value.strip().lower()
    if not normalized_value:
        return None

    match = re.fullmatch(r"(\d+(?:\.\d+)?)([mhdw])", normalized_value)
    if match is None:
        raise ValueError(f"无法解析最近时间: {value!r}，请使用 30m、24h、7d 或 2w")

    amount = float(match.group(1))
    if amount <= 0:
        raise ValueError(f"最近时间必须大于 0: {value!r}")

    unit = match.group(2)
    if unit == "m":
        delta = timedelta(minutes=amount)
    elif unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "d":
        delta = timedelta(days=amount)
    else:
        delta = timedelta(weeks=amount)
    return now - delta


def format_datetime_for_sql(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def parse_platform_account(value: str, source: str) -> Optional[BotAccount]:
    normalized_value = str(value or "").strip()
    if not normalized_value:
        return None

    if ":" in normalized_value:
        platform, user_id = normalized_value.split(":", 1)
        normalized_platform = platform.strip().lower()
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None
        return BotAccount(
            platform=None if normalized_platform in {"", "*"} else normalized_platform,
            user_id=normalized_user_id,
            source=source,
        )

    return BotAccount(platform=None, user_id=normalized_value, source=source)


def deduplicate_accounts(accounts: Iterable[BotAccount]) -> List[BotAccount]:
    seen: Set[Tuple[Optional[str], str]] = set()
    deduplicated: List[BotAccount] = []
    for account in accounts:
        key = (account.platform, account.user_id)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(account)
    return deduplicated


def load_bot_accounts_from_config(config_path: Path) -> Tuple[List[BotAccount], str]:
    if not config_path.exists():
        return [], ""

    with config_path.open("rb") as handle:
        config_data = tomllib.load(handle)

    bot_config = config_data.get("bot")
    if not isinstance(bot_config, dict):
        return [], ""

    accounts: List[BotAccount] = []
    qq_account = str(bot_config.get("qq_account") or "").strip()
    if qq_account and qq_account != "0":
        accounts.append(BotAccount(platform="qq", user_id=qq_account, source="bot_config.qq_account"))
        accounts.append(BotAccount(platform="webui", user_id=qq_account, source="bot_config.qq_account"))

    platforms = bot_config.get("platforms") or []
    if isinstance(platforms, list):
        for platform_entry in platforms:
            parsed_account = parse_platform_account(str(platform_entry), source="bot_config.platforms")
            if parsed_account is None or parsed_account.platform is None:
                continue
            accounts.append(parsed_account)
            if parsed_account.platform in {"tg", "telegram"}:
                accounts.append(
                    BotAccount(
                        platform="telegram" if parsed_account.platform == "tg" else "tg",
                        user_id=parsed_account.user_id,
                        source="bot_config.platforms",
                    )
                )

    return deduplicate_accounts(accounts), qq_account


def _normalize_flag_value(value: Any) -> str:
    return str(value).strip().lower()


def resolve_thinking_state(extra_params: Any) -> str:
    """根据模型额外参数判断是否显式启用 thinking。"""
    if not isinstance(extra_params, dict):
        return "unknown"

    thinking_value = extra_params.get("thinking")
    if isinstance(thinking_value, dict):
        thinking_type = _normalize_flag_value(thinking_value.get("type"))
        if thinking_type in {"enabled", "enable", "true", "on", "yes"}:
            return "enabled"
        if thinking_type in {"disabled", "disable", "false", "off", "no", "none"}:
            return "disabled"
    elif thinking_value is not None:
        normalized_thinking = _normalize_flag_value(thinking_value)
        if normalized_thinking in {"enabled", "enable", "true", "on", "yes"}:
            return "enabled"
        if normalized_thinking in {"disabled", "disable", "false", "off", "no", "none"}:
            return "disabled"

    if "enable_thinking" in extra_params:
        enable_thinking = _normalize_flag_value(extra_params.get("enable_thinking"))
        if enable_thinking in {"true", "1", "yes", "on", "enabled"}:
            return "enabled"
        if enable_thinking in {"false", "0", "no", "off", "disabled"}:
            return "disabled"

    if "thinking_budget" in extra_params:
        try:
            if int(extra_params["thinking_budget"]) == 0:
                return "disabled"
        except (TypeError, ValueError):
            return "unknown"

    return "unknown"


def validate_task_uses_non_thinking_models(model_config_path: Path, task_name: str, allow_thinking: bool) -> List[str]:
    if allow_thinking:
        return []
    if not model_config_path.exists():
        raise FileNotFoundError(f"模型配置文件不存在: {model_config_path}")

    with model_config_path.open("rb") as handle:
        config_data = tomllib.load(handle)

    model_task_config = config_data.get("model_task_config")
    if not isinstance(model_task_config, dict):
        raise ValueError(f"模型配置文件缺少 [model_task_config]: {model_config_path}")

    task_config = model_task_config.get(task_name)
    if not isinstance(task_config, dict):
        raise ValueError(f"模型配置文件中找不到任务配置: model_task_config.{task_name}")

    model_names = [str(name).strip() for name in task_config.get("model_list", []) if str(name).strip()]
    if task_name == "learner" and not model_names:
        fallback_task_config = model_task_config.get("utils")
        if isinstance(fallback_task_config, dict):
            model_names = [
                str(name).strip() for name in fallback_task_config.get("model_list", []) if str(name).strip()
            ]

    if not model_names:
        raise ValueError(f"任务配置 model_task_config.{task_name} 没有可用模型")

    models_by_name = {
        str(model.get("name") or "").strip(): model
        for model in config_data.get("models", [])
        if isinstance(model, dict) and str(model.get("name") or "").strip()
    }
    enabled_model_names: List[str] = []
    model_state_descriptions: List[str] = []
    for model_name in model_names:
        model_config = models_by_name.get(model_name)
        if model_config is None:
            model_state_descriptions.append(f"{model_name}: unknown")
            continue
        state = resolve_thinking_state(model_config.get("extra_params"))
        model_state_descriptions.append(f"{model_name}: {state}")
        if state == "enabled":
            enabled_model_names.append(model_name)

    if enabled_model_names:
        joined_enabled_names = ", ".join(enabled_model_names)
        joined_states = "; ".join(model_state_descriptions)
        raise ValueError(
            f"当前任务 model_task_config.{task_name} 包含 thinking 启用模型: {joined_enabled_names}。"
            f" 状态: {joined_states}。如确实要允许，请加 --allow-thinking。"
        )

    return model_state_descriptions


def build_account_conditions(
    accounts: Sequence[BotAccount],
    qq_fallback_account: str,
    legacy_qq_fallback: bool,
) -> Tuple[str, List[str]]:
    clauses: List[str] = []
    params: List[str] = []

    for account in accounts:
        if account.platform:
            clauses.append("(mai_messages.platform = ? AND mai_messages.user_id = ?)")
            params.extend([account.platform, account.user_id])
        else:
            clauses.append("mai_messages.user_id = ?")
            params.append(account.user_id)

    if legacy_qq_fallback and qq_fallback_account:
        clauses.append("mai_messages.user_id = ?")
        params.append(qq_fallback_account)

    if not clauses:
        return "", []
    return f"({' OR '.join(clauses)})", params


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"数据库文件不存在: {db_path}")

    database_uri = f"file:{db_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def normalize_message_text(text: str, keep_media_placeholders: bool) -> str:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return ""

    if not keep_media_placeholders:
        # 去掉消息扁平化时生成的媒体和引用说明，避免把元信息误判成固定句式。
        normalized_text = re.sub(r"\[回复[^\]]*\]", " ", normalized_text)
        normalized_text = re.sub(r"\[(?:图片|图像|表情包|表情|语音|文件)[^\]]*\]", " ", normalized_text)

    normalized_text = re.sub(r"\s+", " ", normalized_text)
    return normalized_text.strip()


def fetch_bot_messages(
    db_path: Path,
    since: datetime,
    until: datetime,
    accounts: Sequence[BotAccount],
    qq_fallback_account: str,
    legacy_qq_fallback: bool,
    session_id: Optional[str],
    platform: Optional[str],
    group_id: Optional[str],
    keep_media_placeholders: bool,
    min_text_length: int,
    limit: int,
) -> List[BotMessage]:
    where_clauses: List[str] = [
        "mai_messages.message_id != 'notice'",
        "mai_messages.timestamp >= ?",
        "mai_messages.timestamp < ?",
        "mai_messages.processed_plain_text IS NOT NULL",
        "TRIM(mai_messages.processed_plain_text) != ''",
    ]
    params: List[Any] = [format_datetime_for_sql(since), format_datetime_for_sql(until)]

    account_condition, account_params = build_account_conditions(
        accounts=accounts,
        qq_fallback_account=qq_fallback_account,
        legacy_qq_fallback=legacy_qq_fallback,
    )
    if account_condition:
        where_clauses.append(account_condition)
        params.extend(account_params)

    if session_id:
        where_clauses.append("mai_messages.session_id = ?")
        params.append(session_id)
    if platform:
        where_clauses.append("mai_messages.platform = ?")
        params.append(platform)
    if group_id:
        where_clauses.append("mai_messages.group_id = ?")
        params.append(group_id)

    limit_clause = "LIMIT ?" if limit > 0 else ""
    if limit > 0:
        params.append(limit)

    query = f"""
        SELECT
            mai_messages.message_id AS message_id,
            mai_messages.timestamp AS timestamp,
            mai_messages.platform AS platform,
            mai_messages.user_id AS user_id,
            COALESCE(mai_messages.user_nickname, '') AS user_nickname,
            COALESCE(mai_messages.user_cardname, '') AS user_cardname,
            COALESCE(mai_messages.group_id, '') AS group_id,
            COALESCE(mai_messages.group_name, '') AS group_name,
            COALESCE(mai_messages.session_id, '') AS session_id,
            COALESCE(chat_sessions.user_id, '') AS chat_user_id,
            mai_messages.processed_plain_text AS processed_plain_text
        FROM mai_messages
        LEFT JOIN chat_sessions ON chat_sessions.session_id = mai_messages.session_id
        WHERE {" AND ".join(where_clauses)}
        ORDER BY mai_messages.timestamp ASC
        {limit_clause}
    """

    messages: List[BotMessage] = []
    with connect_readonly(db_path) as connection:
        rows = connection.execute(query, params).fetchall()

    for row in rows:
        text = normalize_message_text(str(row["processed_plain_text"] or ""), keep_media_placeholders)
        if len(text) < min_text_length:
            continue
        messages.append(
            BotMessage(
                index=len(messages) + 1,
                message_id=str(row["message_id"] or ""),
                timestamp=str(row["timestamp"] or ""),
                platform=str(row["platform"] or ""),
                user_id=str(row["user_id"] or ""),
                user_nickname=str(row["user_nickname"] or ""),
                user_cardname=str(row["user_cardname"] or ""),
                group_id=str(row["group_id"] or ""),
                group_name=str(row["group_name"] or ""),
                session_id=str(row["session_id"] or ""),
                chat_user_id=str(row["chat_user_id"] or ""),
                text=text,
            )
        )

    return messages


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def split_chunks(messages: Sequence[BotMessage], chunk_char_limit: int, max_text_chars: int) -> List[MessageChunk]:
    chunks: List[MessageChunk] = []
    current_messages: List[BotMessage] = []
    current_size = 0

    for message in messages:
        prompt_line = json.dumps(message.to_prompt_dict(max_text_chars=max_text_chars), ensure_ascii=False)
        line_size = len(prompt_line) + 1
        if current_messages and current_size + line_size > chunk_char_limit:
            chunks.append(MessageChunk(chunk_id=len(chunks) + 1, messages=current_messages))
            current_messages = []
            current_size = 0

        current_messages.append(message)
        current_size += line_size

    if current_messages:
        chunks.append(MessageChunk(chunk_id=len(chunks) + 1, messages=current_messages))

    return chunks


def _top_counter_items(counter: Counter[str], limit: int, min_support: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for text, count in counter.most_common():
        if count < min_support:
            continue
        rows.append({"text": text, "count": count})
        if len(rows) >= limit:
            break
    return rows


def build_statistical_candidates(messages: Sequence[BotMessage], min_support: int, limit: int) -> Dict[str, Any]:
    exact_counter: Counter[str] = Counter()
    prefix_counter: Counter[str] = Counter()
    suffix_counter: Counter[str] = Counter()
    example_indexes: DefaultDict[str, List[int]] = defaultdict(list)

    for message in messages:
        text = message.text.strip()
        if not text:
            continue
        exact_counter[text] += 1
        if len(example_indexes[text]) < 5:
            example_indexes[text].append(message.index)

        compact_text = re.sub(r"\s+", "", text)
        for length in (3, 4, 5, 6, 8, 10, 12):
            if len(compact_text) < length:
                continue
            prefix_counter[compact_text[:length]] += 1
            suffix_counter[compact_text[-length:]] += 1

    exact_repeats = _top_counter_items(exact_counter, limit=limit, min_support=min_support)
    for item in exact_repeats:
        item["example_indexes"] = example_indexes.get(str(item["text"]), [])

    return {
        "exact_repeats": exact_repeats,
        "frequent_prefixes": _top_counter_items(prefix_counter, limit=limit, min_support=min_support),
        "frequent_suffixes": _top_counter_items(suffix_counter, limit=limit, min_support=min_support),
    }


def build_session_stats(messages: Sequence[BotMessage], limit: int = 0) -> List[Dict[str, Any]]:
    session_rows: Dict[str, Dict[str, Any]] = {}
    chat_counters: DefaultDict[str, Counter[str]] = defaultdict(Counter)
    platform_counters: DefaultDict[str, Counter[str]] = defaultdict(Counter)
    group_id_counters: DefaultDict[str, Counter[str]] = defaultdict(Counter)

    for message in messages:
        session_id = message.session_id
        row = session_rows.setdefault(
            session_id,
            {
                "session_id": session_id,
                "message_count": 0,
                "char_count": 0,
                "first_message_time": message.timestamp,
                "last_message_time": message.timestamp,
            },
        )
        row["message_count"] += 1
        row["char_count"] += len(message.text)
        if message.timestamp < row["first_message_time"]:
            row["first_message_time"] = message.timestamp
        if message.timestamp > row["last_message_time"]:
            row["last_message_time"] = message.timestamp

        chat_counters[session_id][message.chat_label] += 1
        platform_counters[session_id][message.platform] += 1
        if message.group_id:
            group_id_counters[session_id][message.group_id] += 1

    rows: List[Dict[str, Any]] = []
    for session_id, row in session_rows.items():
        normalized_row = dict(row)
        normalized_row["chat"] = chat_counters[session_id].most_common(1)[0][0] if chat_counters[session_id] else ""
        normalized_row["platform"] = (
            platform_counters[session_id].most_common(1)[0][0] if platform_counters[session_id] else ""
        )
        normalized_row["group_id"] = (
            group_id_counters[session_id].most_common(1)[0][0] if group_id_counters[session_id] else ""
        )
        normalized_row["chat_type"] = "group" if normalized_row["group_id"] else "private"
        rows.append(normalized_row)

    rows.sort(key=lambda item: (-int(item["message_count"]), str(item["session_id"])))
    if limit > 0:
        return rows[:limit]
    return rows


def build_corpus_stats(messages: Sequence[BotMessage]) -> Dict[str, Any]:
    platform_counter = Counter(message.platform for message in messages)
    session_counter = Counter(message.session_id for message in messages)
    chat_counter = Counter(message.chat_label for message in messages)
    char_count = sum(len(message.text) for message in messages)

    return {
        "message_count": len(messages),
        "char_count": char_count,
        "unique_session_count": len(session_counter),
        "platforms": dict(sorted(platform_counter.items())),
        "top_chats": [{"chat": chat, "count": count} for chat, count in chat_counter.most_common(20)],
        "top_sessions": build_session_stats(messages, limit=20),
    }


def build_chunk_prompt(chunk: MessageChunk, min_support: int, max_text_chars: int) -> str:
    message_lines = "\n".join(
        json.dumps(message.to_prompt_dict(max_text_chars=max_text_chars), ensure_ascii=False)
        for message in chunk.messages
    )
    return f"""你是聊天语料里的固定句式分析器。下面是同一个 bot 在一段时间内的部分发言，每行都是一条 JSON 消息。

任务：
1. 找出这个分块中是否存在固定句式、固定开头/结尾、固定反问模板、固定语气模板或高频口头禅。
2. 只提取至少出现在 {min_support} 条不同消息中的模式；如果只是同一话题或同一实体重复，不要算作固定句式。
3. 模板中请用 {{变量名}} 表示可替换部分，例如“{{对象}}不如先{{动作}}”。
4. supporting_message_indexes 必须只填写下面消息里的 idx 数字。
5. 只输出 JSON 对象，不要输出 Markdown 或额外解释。

输出 JSON 结构：
{{
  "chunk_id": {chunk.chunk_id},
  "message_count": {len(chunk.messages)},
  "has_fixed_patterns": true,
  "patterns": [
    {{
      "pattern_name": "简短名称",
      "template": "固定句式模板",
      "fixed_parts": ["固定片段"],
      "variable_slots": [
        {{"name": "变量名", "description": "变量含义", "examples": ["样例"]}}
      ],
      "function": "这个句式通常用于什么语用功能",
      "tone": "语气/风格",
      "trigger_contexts": ["可能触发场景"],
      "estimated_count": 3,
      "supporting_message_indexes": [1, 2, 3],
      "examples": ["原文样例"],
      "confidence": 0.0
    }}
  ],
  "non_patterns_note": "如果没有明显模式，说明原因"
}}

消息：
{message_lines}
"""


def build_final_prompt(
    chunk_payloads: Sequence[Dict[str, Any]],
    candidates: Dict[str, Any],
    stats: Dict[str, Any],
    min_support: int,
) -> str:
    chunk_json = json.dumps(chunk_payloads, ensure_ascii=False, indent=2)
    candidates_json = json.dumps(candidates, ensure_ascii=False, indent=2)
    stats_json = json.dumps(stats, ensure_ascii=False, indent=2)
    return f"""你是 bot 语言习惯审计器。请根据分块 LLM 分析结果和统计候选，整合出“这段时间 bot 是否存在固定句式”，并结构化提取。

判定原则：
1. 固定句式必须有可复现的固定片段或模板结构，支持数至少为 {min_support}。
2. 合并语义相同或模板相近的模式，不要重复列出。
3. 不要把单纯话题重复、人物名称重复、普通功能词重复误判成固定句式。
4. 置信度请根据支持数量、例句一致性和模板清晰度综合估计，范围 0 到 1。
5. supporting_message_indexes 尽量沿用分块结果中的 idx，便于脚本回填原始消息。
6. 只输出 JSON 对象，不要输出 Markdown 或额外解释。

输出 JSON 结构：
{{
  "has_fixed_patterns": true,
  "overall_summary": "总体判断",
  "fixed_patterns": [
    {{
      "pattern_id": "P01",
      "pattern_name": "简短名称",
      "template": "固定句式模板",
      "fixed_parts": ["固定片段"],
      "variable_slots": [
        {{"name": "变量名", "description": "变量含义", "examples": ["样例"]}}
      ],
      "function": "语用功能",
      "tone": "语气/风格",
      "trigger_contexts": ["触发场景"],
      "estimated_count": 3,
      "supporting_message_indexes": [1, 2, 3],
      "examples": ["原文样例"],
      "confidence": 0.0,
      "notes": "补充说明"
    }}
  ],
  "weak_patterns": [
    {{
      "pattern_name": "证据较弱的模式",
      "reason": "为什么暂不列为固定句式",
      "supporting_message_indexes": [4, 5],
      "confidence": 0.0
    }}
  ],
  "recommendations": ["如果这些固定句式过强，可以如何调整"]
}}

语料统计：
{stats_json}

程序统计候选：
{candidates_json}

分块分析结果：
{chunk_json}
"""


def strip_markdown_code_fence(text: str) -> str:
    normalized_text = str(text or "").strip()
    if match := re.search(r"```json\s*(.*?)\s*```", normalized_text, re.DOTALL | re.IGNORECASE):
        return match.group(1).strip()
    normalized_text = re.sub(r"^```\s*", "", normalized_text)
    normalized_text = re.sub(r"\s*```$", "", normalized_text)
    return normalized_text.strip()


def loads_json_object(response_text: str) -> Dict[str, Any]:
    normalized_text = strip_markdown_code_fence(response_text)
    if not normalized_text:
        raise ValueError("LLM 响应为空")

    candidates = [normalized_text]
    start = normalized_text.find("{")
    end = normalized_text.rfind("}")
    if start >= 0 and end > start:
        object_candidate = normalized_text[start : end + 1]
        if object_candidate not in candidates:
            candidates.append(object_candidate)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json

                repaired = repair_json(candidate, return_objects=True)
            except Exception:
                continue
            parsed = repaired
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("无法将 LLM 响应解析为 JSON 对象")


async def request_llm_json(
    prompt: str,
    task_name: str,
    temperature: float,
    max_tokens: int,
) -> LLMJsonResult:
    from src.common.data_models.llm_service_data_models import LLMGenerationOptions
    from src.llm_models.payload_content.resp_format import RespFormat, RespFormatType
    from src.services.llm_service import LLMServiceClient

    client = LLMServiceClient(task_name=task_name, request_type=REQUEST_TYPE)
    result = await client.generate_response(
        prompt=prompt,
        options=LLMGenerationOptions(
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=RespFormat(RespFormatType.JSON_OBJ),
        ),
    )
    return LLMJsonResult(
        payload=loads_json_object(result.response),
        raw_response=result.response,
        model_name=result.model_name,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
    )


def progress(message: str) -> None:
    print(message, file=sys.stderr)


def _coerce_int_list(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    indexes: List[int] = []
    for item in value:
        try:
            indexes.append(int(item))
        except (TypeError, ValueError):
            continue
    return indexes


def enrich_pattern_examples(
    payload: Dict[str, Any],
    message_by_index: Dict[int, BotMessage],
    max_examples: int,
) -> Dict[str, Any]:
    for section_name in ("fixed_patterns", "weak_patterns"):
        patterns = payload.get(section_name)
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            indexes = _coerce_int_list(
                pattern.get("supporting_message_indexes")
                or pattern.get("message_indexes")
                or pattern.get("example_indexes")
            )
            supporting_messages = [
                message_by_index[index].to_example_dict()
                for index in indexes[:max_examples]
                if index in message_by_index
            ]
            if supporting_messages:
                pattern["supporting_messages"] = supporting_messages
    return payload


def build_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"bot_phrase_patterns_{timestamp}.json"


def write_payload(payload: Dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


async def analyze(args: Namespace) -> Dict[str, Any]:
    now = datetime.now()
    has_explicit_since = bool(args.since and args.since.strip())
    since = parse_datetime_filter(args.since) or parse_recent_filter(args.recent, now)
    until = parse_datetime_filter(args.until) or now
    if since is None:
        raise ValueError("必须指定 --since 或 --recent")
    if until <= since:
        raise ValueError("--until 必须晚于起始时间")

    config_accounts, qq_fallback_account = load_bot_accounts_from_config(args.bot_config.resolve())
    cli_accounts = [
        parsed_account
        for raw_account in args.bot_account
        if (parsed_account := parse_platform_account(raw_account, source="cli"))
    ]
    accounts = deduplicate_accounts([*cli_accounts, *config_accounts])
    if not accounts and not qq_fallback_account:
        raise ValueError("未能识别 bot 账号，请检查 bot_config.toml 或通过 --bot-account platform:user_id 指定")

    source_messages = fetch_bot_messages(
        db_path=args.db.resolve(),
        since=since,
        until=until,
        accounts=accounts,
        qq_fallback_account=qq_fallback_account,
        legacy_qq_fallback=not args.no_legacy_qq_fallback,
        session_id=args.session_id,
        platform=args.platform,
        group_id=args.group_id,
        keep_media_placeholders=args.keep_media_placeholders,
        min_text_length=max(1, args.min_text_length),
        limit=max(0, args.limit),
    )
    source_stats = build_corpus_stats(source_messages)
    top_session_limit = max(0, args.top_sessions)
    should_select_top_sessions = top_session_limit > 0 and not args.session_id and not args.group_id
    source_session_stats = build_session_stats(source_messages)
    selected_session_stats: List[Dict[str, Any]] = []
    messages = source_messages
    if should_select_top_sessions:
        selected_session_stats = source_session_stats[:top_session_limit]
        selected_session_ids = {str(session["session_id"]) for session in selected_session_stats}
        messages = [message for message in source_messages if message.session_id in selected_session_ids]

    stats = build_corpus_stats(messages)
    candidates = build_statistical_candidates(
        messages=messages,
        min_support=max(2, args.min_support),
        limit=max(1, args.candidate_limit),
    )
    metadata = {
        "generated_at": now.isoformat(timespec="seconds"),
        "analysis_range": {
            "since": format_datetime_for_sql(since),
            "until": format_datetime_for_sql(until),
            "recent": None if has_explicit_since else args.recent,
        },
        "filters": {
            "session_id": args.session_id,
            "platform": args.platform,
            "group_id": args.group_id,
            "min_text_length": max(1, args.min_text_length),
            "limit": max(0, args.limit),
            "top_sessions": top_session_limit,
        },
        "bot_accounts": [account.display() for account in accounts],
        "legacy_qq_fallback_account": qq_fallback_account if not args.no_legacy_qq_fallback else "",
        "session_selection": {
            "applied": should_select_top_sessions,
            "top_session_limit": top_session_limit,
            "source_message_count": len(source_messages),
            "selected_message_count": len(messages),
            "selected_sessions": selected_session_stats,
        },
        "corpus_stats": stats,
    }
    if should_select_top_sessions:
        metadata["source_corpus_stats"] = source_stats

    if not messages:
        return {
            **metadata,
            "has_fixed_patterns": False,
            "overall_summary": "指定时间段内没有找到 bot 发言。",
            "fixed_patterns": [],
            "weak_patterns": [],
            "recommendations": [],
            "statistical_candidates": candidates,
        }

    if args.dry_run:
        return {
            **metadata,
            "dry_run": True,
            "has_fixed_patterns": False,
            "overall_summary": "dry-run 仅完成消息抽取和统计候选，未调用 LLM。",
            "fixed_patterns": [],
            "weak_patterns": [],
            "recommendations": [],
            "statistical_candidates": candidates,
        }

    metadata["model_thinking_states"] = validate_task_uses_non_thinking_models(
        model_config_path=args.model_config.resolve(),
        task_name=args.task_name,
        allow_thinking=args.allow_thinking,
    )

    chunks = split_chunks(
        messages=messages,
        chunk_char_limit=max(1000, args.chunk_char_limit),
        max_text_chars=max(50, args.max_text_chars),
    )
    if should_select_top_sessions:
        progress(
            f"已从 {len(source_messages)} 条 bot 发言中选择消息最多的 "
            f"{len(selected_session_stats)} 个 session，共 {len(messages)} 条。"
        )
    progress(f"已抽取 {len(messages)} 条 bot 发言，分为 {len(chunks)} 个 LLM 分块。")

    chunk_results: List[LLMJsonResult] = []
    for chunk in chunks:
        progress(f"正在分析分块 {chunk.chunk_id}/{len(chunks)}，消息数 {len(chunk.messages)}。")
        prompt = build_chunk_prompt(
            chunk=chunk,
            min_support=max(2, args.min_support),
            max_text_chars=max(50, args.max_text_chars),
        )
        chunk_results.append(
            await request_llm_json(
                prompt=prompt,
                task_name=args.task_name,
                temperature=args.temperature,
                max_tokens=args.chunk_max_tokens,
            )
        )

    final_prompt = build_final_prompt(
        chunk_payloads=[result.payload for result in chunk_results],
        candidates=candidates,
        stats=stats,
        min_support=max(2, args.min_support),
    )
    progress("正在整合所有分块结果。")
    final_result = await request_llm_json(
        prompt=final_prompt,
        task_name=args.task_name,
        temperature=args.temperature,
        max_tokens=args.final_max_tokens,
    )

    message_by_index = {message.index: message for message in messages}
    final_payload = enrich_pattern_examples(
        payload=final_result.payload,
        message_by_index=message_by_index,
        max_examples=max(1, args.max_examples),
    )
    usage = {
        "chunk_models": [result.model_name for result in chunk_results],
        "final_model": final_result.model_name,
        "prompt_tokens": sum(result.prompt_tokens for result in chunk_results) + final_result.prompt_tokens,
        "completion_tokens": sum(result.completion_tokens for result in chunk_results) + final_result.completion_tokens,
        "total_tokens": sum(result.total_tokens for result in chunk_results) + final_result.total_tokens,
    }

    output_payload: Dict[str, Any] = {
        **metadata,
        **final_payload,
        "llm_usage": usage,
    }
    if args.include_candidates:
        output_payload["statistical_candidates"] = candidates
    if args.include_chunk_results:
        output_payload["chunk_results"] = [result.payload for result in chunk_results]
    return output_payload


def parse_args() -> Namespace:
    parser = ArgumentParser(description="分析一段时间内 bot 发言中的固定句式，并用 LLM 结构化提取。")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"数据库路径，默认: {DEFAULT_DB_PATH}")
    parser.add_argument("--bot-config", type=Path, default=DEFAULT_BOT_CONFIG_PATH, help="bot_config.toml 路径")
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL_CONFIG_PATH, help="model_config.toml 路径")
    parser.add_argument("--recent", default="30d", help="分析最近多久，例如 30m、24h、30d、2w；--since 优先于该参数")
    parser.add_argument("--since", help="起始时间，格式: YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS")
    parser.add_argument("--until", help="结束时间，格式: YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS；默认当前时间")
    parser.add_argument("--session-id", help="只分析指定 session_id")
    parser.add_argument("--platform", help="只分析指定平台")
    parser.add_argument("--group-id", help="只分析指定群号/群聊 ID")
    parser.add_argument(
        "--bot-account",
        action="append",
        default=[],
        help="手动补充 bot 账号，格式 platform:user_id；也可只填 user_id 表示任意平台，可重复传入",
    )
    parser.add_argument("--no-legacy-qq-fallback", action="store_true", help="关闭旧数据的 QQ 账号全平台兜底匹配")
    parser.add_argument("--keep-media-placeholders", action="store_true", help="保留 [图片]、[表情包] 等媒体占位文本")
    parser.add_argument("--min-text-length", type=int, default=1, help="忽略短于该长度的发言")
    parser.add_argument("--min-support", type=int, default=3, help="固定句式至少需要多少条消息支持")
    parser.add_argument("--limit", type=int, default=0, help="最多读取多少条 bot 发言，0 表示不限制")
    parser.add_argument(
        "--top-sessions",
        type=int,
        default=10,
        help="默认只分析消息数最多的 N 个 session_id；0 表示不限制。指定 --session-id/--group-id 时不再自动截取",
    )
    parser.add_argument("--task-name", default="learner", help="使用 model_task_config 下的哪个任务配置调用 LLM")
    parser.add_argument("--allow-thinking", action="store_true", help="允许使用 thinking enabled 的模型，默认会拒绝")
    parser.add_argument("--temperature", type=float, default=0.2, help="LLM 温度")
    parser.add_argument("--chunk-char-limit", type=int, default=16000, help="单个 LLM 分块的字符预算")
    parser.add_argument("--max-text-chars", type=int, default=800, help="单条消息进入 prompt 时的最大字符数")
    parser.add_argument("--chunk-max-tokens", type=int, default=2048, help="分块分析的最大输出 token")
    parser.add_argument("--final-max-tokens", type=int, default=4096, help="最终整合的最大输出 token")
    parser.add_argument("--candidate-limit", type=int, default=20, help="程序统计候选每类最多保留多少条")
    parser.add_argument("--max-examples", type=int, default=5, help="每个句式最多回填多少条原始例句")
    parser.add_argument("--include-candidates", action="store_true", help="在最终 JSON 中包含程序统计候选")
    parser.add_argument("--include-chunk-results", action="store_true", help="在最终 JSON 中包含分块 LLM 原始结构")
    parser.add_argument("--dry-run", action="store_true", help="只抽取消息和统计候选，不调用 LLM")
    parser.add_argument(
        "--output", type=Path, default=None, help="输出 JSON 路径；不指定时写入 data/analysis，填 - 输出到 stdout"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = asyncio.run(analyze(args))
    except Exception as exc:
        print(f"分析失败: {exc}", file=sys.stderr)
        return 1

    if args.output is not None and str(args.output) == "-":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    output_path = args.output if args.output is not None else build_output_path()
    write_payload(payload, output_path.resolve())
    print(f"分析结果已保存到: {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
