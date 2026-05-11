from types import SimpleNamespace

from src.chat.message_receive.chat_manager import chat_manager
from src.common.utils.utils_config import ChatConfigUtils, ExpressionConfigUtils, JargonConfigUtils
from src.common.utils.utils_session import SessionUtils
from src.config.config import global_config


def test_get_chat_prompt_for_chat_merges_multiple_matching_prompts(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828")
    monkeypatch.setattr(
        global_config.chat,
        "chat_prompts",
        [
            {"platform": "qq", "item_id": "1036092828", "rule_type": "group", "prompt": "你也是群管理员，可以适当进行管理"},
            {"platform": "qq", "item_id": "1036092828", "rule_type": "group", "prompt": "这个群是技术实验群，请你专心讨论技术"},
            {"platform": "qq", "item_id": "other", "rule_type": "group", "prompt": "不应该生效"},
        ],
    )
    monkeypatch.setattr(chat_manager, "get_session_by_session_id", lambda _session_id: None)

    result = ChatConfigUtils.get_chat_prompt_for_chat(session_id, True)

    assert result == "你也是群管理员，可以适当进行管理\n这个群是技术实验群，请你专心讨论技术"


def test_get_chat_prompt_for_chat_matches_routed_session_by_chat_stream(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(
        global_config.chat,
        "chat_prompts",
        [
            {"platform": "qq", "item_id": "1036092828", "rule_type": "group", "prompt": "路由会话也应该生效"},
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None),
    )

    result = ChatConfigUtils.get_chat_prompt_for_chat(session_id, True)

    assert result == "路由会话也应该生效"


def test_expression_learning_list_matches_routed_session_by_chat_stream(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(
        global_config.expression,
        "learning_list",
        [
            {
                "platform": "qq",
                "item_id": "1036092828",
                "type": "group",
                "use": False,
                "learn": False,
            }
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None),
    )

    assert ExpressionConfigUtils.get_expression_config_for_chat(session_id) == (False, False)


def test_expression_learning_list_wildcard_takes_priority_over_exact(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(
        global_config.expression,
        "learning_list",
        [
            {
                "platform": "qq",
                "item_id": "1036092828",
                "type": "group",
                "use": False,
                "learn": False,
            },
            {
                "platform": "qq",
                "item_id": "*",
                "type": "group",
                "use": True,
                "learn": True,
            },
            {
                "platform": "",
                "item_id": "",
                "type": "group",
                "use": False,
                "learn": True,
            },
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None),
    )

    assert ExpressionConfigUtils.get_expression_config_for_chat(session_id) == (True, True)


def test_expression_learning_list_exact_takes_priority_when_no_wildcard_matches(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(
        global_config.expression,
        "learning_list",
        [
            {
                "platform": "telegram",
                "item_id": "*",
                "type": "group",
                "use": True,
                "learn": True,
            },
            {
                "platform": "qq",
                "item_id": "1036092828",
                "type": "group",
                "use": False,
                "learn": False,
            },
            {
                "platform": "",
                "item_id": "",
                "type": "group",
                "use": True,
                "learn": True,
            },
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None),
    )

    assert ExpressionConfigUtils.get_expression_config_for_chat(session_id) == (False, False)


def test_jargon_learning_list_matches_routed_session_by_chat_stream(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(
        global_config.jargon,
        "learning_list",
        [
            {
                "platform": "qq",
                "item_id": "1036092828",
                "type": "group",
                "learn": False,
            }
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None, is_group_session=True),
    )

    assert JargonConfigUtils.get_jargon_config_for_chat(session_id) == (True, False)


def test_jargon_learning_list_wildcard_takes_priority_over_exact(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(
        global_config.jargon,
        "learning_list",
        [
            {
                "platform": "qq",
                "item_id": "1036092828",
                "type": "group",
                "learn": False,
            },
            {
                "platform": "qq",
                "item_id": "*",
                "type": "group",
                "learn": True,
            },
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None, is_group_session=True),
    )

    assert JargonConfigUtils.get_jargon_config_for_chat(session_id) == (True, True)


def test_jargon_learning_list_supports_platform_wildcard(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(
        global_config.jargon,
        "learning_list",
        [
            {
                "platform": "*",
                "item_id": "1036092828",
                "type": "group",
                "learn": False,
            }
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None, is_group_session=True),
    )

    assert JargonConfigUtils.get_jargon_config_for_chat(session_id) == (True, False)


def test_jargon_group_scope_supports_item_id_wildcard(monkeypatch):
    session_id = "session-a"
    other_session_id = "session-b"
    private_session_id = "session-c"
    monkeypatch.setattr(
        global_config.jargon,
        "jargon_groups",
        [
            {
                "targets": [
                    {"platform": "qq", "item_id": "*", "rule_type": "group"},
                ]
            }
        ],
    )
    sessions = {
        session_id: SimpleNamespace(
            session_id=session_id,
            platform="qq",
            group_id="10001",
            user_id=None,
            is_group_session=True,
        ),
        other_session_id: SimpleNamespace(
            session_id=other_session_id,
            platform="qq",
            group_id="10002",
            user_id=None,
            is_group_session=True,
        ),
        private_session_id: SimpleNamespace(
            session_id=private_session_id,
            platform="qq",
            group_id=None,
            user_id="10003",
            is_group_session=False,
        ),
    }
    monkeypatch.setattr(chat_manager, "sessions", sessions)
    monkeypatch.setattr(chat_manager, "get_session_by_session_id", lambda target_session_id: sessions.get(target_session_id))

    related_session_ids, has_global_share = JargonConfigUtils.resolve_jargon_group_scope(session_id)

    assert related_session_ids >= {session_id, other_session_id}
    assert private_session_id not in related_session_ids
    assert has_global_share is False


def test_talk_value_rules_match_routed_session_by_chat_stream(monkeypatch):
    session_id = SessionUtils.calculate_session_id("qq", group_id="1036092828", account_id="bot-a")
    monkeypatch.setattr(global_config.chat, "talk_value", 0.1)
    monkeypatch.setattr(global_config.chat, "enable_talk_value_rules", True)
    monkeypatch.setattr(
        global_config.chat,
        "talk_value_rules",
        [
            {"platform": "qq", "item_id": "1036092828", "rule_type": "group", "time": "00:00-23:59", "value": 0.7}
        ],
    )
    monkeypatch.setattr(
        chat_manager,
        "get_session_by_session_id",
        lambda _session_id: SimpleNamespace(platform="qq", group_id="1036092828", user_id=None),
    )

    assert ChatConfigUtils.get_talk_value(session_id, True) == 0.7
