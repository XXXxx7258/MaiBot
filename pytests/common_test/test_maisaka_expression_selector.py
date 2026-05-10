from types import SimpleNamespace

import pytest

import src.chat.replyer.maisaka_expression_selector as selector_module
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector
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

