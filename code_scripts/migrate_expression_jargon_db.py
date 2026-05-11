from argparse import ArgumentParser, Namespace
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from sys import path as sys_path
from typing import Any, Optional

import json
import sqlite3

from sqlmodel import Session, SQLModel, create_engine

ROOT_PATH = Path(__file__).resolve().parent.parent
if str(ROOT_PATH) not in sys_path:
    sys_path.insert(0, str(ROOT_PATH))

from src.common.database.database_model import ModifiedBy  # noqa: E402


def build_argument_parser() -> ArgumentParser:
    """构建命令行参数解析器。"""
    parser = ArgumentParser(
        description="旧版 expression/jargon 已不再迁移，本工具仅保留为空操作兼容入口。"
    )
    parser.add_argument("--source-db", dest="source_db", help="旧版 SQLite 数据库路径")
    parser.add_argument("--target-db", dest="target_db", help="新版 SQLite 数据库路径")
    parser.add_argument(
        "--clear-target",
        dest="clear_target",
        action="store_true",
        help="保留兼容参数；不再清空任何目标表",
    )
    return parser


def prompt_path(prompt_text: str, current_value: Optional[str] = None) -> Path:
    """读取数据库路径输入。"""
    while True:
        suffix = f" [{current_value}]" if current_value else ""
        raw_text = input(f"{prompt_text}{suffix}: ").strip()
        value = raw_text or current_value or ""
        if not value:
            print("路径不能为空，请重新输入。")
            continue
        return Path(value).expanduser().resolve()


def prompt_yes_no(prompt_text: str, default: bool = False) -> bool:
    """读取是否确认输入。"""
    default_hint = "Y/n" if default else "y/N"
    raw_text = input(f"{prompt_text} [{default_hint}]: ").strip().lower()
    if not raw_text:
        return default
    return raw_text in {"y", "yes"}


def ensure_sqlite_file(path: Path, should_exist: bool) -> None:
    """校验 SQLite 文件路径。"""
    if should_exist and not path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{path}")
    if not should_exist:
        path.parent.mkdir(parents=True, exist_ok=True)


def connect_sqlite(path: Path) -> sqlite3.Connection:
    """创建 SQLite 连接。"""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    """检查表是否存在。"""
    result = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return result is not None


def resolve_source_table_name(connection: sqlite3.Connection, candidates: list[str]) -> str:
    """从候选表名中解析实际存在的表名。"""
    for table_name in candidates:
        if table_exists(connection, table_name):
            return table_name
    raise ValueError(f"未找到候选表：{', '.join(candidates)}")


def get_table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """获取表字段名集合。"""
    rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return {str(row["name"]) for row in rows}


def get_table_nullable_map(connection: sqlite3.Connection, table_name: str) -> dict[str, bool]:
    """获取表字段是否允许 NULL 的映射。"""
    rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return {str(row["name"]): not bool(row["notnull"]) for row in rows}


def load_rows(connection: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
    """读取整张表的数据。"""
    return connection.execute(f"SELECT * FROM {table_name}").fetchall()


def normalize_optional_text(raw_value: Any) -> Optional[str]:
    """标准化可空文本字段。"""
    if raw_value is None:
        return None
    return str(raw_value)


def ensure_nullable_compatibility(
    table_name: str,
    column_name: str,
    row_id: Any,
    value: Any,
    nullable_map: dict[str, bool],
) -> None:
    """检查待迁移值是否与目标表可空约束兼容。"""
    if value is None and not nullable_map.get(column_name, True):
        raise ValueError(
            f"目标表 {table_name}.{column_name} 不允许 NULL，但源记录 id={row_id} 的该字段为 NULL。"
        )


def normalize_string_list(raw_value: Any) -> list[str]:
    """将旧库中的 JSON/文本字段标准化为字符串列表。"""
    if raw_value is None:
        return []
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if not raw_text:
            return []
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            return [raw_text]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, str):
            parsed_text = parsed.strip()
            return [parsed_text] if parsed_text else []
        if parsed is None:
            return []
        return [str(parsed).strip()]
    return [str(raw_value).strip()]


def normalize_modified_by(raw_value: Any) -> Optional[ModifiedBy]:
    """标准化审核来源字段。"""
    if raw_value is None:
        return None

    normalized_raw_value = raw_value
    if isinstance(raw_value, str):
        raw_text = raw_value.strip()
        if raw_text.startswith('"') and raw_text.endswith('"'):
            try:
                normalized_raw_value = json.loads(raw_text)
            except json.JSONDecodeError:
                normalized_raw_value = raw_text
        else:
            normalized_raw_value = raw_text

    value = str(normalized_raw_value).strip().lower()
    if value in {"", "none", "null"}:
        return None
    if value in {ModifiedBy.AI.value, ModifiedBy.AI.name.lower()}:
        return ModifiedBy.AI
    if value in {ModifiedBy.USER.value, ModifiedBy.USER.name.lower()}:
        return ModifiedBy.USER
    return None


