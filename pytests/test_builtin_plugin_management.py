from src.plugin_runtime.host.component_registry import ComponentRegistry
from src.config.official_configs import PluginConfig
from src.plugins.built_in.plugin_management.plugin import (
    _build_scoped_user_id,
    _normalize_permission_list,
    create_plugin,
)


def _build_registry() -> ComponentRegistry:
    registry = ComponentRegistry()
    plugin = create_plugin()
    for component in plugin.get_components():
        registry.register_component(
            component["name"],
            component["type"],
            "builtin.plugin-management",
            component["metadata"],
        )
    return registry


def test_plugin_management_command_matches_plugin_ids_with_symbols() -> None:
    registry = _build_registry()

    assert registry.find_command_by_text("/pm plugin load builtin.plugin-management") is not None
    assert registry.find_command_by_text("/pm plugin reload maibot-team.docs-helper") is not None


def test_plugin_management_command_tolerates_repeated_spaces() -> None:
    registry = _build_registry()

    match = registry.find_command_by_text("/pm   plugin   list")

    assert match is not None
    _component, matched_groups = match
    assert matched_groups["manage_command"] == "/pm   plugin   list"


def test_global_plugin_permission_config_defaults_to_empty_list() -> None:
    config = PluginConfig()

    assert config.permission == []


def test_plugin_management_permission_uses_platform_scoped_user_id() -> None:
    permissions = _normalize_permission_list(["QQ:123456", "telegram:alice"])

    assert _build_scoped_user_id("qq", "123456") in permissions
    assert _build_scoped_user_id("telegram", "alice") in permissions
    assert _build_scoped_user_id("", "123456") == ""
    assert "123456" not in permissions
