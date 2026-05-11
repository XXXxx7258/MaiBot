from argparse import ArgumentParser, Namespace
from dataclasses import asdict, dataclass
from pathlib import Path
from sys import path as sys_path
from typing import Optional

import json

from sqlalchemy import func
from sqlmodel import Session, col, create_engine, select

ROOT_PATH = Path(__file__).resolve().parent.parent
if str(ROOT_PATH) not in sys_path:
    sys_path.insert(0, str(ROOT_PATH))

from src.common.database.database_model import ChatSession, Expression, Messages  # noqa: E402


DEFAULT_DB_PATH = ROOT_PATH / "data" / "MaiBot.db"


@dataclass
class OrphanExpressionSession:
    """同一个孤儿 session_id 下的表达方式统计。"""

    session_id: str
    expression_count: int
    expression_ids: list[int]
    sample_situations: list[str]
    message_count: int = 0
    latest_message_time: Optional[str] = None


def build_argument_parser() -> ArgumentParser:
    """构建命令行参数解析器。"""
    parser = ArgumentParser(description="检查 expressions 表里找不到 ChatSession 的孤儿表达方式。")
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
        help="每个 session_id 最多展示多少个表达示例，默认 3。",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果。")
    parser.add_argument(
        "--fail-on-found",
        action="store_true",
        help="发现孤儿表达时以退出码 1 结束，便于接入自动检查。",
    )
    return parser


def build_engine(db_path: Path):
    """基于指定 SQLite 文件创建只读检查用连接。"""
    resolved_path = db_path.expanduser().resolve()
    if not resolved_path.is_file():
        raise FileNotFoundError(f"数据库文件不存在：{resolved_path}")
    return create_engine(f"sqlite:///{resolved_path}", connect_args={"check_same_thread": False})


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


def collect_orphan_expression_sessions(session: Session, sample_size: int) -> list[OrphanExpressionSession]:
    """收集所有 session_id 找不到 ChatSession 的表达方式。"""
    existing_session_ids = set(session.exec(select(ChatSession.session_id)).all())
    expressions = session.exec(select(Expression).where(col(Expression.session_id).is_not(None))).all()

    grouped: dict[str, OrphanExpressionSession] = {}
    for expression in expressions:
        if not expression.session_id or expression.session_id in existing_session_ids:
            continue

        summary = grouped.setdefault(
            expression.session_id,
            OrphanExpressionSession(
                session_id=expression.session_id,
                expression_count=0,
                expression_ids=[],
                sample_situations=[],
            ),
        )
        summary.expression_count += 1
        if expression.id is not None:
            summary.expression_ids.append(expression.id)
        if len(summary.sample_situations) < sample_size:
            summary.sample_situations.append(expression.situation)

    session_ids = sorted(grouped)
    message_stats = load_message_stats(session, session_ids)
    for session_id, summary in grouped.items():
        message_count, latest_time = message_stats.get(session_id, (0, None))
        summary.message_count = message_count
        summary.latest_message_time = latest_time

    return sorted(grouped.values(), key=lambda item: (-item.expression_count, item.session_id))


def print_text_report(db_path: Path, summaries: list[OrphanExpressionSession], limit: int) -> None:
    """输出便于人工阅读的检查报告。"""
    total_expression_count = sum(summary.expression_count for summary in summaries)
    print(f"数据库：{db_path.expanduser().resolve()}")

    if not summaries:
        print("未发现孤儿表达：所有非全局表达的 session_id 都能找到 ChatSession。")
        return

    print(f"发现 {total_expression_count} 条孤儿表达，涉及 {len(summaries)} 个 session_id。")
    visible_summaries = summaries if limit <= 0 else summaries[:limit]
    for summary in visible_summaries:
        latest_time = summary.latest_message_time or "-"
        ids_preview = ", ".join(str(expression_id) for expression_id in summary.expression_ids[:20])
        if len(summary.expression_ids) > 20:
            ids_preview += ", ..."

        print()
        print(
            f"session_id={summary.session_id} | "
            f"表达数={summary.expression_count} | "
            f"消息数={summary.message_count} | "
            f"最近消息={latest_time}"
        )
        print(f"  表达ID：{ids_preview}")
        for situation in summary.sample_situations:
            print(f"  示例情景：{situation}")

    hidden_count = len(summaries) - len(visible_summaries)
    if hidden_count > 0:
        print()
        print(f"还有 {hidden_count} 个 session_id 未展示，可使用 --limit 0 查看全部。")


def main() -> int:
    parser = build_argument_parser()
    args: Namespace = parser.parse_args()

    engine = build_engine(args.db)
    with Session(engine) as session:
        summaries = collect_orphan_expression_sessions(session, max(args.sample_size, 0))

    if args.json:
        print(json.dumps([asdict(summary) for summary in summaries], ensure_ascii=False, indent=2))
    else:
        print_text_report(args.db, summaries, args.limit)

    if summaries and args.fail_on_found:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