def parse_optional_bool(raw_value: Any) -> Optional[bool]:
    """解析可空布尔值，兼容整数和字符串。"""
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int):
        return bool(raw_value)
    if isinstance(raw_value, float):
        return bool(int(raw_value))

    value = str(raw_value).strip().lower()
    if value in {"", "none", "null"}:
        return None
    if value in {"1", "true", "t", "yes", "y"}:
        return True
    if value in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError(f"无法解析布尔值：{raw_value}")


def parse_bool(raw_value: Any, default: bool = False) -> bool:
    """解析非空布尔值。"""
    parsed = parse_optional_bool(raw_value)
    return default if parsed is None else parsed


def timestamp_to_datetime(raw_value: Any, fallback_now: bool) -> Optional[datetime]:
    """将旧库中的 Unix 时间戳转换为 datetime。"""
    if raw_value is None or raw_value == "":
        return datetime.now() if fallback_now else None
    if isinstance(raw_value, datetime):
        return raw_value
    try:
        return datetime.fromtimestamp(float(raw_value))
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now() if fallback_now else None


def build_session_id_dict(raw_chat_id: Any, fallback_count: int) -> str:
    """将旧版 jargon.chat_id 转换为新版 session_id_dict。"""
    if raw_chat_id is None:
        return json.dumps({}, ensure_ascii=False)

    if isinstance(raw_chat_id, str):
        raw_text = raw_chat_id.strip()
    else:
        raw_text = str(raw_chat_id).strip()

    if not raw_text:
        return json.dumps({}, ensure_ascii=False)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return json.dumps({raw_text: max(fallback_count, 1)}, ensure_ascii=False)

    if isinstance(parsed, str):
        parsed_text = parsed.strip()
        session_counts = {parsed_text: max(fallback_count, 1)} if parsed_text else {}
        return json.dumps(session_counts, ensure_ascii=False)

    if not isinstance(parsed, list):
        return json.dumps({}, ensure_ascii=False)

    session_counts: dict[str, int] = {}
    for item in parsed:
        if not isinstance(item, list) or not item:
            continue
        session_id = str(item[0]).strip()
        if not session_id:
            continue
        item_count = 1
        if len(item) > 1:
            try:
                item_count = int(item[1])
            except (TypeError, ValueError):
                item_count = 1
        session_counts[session_id] = max(item_count, 1)

    return json.dumps(session_counts, ensure_ascii=False)


def create_target_engine(target_db_path: Path):
    """创建目标数据库引擎。"""
    return create_engine(
        f"sqlite:///{target_db_path.as_posix()}",
        echo=False,
        connect_args={"check_same_thread": False},
    )


def clear_target_tables(session: Session) -> None:
    """旧版 expression/jargon 不迁移时不清空任何目标表。"""
    del session


def migrate_expressions(
    old_rows: Iterable[sqlite3.Row],
    target_session: Session,
    expression_columns: set[str],
) -> int:
    """跳过 expression 数据迁移。"""
    del old_rows, target_session, expression_columns
    return 0


def migrate_jargons(
    old_rows: Iterable[sqlite3.Row],
    target_session: Session,
    jargon_columns: set[str],
    jargon_nullable_map: dict[str, bool],
) -> int:
    """跳过 jargon 数据迁移。"""
    del old_rows, target_session, jargon_columns, jargon_nullable_map
    return 0


def confirm_target_replacement(target_db_path: Path, clear_target: bool) -> bool:
    """确认是否写入目标数据库。"""
    if clear_target:
        return prompt_yes_no(f"不会清空目标库，也不会迁移 expression/jargon，确认继续吗？\n目标库：{target_db_path}")
    return prompt_yes_no(f"不会写入 expression/jargon，确认继续吗？\n目标库：{target_db_path}")


def parse_arguments() -> Namespace:
    """解析参数。"""
    return build_argument_parser().parse_args()


def main() -> None:
    """脚本入口。"""
    args = parse_arguments()

    print("旧版 expression/jargon 迁移工具（当前不迁移 expression/jargon）")
    source_db_path = prompt_path("请输入旧版数据库路径", args.source_db)
    target_db_path = prompt_path("请输入新版数据库路径", args.target_db)
    clear_target = args.clear_target or prompt_yes_no("是否继续空操作迁移流程？", False)

    if source_db_path == target_db_path:
        raise ValueError("旧版数据库路径和新版数据库路径不能相同。")

    ensure_sqlite_file(source_db_path, should_exist=True)
    ensure_sqlite_file(target_db_path, should_exist=False)

    print(f"旧库：{source_db_path}")
    print(f"新库：{target_db_path}")
    print(f"清空目标表：{'是' if clear_target else '否'}")

    if not confirm_target_replacement(target_db_path, clear_target):
        print("已取消迁移。")
        return

    target_engine = create_target_engine(target_db_path)
    SQLModel.metadata.create_all(target_engine)

    with Session(target_engine) as target_session:
        if clear_target:
            clear_target_tables(target_session)
            target_session.commit()

        expression_count = 0
        jargon_count = 0
        target_session.commit()

    print("迁移完成。")
    print(f"已跳过 expression 记录迁移：{expression_count}")
    print(f"已跳过 jargon 记录迁移：{jargon_count}")


if __name__ == "__main__":
    main()
