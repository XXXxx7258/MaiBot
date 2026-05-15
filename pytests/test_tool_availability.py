from types import SimpleNamespace
from typing import Any
import importlib.util
import sys

import pytest

from src.core.tooling import ToolAvailabilityContext, ToolRegistry
from src.maisaka.tool_provider import MaisakaBuiltinToolProvider
from src.plugin_runtime.component_query import ComponentQueryService
from src.plugin_runtime.host.component_registry import ComponentRegistry


@pytest.mark.asyncio
async def test_builtin_at_tool_is_not_exposed() -> None:
    registry = ToolRegistry()
    registry.register_provider(MaisakaBuiltinToolProvider())

    group_specs = await registry.list_tools(ToolAvailabilityContext(session_id="group-1", is_group_chat=True))
    private_specs = await registry.list_tools(ToolAvailabilityContext(session_id="private-1", is_group_chat=False))
    default_specs = await registry.list_tools()

    assert "at" not in {tool_spec.name for tool_spec in group_specs}
    assert "at" not in {tool_spec.name for tool_spec in private_specs}
    assert "at" not in {tool_spec.name for tool_spec in default_specs}


def test_plugin_tool_chat_scope_uses_component_field(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ComponentQueryService()
    registry = ComponentRegistry()
    supervisor = SimpleNamespace(component_registry=registry)
    monkeypatch.setattr(service, "_iter_supervisors", lambda: [supervisor])

    registry.register_plugin_components(
        "scope_plugin",
        [
            {
                "name": "group_tool",
                "component_type": "TOOL",
                "chat_scope": "group",
                "metadata": {"description": "group only"},
            },
            {
                "name": "private_tool",
                "component_type": "TOOL",
                "chat_scope": "private",
                "metadata": {"description": "private only"},
            },
            {
                "name": "all_tool",
                "component_type": "TOOL",
                "metadata": {"description": "all chats"},
            },
        ],
    )

    group_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(session_id="group-1", is_group_chat=True)
    )
    private_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(session_id="private-1", is_group_chat=False)
    )

    group_entry = registry.get_component("scope_plugin.group_tool")
    assert group_entry is not None
    assert group_entry.chat_scope == "group"
    assert "chat_scope" not in group_entry.metadata
    assert set(group_specs) == {"group_tool", "all_tool"}
    assert set(private_specs) == {"private_tool", "all_tool"}


def test_plugin_tool_session_disable_still_filters_specific_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ComponentQueryService()
    registry = ComponentRegistry()
    supervisor = SimpleNamespace(component_registry=registry)
    monkeypatch.setattr(service, "_iter_supervisors", lambda: [supervisor])

    registry.register_plugin_components(
        "mute_plugin",
        [
            {
                "name": "mute",
                "component_type": "TOOL",
                "chat_scope": "group",
                "metadata": {"description": "mute group member"},
            }
        ],
    )
    registry.set_component_enabled("mute_plugin.mute", False, session_id="group-disabled")

    disabled_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(session_id="group-disabled", is_group_chat=True)
    )
    enabled_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(session_id="group-enabled", is_group_chat=True)
    )

    assert "mute" not in disabled_specs
    assert "mute" in enabled_specs


def test_plugin_tool_allowed_session_filters_tool_exposure(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ComponentQueryService()
    registry = ComponentRegistry()
    supervisor = SimpleNamespace(component_registry=registry)
    monkeypatch.setattr(service, "_iter_supervisors", lambda: [supervisor])

    registry.register_plugin_components(
        "mute_plugin",
        [
            {
                "name": "mute",
                "component_type": "TOOL",
                "chat_scope": "group",
                "allowed_session": ["qq:10001", "raw-group-id", "exact-session-id"],
                "metadata": {"description": "mute group member"},
            }
        ],
    )

    platform_group_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(
            session_id="hashed-session-1",
            is_group_chat=True,
            group_id="10001",
            platform="qq",
        )
    )
    raw_group_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(
            session_id="hashed-session-2",
            is_group_chat=True,
            group_id="raw-group-id",
            platform="qq",
        )
    )
    exact_session_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(session_id="exact-session-id", is_group_chat=True)
    )
    blocked_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(
            session_id="blocked-session",
            is_group_chat=True,
            group_id="20002",
            platform="qq",
        )
    )

    entry = registry.get_component("mute_plugin.mute")
    assert entry is not None
    assert entry.allowed_session == {"qq:10001", "raw-group-id", "exact-session-id"}
    assert "allowed_session" not in entry.metadata
    assert "mute" in platform_group_specs
    assert "mute" in raw_group_specs
    assert "mute" in exact_session_specs
    assert "mute" not in blocked_specs


def test_plugin_tool_can_declare_visible_core_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ComponentQueryService()
    registry = ComponentRegistry()
    supervisor = SimpleNamespace(component_registry=registry)
    monkeypatch.setattr(service, "_iter_supervisors", lambda: [supervisor])

    registry.register_plugin_components(
        "core_tool_plugin",
        [
            {
                "name": "always_ready",
                "component_type": "TOOL",
                "metadata": {
                    "description": "directly visible tool",
                    "core_tool": True,
                },
            },
            {
                "name": "explicit_visible",
                "component_type": "TOOL",
                "metadata": {
                    "description": "explicitly visible tool",
                    "visibility": "visible",
                },
            },
            {
                "name": "normal_tool",
                "component_type": "TOOL",
                "metadata": {"description": "deferred by default"},
            },
        ],
    )

    specs = service.get_llm_available_tool_specs()

    assert specs["always_ready"].metadata["visibility"] == "visible"
    assert specs["explicit_visible"].metadata["visibility"] == "visible"
    assert specs["normal_tool"].metadata["visibility"] == "deferred"


