from argparse import ArgumentParser, Namespace
from dataclasses import asdict, dataclass
from pathlib import Path
from sys import path as sys_path
from typing import Any, Optional

import json

from sqlalchemy import func
from sqlmodel import Session, col, create_engine, select

ROOT_PATH = Path(__file__).resolve().parent.parent
if str(ROOT_PATH) not in sys_path:
    sys_path.insert(0, str(ROOT_PATH))

from src.common.database.database_model import ChatSession, Jargon, Messages  # noqa: E402


DEFAULT_DB_PATH = ROOT_PATH / "data" / "MaiBot.db"


@dataclass
class OrphanJargonSession:
    """同一个孤儿 session_id 下的黑话统计。"""

    session_id: str
    jargon_count: int
    jargon_ids: list[int]
    sample_contents: list[str]
    total_session_count: int
    message_count: int = 0
    latest_message_time: Optional[str] = None


@dataclass
class BrokenJargonSessionDict:
    """无法解析 session_id_dict 的黑话记录。"""

    jargon_id: int
    content: str
    raw_session_id_dict: str


def build_argument_parser() -> ArgumentParser:
    """构建命令行参数解析器。"""
    parser = ArgumentParser(description="检查 jargons 表里找不到 ChatSession 的孤儿黑话引用。")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"SQLite 数据库路径，默认：{DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="最多输出多少个孤儿 session_id，默认 50；传入 0 表示不限制。",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=3,
        help="每个 session_id 最多展示多少条黑话示例，默认 3。",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果。")
    parser.add_argument(
        "--fail-on-found",
        action="store_true",
        help="发现孤儿黑话引用或损坏 session_id_dict 时以退出码 1 结束。",
    )
    return parser


def build_engine(db_path: Path):
    """基于指定 SQLite 文件创建只读检查用连接。"""
    resolved_path = db_path.expanduser().resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{resolved_path}")
    return create_engine(f"sqlite:///{resolved_path}", connect_args={"check_same_thread": False})


def parse_session_id_dict(raw_value: str) -> Optional[dict[str, int]]:
    """解析黑话记录里的 session_id_dict。"""
    try:
        parsed = json.loads(raw_value or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None

    result: dict[str, int] = {}
    for raw_session_id, raw_count in parsed.items():
        session_id = str(raw_session_id or "").strip()
        if not session_id:
            continue
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            count = 1
        result[session_id] = max(count, 1)
    return result


def load_message_stats(session: Session, session_ids: list[str]) -> dict[str, tuple[int, Optional[str]]]:
    """读取孤儿 session_id 在消息表中的残留消息数量与最近时间。"""
    if not session_ids:
        return {}

    statement = (
        select(Messages.session_id, func.count(Messages.id), func.max(Messages.timestamp))
        .where(col(Messages.session_id).in_(session_ids))
        .group_by(Messages.session_id)
    )
    stats: dict[str, tuple[int, Optional[str]]] = {}
    for session_id, message_count, latest_time in session.exec(statement).all():
        stats[str(session_id)] = (
            int(message_count or 0),
            latest_time.isoformat(sep=" ", timespec="seconds") if latest_time else None,
        )
    return stats


def collect_orphan_jargon_sessions(
    session: Session, sample_size: int
) -> tuple[list[OrphanJargonSession], list[BrokenJargonSessionDict]]:
    """收集所有 session_id 找不到 ChatSession 的黑话引用。"""
    existing_session_ids = set(session.exec(select(ChatSession.session_id)).all())
    jargons = session.exec(select(Jargon)).all()

    grouped: dict[str, OrphanJargonSession] = {}
    broken_items: list[BrokenJargonSessionDict] = []
    for jargon in jargons:
        session_counts = parse_session_id_dict(jargon.session_id_dict)
        if session_counts is None:
            broken_items.append(
                BrokenJargonSessionDict(
                    jargon_id=jargon.id or 0,
                    content=jargon.content,
                    raw_session_id_dict=jargon.session_id_dict,
                )
            )
            continue

        for session_id, session_count in session_counts.items():
            if session_id in existing_session_ids:
                continue

            summary = grouped.setdefault(
                session_id,
                OrphanJargonSession(
                    session_id=session_id,
                    jargon_count=0,
                    jargon_ids=[],
                    sample_contents=[],
                    total_session_count=0,
                ),
            )
            summary.jargon_count += 1
            summary.total_session_count += session_count
            if jargon.id is not None:
                summary.jargon_ids.append(jargon.id)
            if len(summary.sample_contents) < sample_size:
                summary.sample_contents.append(jargon.content)

    session_ids = sorted(grouped)
    message_stats = load_message_stats(session, session_ids)
    for session_id, summary in grouped.items():
        message_count, latest_time = message_stats.get(session_id, (0, None))
        summary.message_count = message_count
        summary.latest_message_time = latest_time

    return (
        sorted(grouped.values(), key=lambda item: (-item.jargon_count, item.session_id)),
        broken_items,
    )


def print_text_report(
    db_path: Path,
    summaries: list[OrphanJargonSession],
    broken_items: list[BrokenJargonSessionDict],
    limit: int,
) -> None:
    """输出便于人工阅读的检查报告。"""
    total_jargon_count = sum(summary.jargon_count for summary in summaries)
    print(f"数据库：{db_path.expanduser().resolve()}")

    if not summaries and not broken_items:
        print("未发现孤儿黑话引用：所有 session_id_dict 中的 session_id 都能找到 ChatSession。")
        return

    if summaries:
        print(f"发现 {total_jargon_count} 条孤儿黑话引用，涉及 {len(summaries)} 个 session_id。")
        visible_summaries = summaries if limit <= 0 else summaries[:limit]
        for summary in visible_summaries:
            latest_time = summary.latest_message_time or "-"
            ids_preview = ", ".join(str(jargon_id) for jargon_id in summary.jargon_ids[:20])
            if len(summary.jargon_ids) > 20:
                ids_preview += ", ..."

            print()
            print(
                f"session_id={summary.session_id} | "
                f"黑话数={summary.jargon_count} | "
                f"累计次数={summary.total_session_count} | "
                f"消息数={summary.message_count} | "
                f"最近消息={latest_time}"
            )
            print(f"  黑话ID：{ids_preview}")
            for content in summary.sample_contents:
                print(f"  示例黑话：{content}")

        hidden_count = len(summaries) - len(visible_summaries)
        if hidden_count > 0:
            print()
            print(f"还有 {hidden_count} 个 session_id 未展示，可使用 --limit 0 查看全部。")

    if broken_items:
        print()
        print(f"另有 {len(broken_items)} 条黑话的 session_id_dict 无法解析。")
        for item in broken_items[:20]:
            print(f"  黑话ID={item.jargon_id} 内容={item.content} session_id_dict={item.raw_session_id_dict!r}")
        if len(broken_items) > 20:
            print(f"  还有 {len(broken_items) - 20} 条未展示。")


def main() -> int:
    parser = build_argument_parser()
    args: Namespace = parser.parse_args()

    engine = build_engine(args.db)
    with Session(engine) as session:
        summaries, broken_items = collect_orphan_jargon_sessions(session, max(args.sample_size, 0))

    if args.json:
        print(
            json.dumps(
                {
                    "orphan_sessions": [asdict(summary) for summary in summaries],
                    "broken_session_id_dicts": [asdict(item) for item in broken_items],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print_text_report(args.db, summaries, broken_items, args.limit)

    if (summaries or broken_items) and args.fail_on_found:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
