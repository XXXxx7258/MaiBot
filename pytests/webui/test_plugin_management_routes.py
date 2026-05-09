import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.webui.routers.plugin import management as management_module
from src.webui.routers.plugin import support as support_module


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    demo_dir = plugins_dir / "demo_plugin"
    demo_dir.mkdir()
    (demo_dir / "_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 2,
                "id": "test.demo",
                "name": "Demo Plugin",
                "version": "1.0.0",
                "description": "demo plugin",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(management_module, "require_plugin_token", lambda _: "ok")
    monkeypatch.setattr(support_module, "get_plugins_dir", lambda: plugins_dir)

    app = FastAPI()
    app.include_router(management_module.router, prefix="/api/webui/plugins")
    return TestClient(app)


def test_installed_plugins_only_scan_plugins_dir_and_exclude_a_memorix(client: TestClient):
    response = client.get("/api/webui/plugins/installed")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True

    ids = [plugin["id"] for plugin in payload["plugins"]]
    assert ids == ["test.demo"]
    assert "a-dawn.a-memorix" not in ids
    assert all("/src/plugins/built_in/" not in plugin["path"] for plugin in payload["plugins"])


def test_resolve_installed_plugin_path_falls_back_to_manifest_id(client: TestClient):
    plugin_path = support_module.resolve_installed_plugin_path("test.demo")

    assert plugin_path is not None
    assert plugin_path.name == "demo_plugin"


def test_resolve_installed_plugin_path_accepts_manifest_id_case_mismatch(client: TestClient):
    plugin_path = support_module.resolve_installed_plugin_path("Test.Demo")

    assert plugin_path is not None
    assert plugin_path.name == "demo_plugin"


def test_install_plugin_preserves_manifest_declared_id(client: TestClient, monkeypatch):
    class FakeGitMirrorService:
        async def clone_repository(self, **kwargs):
            target_path = kwargs["target_path"]
            target_path.mkdir(parents=True, exist_ok=True)
            (target_path / "_manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": 2,
                        "id": "author.declared",
                        "name": "Declared Plugin",
                        "version": "1.0.0",
                        "author": {"name": "author"},
                    }
                ),
                encoding="utf-8",
            )
            return {"success": True}

    monkeypatch.setattr(management_module, "get_git_mirror_service", lambda: FakeGitMirrorService())

    response = client.post(
        "/api/webui/plugins/install",
        json={
            "plugin_id": "market.plugin",
            "repository_url": "https://github.com/author/declared",
            "branch": "main",
        },
    )

    assert response.status_code == 200
    plugin_path = support_module.resolve_installed_plugin_path("author.declared")
    assert plugin_path is not None
    manifest = json.loads((plugin_path / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "author.declared"


def test_install_plugin_backfills_missing_manifest_id(client: TestClient, monkeypatch):
    class FakeGitMirrorService:
        async def clone_repository(self, **kwargs):
            target_path = kwargs["target_path"]
            target_path.mkdir(parents=True, exist_ok=True)
            (target_path / "_manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": 2,
                        "name": "Legacy Plugin",
                        "version": "1.0.0",
                        "author": {"name": "author"},
                    }
                ),
                encoding="utf-8",
            )
            return {"success": True}

    monkeypatch.setattr(management_module, "get_git_mirror_service", lambda: FakeGitMirrorService())

    response = client.post(
        "/api/webui/plugins/install",
        json={
            "plugin_id": "market.legacy",
            "repository_url": "https://github.com/author/legacy",
            "branch": "main",
        },
    )

    assert response.status_code == 200
    plugin_path = support_module.resolve_installed_plugin_path("market.legacy")
    assert plugin_path is not None
    manifest = json.loads((plugin_path / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "market.legacy"
