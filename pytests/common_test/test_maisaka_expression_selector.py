from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Generator

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
import pytest

from src.chat.replyer import maisaka_expression_selector as selector_module
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector
from src.common.database.database_model import Expression, ModifiedBy
from src.common.utils.utils_session import SessionUtils


def _build_target(platform: str, item_id: str, rule_type: str = "group") -> SimpleNamespace:
    return SimpleNamespace(platform=platform, item_id=item_id, rule_type=rule_type)


def test_resolve_expression_group_scope_returns_related_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    current_session_id = SessionUtils.calculate_session_id("qq", group_id="10001")
    related_session_id = SessionUtils.calculate_session_id("qq", group_id="10002")

    monkeypatch.setattr(
        selector_module,
        "global_config",
        SimpleNamespace(
            expression=SimpleNamespace(
                expression_groups=[
                    SimpleNamespace(
                        targets=[
                            _build_target("qq", "10001"),
                            _build_target("qq", "10002"),
                        ]
                    )
                ]
            )
        ),
    )
    target_session_ids = {
        "10001": current_session_id,
        "10002": related_session_id,
    }
    monkeypatch.setattr(
        selector_module.ChatConfigUtils,
        "get_target_session_ids",
        lambda target_item: {target_session_ids[target_item.item_id]},
    )
    monkeypatch.setattr(
        selector_module.ChatConfigUtils,
        "target_matches_session",
        lambda target_item, session_id: target_item.item_id == "10001" and session_id == current_session_id,
    )

    selector = MaisakaExpressionSelector()
    related_session_ids, has_global_share = selector._resolve_expression_group_scope(current_session_id)

    assert related_session_ids == {current_session_id, related_session_id}
    assert has_global_share is False


def test_resolve_expression_group_scope_matches_routed_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    current_session_id = SessionUtils.calculate_session_id("qq", group_id="10001", account_id="bot-a")
    related_session_id = SessionUtils.calculate_session_id("qq", group_id="10002", account_id="bot-a")

    monkeypatch.setattr(
        selector_module,
        "global_config",
        SimpleNamespace(
            expression=SimpleNamespace(
                expression_groups=[
                    SimpleNamespace(
                        targets=[
                            _build_target("qq", "10001"),
                            _build_target("qq", "10002"),
                        ]
                    )
                ]
            )
        ),
    )
    monkeypatch.setattr(
        selector_module.ChatConfigUtils,
        "_get_chat_stream",
        lambda session_id: SimpleNamespace(platform="qq", group_id="10001", user_id=None)
        if session_id == current_session_id
        else None,
    )
    target_session_ids = {
        "10001": current_session_id,
        "10002": related_session_id,
    }
    monkeypatch.setattr(
        selector_module.ChatConfigUtils,
        "get_target_session_ids",
        lambda target_item: {target_session_ids[target_item.item_id]},
    )

    selector = MaisakaExpressionSelector()
    related_session_ids, has_global_share = selector._resolve_expression_group_scope(current_session_id)

    assert related_session_ids == {current_session_id, related_session_id}
    assert has_global_share is False


def test_resolve_expression_group_scope_uses_star_as_global_share(monkeypatch: pytest.MonkeyPatch) -> None:
    current_session_id = SessionUtils.calculate_session_id("qq", group_id="10001")

    monkeypatch.setattr(
        selector_module,
        "global_config",
        SimpleNamespace(
            expression=SimpleNamespace(
                expression_groups=[
                    SimpleNamespace(
                        targets=[
                            _build_target("*", "*"),
                        ]
                    )
                ]
            )
        ),
    )

    selector = MaisakaExpressionSelector()
    related_session_ids, has_global_share = selector._resolve_expression_group_scope(current_session_id)

    assert related_session_ids == {current_session_id}
    assert has_global_share is True


def test_resolve_expression_group_scope_does_not_treat_empty_target_as_global(monkeypatch: pytest.MonkeyPatch) -> None:
    current_session_id = SessionUtils.calculate_session_id("qq", group_id="10001")

    monkeypatch.setattr(
        selector_module,
        "global_config",
        SimpleNamespace(
            expression=SimpleNamespace(
                expression_groups=[
                    SimpleNamespace(
                        targets=[
                            _build_target("", ""),
                        ]
                    )
                ]
            )
        ),
    )

    selector = MaisakaExpressionSelector()
    related_session_ids, has_global_share = selector._resolve_expression_group_scope(current_session_id)

    assert related_session_ids == {current_session_id}
    assert has_global_share is False


def test_load_expression_candidates_checked_only_requires_user_review(monkeypatch: pytest.MonkeyPatch) -> None:
    """仅用已检查表达时，只允许人工 USER 检查过的表达进入候选池。"""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    session_id = "session-a"
    now = datetime.now()
    user_checked_ids: set[int] = set()

    with Session(engine) as session:
        for index in range(10):
            expression = Expression(
                situation=f"人工情景{index}",
                style=f"人工风格{index}",
                content_list="[]",
                count=1,
                session_id=session_id,
                checked=True,
                modified_by=ModifiedBy.USER,
                create_time=now,
                last_active_time=now,
            )
            session.add(expression)
            session.flush()
            assert expression.id is not None
            user_checked_ids.add(expression.id)

        for index in range(10):
            session.add(
                Expression(
                    situation=f"AI情景{index}",
                    style=f"AI风格{index}",
                    content_list="[]",
                    count=1,
                    session_id=session_id,
                    checked=True,
                    modified_by=ModifiedBy.AI,
                    create_time=now,
                    last_active_time=now,
                )
            )
        session.commit()

    @contextmanager
    def fake_get_db_session(auto_commit: bool = True) -> Generator[Session, None, None]:
        session = Session(engine)
        try:
            yield session
            if auto_commit:
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(selector_module, "get_db_session", fake_get_db_session)
    monkeypatch.setattr(selector_module, "weighted_sample", lambda items, count: list(items[:count]))
    monkeypatch.setattr(
        selector_module,
        "global_config",
        SimpleNamespace(
            expression=SimpleNamespace(
                expression_checked_only=True,
                expression_groups=[],
            )
        ),
    )

    candidates = MaisakaExpressionSelector()._load_expression_candidates(session_id)

    assert candidates
    assert {candidate["id"] for candidate in candidates}.issubset(user_checked_ids)

