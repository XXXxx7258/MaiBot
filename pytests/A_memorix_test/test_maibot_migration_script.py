from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_migration_module():
    script_dir = Path(__file__).resolve().parents[2] / "src" / "A_memorix" / "scripts"
    script_path = script_dir / "migrate_maibot_memory.py"
    script_dir_text = str(script_dir)
    if script_dir_text not in sys.path:
        sys.path.insert(0, script_dir_text)
    spec = importlib.util.spec_from_file_location("maibot_migration_script_test_module", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.compute_hash = lambda text: f"hash:{text}"
    module.normalize_text = lambda text: " ".join(str(text).split())
    return module


class _FakeVectorStore:
    def __contains__(self, value: str) -> bool:
        del value
        return False


class _Row(dict):
    def __getitem__(self, key: str):
        return dict.__getitem__(self, key)


def test_parse_list_field_accepts_legacy_dirty_values(tmp_path: Path) -> None:
    module = _load_migration_module()
    runner = module.MigrationRunner(
        SimpleNamespace(source_db=str(tmp_path / "source.db"), target_data_dir=str(tmp_path / "target"))
    )

    assert runner._parse_json_list_field("", "participants", 1) == []
    assert runner._parse_json_list_field("['Alice', 'Bob']", "participants", 1) == ["Alice", "Bob"]
    assert runner._parse_json_list_field('{"name": "Alice"}', "participants", 1) == ["Alice"]
    assert runner._parse_json_list_field("Alice,Bob", "participants", 1) == ["Alice", "Bob"]
    assert runner.stats["coerced_list_fields"] >= 3


def test_current_schema_is_aliased_for_preview_and_rows(tmp_path: Path) -> None:
    module = _load_migration_module()
    db_path = tmp_path / "current.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE chat_history (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            start_timestamp TEXT,
            end_timestamp TEXT,
            query_count INTEGER NOT NULL,
            query_forget_count INTEGER NOT NULL,
            original_messages TEXT NOT NULL,
            participants TEXT NOT NULL,
            theme TEXT NOT NULL,
            keywords TEXT NOT NULL,
            summary TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE chat_sessions (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            group_id TEXT,
            user_id TEXT,
            platform TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO chat_history
        (id, session_id, start_timestamp, end_timestamp, query_count, query_forget_count,
         original_messages, participants, theme, keywords, summary)
        VALUES (1, 'session-1', '2026-04-01 12:00:00', '2026-04-01 12:05:00',
                0, 0, 'original', '["Alice"]', '计划', '地图,咖啡', '讨论周末计划')
        """
    )
    conn.execute(
        "INSERT INTO chat_sessions (id, session_id, group_id, user_id, platform) VALUES (1, 'session-1', 'group-1', 'user-1', 'qq')"
    )
    conn.commit()
    conn.close()

    source = module.SourceDB(db_path)
    source.connect()
    try:
        stream_ids = source.resolve_stream_ids([], ["group-1"], [])
        assert stream_ids == ["session-1"]

        selection = module.SelectionFilter(None, None, stream_ids, True, None, None, None, None)
        preview = source.preview(selection, preview_limit=1)
        assert preview.total == 1
        assert preview.samples[0]["chat_id"] == "session-1"

        rows = next(source.iter_rows(selection, batch_size=10, start_after_id=0))
        runner = module.MigrationRunner(
            SimpleNamespace(source_db=str(db_path), target_data_dir=str(tmp_path / "target"))
        )
        runner.vector_store = _FakeVectorStore()
        mapped = runner._map_row(rows[0])
        assert mapped.chat_id == "session-1"
        assert mapped.time_meta["event_time_start"] > 0
        assert "Alice" in mapped.entities
        assert "地图" in mapped.entities
    finally:
        source.close()


def test_max_errors_defaults_to_no_abort() -> None:
    module = _load_migration_module()

    args = module.build_parser().parse_args([])

    assert args.max_errors == 0


def test_same_content_from_different_streams_keeps_same_hash_for_idempotency(tmp_path: Path) -> None:
    module = _load_migration_module()
    runner = module.MigrationRunner(
        SimpleNamespace(source_db=str(tmp_path / "source.db"), target_data_dir=str(tmp_path / "target"))
    )
    runner.vector_store = _FakeVectorStore()
    base = {
        "start_time": 1700000000,
        "end_time": 1700000100,
        "participants": '["Alice"]',
        "theme": "同一主题",
        "keywords": '["k"]',
        "summary": "同一摘要",
    }

    row1 = _Row(id=1, chat_id="stream-a", **base)
    row2 = _Row(id=2, chat_id="stream-b", start_time=1800000000, end_time=1800000100, **{k: v for k, v in base.items() if k not in {"start_time", "end_time"}})

    assert runner._map_row(row1).paragraph_hash == runner._map_row(row2).paragraph_hash
