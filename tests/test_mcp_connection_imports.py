from pathlib import Path
from types import ModuleType, SimpleNamespace

import importlib
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _drop_mcp_connection_modules() -> None:
    for module_name in ("src.mcp_module.connection", "src.mcp_module.manager"):
        sys.modules.pop(module_name, None)


def _build_fake_mcp_modules(monkeypatch, streamable_http_module: ModuleType) -> None:
    mcp_module = ModuleType("mcp")
    mcp_module.ClientSession = object
    mcp_module.types = SimpleNamespace(METHOD_NOT_FOUND="METHOD_NOT_FOUND")

    client_module = ModuleType("mcp.client")
    client_module.__path__ = []

    shared_module = ModuleType("mcp.shared")
    shared_module.__path__ = []

    stdio_module = ModuleType("mcp.client.stdio")
    stdio_module.StdioServerParameters = object

    exceptions_module = ModuleType("mcp.shared.exceptions")
    exceptions_module.McpError = Exception

    stdio_filter_module = ModuleType("src.mcp_module.stdio_filter")
    stdio_filter_module.tolerant_stdio_client = object()

    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.client", client_module)
    monkeypatch.setitem(sys.modules, "mcp.client.stdio", stdio_module)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", streamable_http_module)
    monkeypatch.setitem(sys.modules, "mcp.shared", shared_module)
    monkeypatch.setitem(sys.modules, "mcp.shared.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "src.mcp_module.stdio_filter", stdio_filter_module)


def _import_connection_with_fake_mcp(monkeypatch, streamable_http_module: ModuleType) -> ModuleType:
    _drop_mcp_connection_modules()
    _build_fake_mcp_modules(monkeypatch, streamable_http_module)
    return importlib.import_module("src.mcp_module.connection")


def test_mcp_available_when_only_legacy_streamable_http_client_exists(monkeypatch) -> None:
    def legacy_streamable_http_client(*args, **kwargs):
        return None

    streamable_http_module = ModuleType("mcp.client.streamable_http")
    streamable_http_module.streamablehttp_client = legacy_streamable_http_client

    try:
        connection = _import_connection_with_fake_mcp(monkeypatch, streamable_http_module)

        assert connection.MCP_AVAILABLE is True
        assert connection.STREAMABLE_HTTP_AVAILABLE is True
        assert connection.STREAMABLE_HTTP_USES_LEGACY_CLIENT is True
        assert connection.streamable_http_client is legacy_streamable_http_client
    finally:
        _drop_mcp_connection_modules()


def test_mcp_available_when_streamable_http_client_is_missing(monkeypatch) -> None:
    streamable_http_module = ModuleType("mcp.client.streamable_http")

    try:
        connection = _import_connection_with_fake_mcp(monkeypatch, streamable_http_module)

        assert connection.MCP_AVAILABLE is True
        assert connection.STREAMABLE_HTTP_AVAILABLE is False
        assert connection.streamable_http_client is None
    finally:
        _drop_mcp_connection_modules()