def test_plugin_tool_can_be_hidden_from_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ComponentQueryService()
    registry = ComponentRegistry()
    supervisor = SimpleNamespace(component_registry=registry)
    monkeypatch.setattr(service, "_iter_supervisors", lambda: [supervisor])

    registry.register_plugin_components(
        "hidden_tool_plugin",
        [
            {
                "name": "internal_only",
                "component_type": "TOOL",
                "metadata": {
                    "description": "internal tool",
                    "visibility": "hidden",
                },
            }
        ],
    )

    specs = service.get_llm_available_tool_specs()

    assert specs["internal_only"].metadata["visibility"] == "hidden"
    assert specs["internal_only"].enabled is False


def test_plugin_tool_disabled_session_take_precedence_over_allowed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ComponentQueryService()
    registry = ComponentRegistry()
    supervisor = SimpleNamespace(component_registry=registry)
    monkeypatch.setattr(service, "_iter_supervisors", lambda: [supervisor])

    registry.register_plugin_components(
        "mute_plugin",
        [
            {
                "name": "mute",
                "component_type": "TOOL",
                "chat_scope": "group",
                "allowed_session": ["qq:10001"],
                "metadata": {"description": "mute group member"},
            }
        ],
    )
    registry.set_component_enabled("mute_plugin.mute", False, session_id="allowed-session")

    visible_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(
            session_id="visible-session",
            is_group_chat=True,
            group_id="10001",
            platform="qq",
        )
    )
    disabled_specs = service.get_llm_available_tool_specs(
        context=ToolAvailabilityContext(
            session_id="allowed-session",
            is_group_chat=True,
            group_id="10001",
            platform="qq",
        )
    )

    entry = registry.get_component("mute_plugin.mute")
    assert entry is not None
    assert entry.disabled_session == {"allowed-session"}
    assert "mute" in visible_specs
    assert "mute" not in disabled_specs


def test_mute_plugin_exports_allowed_groups_as_component_allowed_session() -> None:
    module_path = "plugins/MutePlugin/plugin.py"
    spec = importlib.util.spec_from_file_location("mute_plugin_under_test", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MutePluginConfig.model_rebuild()

    plugin = module.MutePlugin()
    plugin.set_plugin_config({"permissions": {"allowed_groups": ["qq:10001", "raw-group-id"]}})

    mute_components = [component for component in plugin.get_components() if component.get("name") == "mute"]

    assert len(mute_components) == 1
    assert mute_components[0]["chat_scope"] == "group"
    assert mute_components[0]["allowed_session"] == ["qq:10001", "raw-group-id"]
    assert "allowed_session" not in mute_components[0]["metadata"]


@pytest.mark.asyncio
async def test_mute_tool_queries_target_message_with_current_chat_id() -> None:
    module_path = "plugins/MutePlugin/plugin.py"
    spec = importlib.util.spec_from_file_location("mute_plugin_under_test_msg_id", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MutePluginConfig.model_rebuild()

    capability_calls: list[dict[str, Any]] = []
    api_calls: list[dict[str, Any]] = []

    async def fake_call_capability(name: str, **kwargs: Any) -> dict[str, Any]:
        capability_calls.append({"name": name, **kwargs})
        return {
            "success": True,
            "result": {
                "success": True,
                "message": {
                    "message_info": {
                        "user_info": {
                            "user_id": "35529667",
                            "user_cardname": "目标用户",
                            "user_nickname": "目标昵称",
                        }
                    }
                },
            },
        }

    async def fake_api_call(api_name: str, **kwargs: Any) -> dict[str, Any]:
        api_calls.append({"name": api_name, **kwargs})
        if api_name == "adapter.napcat.group.get_group_member_info":
            return {"success": True, "result": {"data": {"role": "member"}}}
        return {"status": "ok", "retcode": 0}

    plugin = module.MutePlugin()
    plugin.set_plugin_config({"components": {"enable_smart_mute": True}})
    plugin._set_context(
        SimpleNamespace(
            call_capability=fake_call_capability,
            api=SimpleNamespace(call=fake_api_call),
            logger=SimpleNamespace(info=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None),
        )
    )

    success, message = await plugin.handle_mute_tool(
        stream_id="current-session-id",
        group_id="766798517",
        msg_id="2046083292",
        duration=3600,
        reason="测试",
    )

    assert success is True
    assert message == "成功禁言 目标用户"
    assert capability_calls == [
        {
            "name": "message.get_by_id",
            "message_id": "2046083292",
            "chat_id": "current-session-id",
        }
    ]
    assert api_calls[-1] == {
        "name": "adapter.napcat.group.set_group_ban",
        "version": "1",
        "group_id": "766798517",
        "user_id": "35529667",
        "duration": 3600,
    }
