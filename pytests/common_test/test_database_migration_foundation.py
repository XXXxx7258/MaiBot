"""数据库迁移基础设施测试。"""

from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlmodel import SQLModel, create_engine

import json
import msgpack
import pytest

from src.common.database import database as database_module
from src.common.database.migrations import (
    BaseSchemaVersionDetector,
    BaseMigrationProgressReporter,
    DatabaseSchemaSnapshot,
    DatabaseMigrationBootstrapper,
    DatabaseMigrationState,
    DatabaseMigrationManager,
    EMPTY_SCHEMA_VERSION,
    LATEST_SCHEMA_VERSION,
    LEGACY_V1_SCHEMA_VERSION,
    MigrationExecutionContext,
    MigrationPlan,
    MigrationRegistry,
    MigrationStep,
    ResolvedSchemaVersion,
    SchemaVersionResolver,
    SchemaVersionSource,
    SQLiteSchemaInspector,
    SQLiteUserVersionStore,
    V4_SCHEMA_VERSION,
    V5_SCHEMA_VERSION,
    build_default_migration_registry,
    build_default_schema_version_resolver,
    create_database_migration_bootstrapper,
)


class FixedVersionDetector(BaseSchemaVersionDetector):
    """测试用固定版本探测器。"""

    @property
    def name(self) -> str:
        """返回测试探测器名称。

        Returns:
            str: 探测器名称。
        """
        return "fixed_version_detector"

    def detect_version(self, snapshot: DatabaseSchemaSnapshot) -> Optional[int]:
        """根据测试表是否存在返回固定版本。

        Args:
            snapshot: 当前数据库结构快照。

        Returns:
            Optional[int]: 若存在测试表则返回固定版本，否则返回 ``None``。
        """
        if snapshot.has_table("legacy_records"):
            return 2
        return None


class FakeMigrationProgressReporter(BaseMigrationProgressReporter):
    """测试用迁移进度上报器。"""

    def __init__(self) -> None:
        """初始化测试用进度上报器。"""
        self.events: List[Tuple[str, Optional[int], Optional[int], Optional[str]]] = []

    def open(self) -> None:
        """记录打开事件。"""
        self.events.append(("open", None, None, None))

    def close(self) -> None:
        """记录关闭事件。"""
        self.events.append(("close", None, None, None))

    def start(
        self,
        total_records: int,
        total_tables: int,
        description: str = "总迁移进度",
        table_unit_name: str = "表",
        record_unit_name: str = "记录",
    ) -> None:
        """记录启动事件。

        Args:
            total_records: 任务记录总数。
            total_tables: 任务表总数。
            description: 任务描述。
            table_unit_name: 表级进度单位名称。
            record_unit_name: 记录级进度单位名称。
        """
        del table_unit_name, record_unit_name
        self.events.append(("start", total_records, total_tables, description))

    def advance(
        self,
        records: int = 0,
        completed_tables: int = 0,
        item_name: Optional[str] = None,
    ) -> None:
        """记录推进事件。

        Args:
            records: 推进的记录数。
            completed_tables: 已完成的表数。
            item_name: 当前完成的项目名称。
        """
        self.events.append(("advance", records, completed_tables, item_name))


def _create_sqlite_engine(database_file: Path) -> Engine:
    """创建测试用 SQLite 引擎。

    Args:
        database_file: 测试数据库文件路径。

    Returns:
        Engine: SQLite 引擎实例。
    """
    return create_engine(
        f"sqlite:///{database_file}",
        echo=False,
        connect_args={"check_same_thread": False},
    )


def _create_current_schema(connection: Connection) -> None:
    """创建当前最新版本的数据库结构。

    Args:
        connection: 当前数据库连接。
    """
    import src.common.database.database_model  # noqa: F401

    SQLModel.metadata.create_all(connection)


def _create_legacy_v1_schema_with_sample_data(connection: Connection) -> None:
    """创建带示例数据的旧版 ``0.x`` 数据库结构。

    Args:
        connection: 当前数据库连接。
    """
    connection.execute(
        text(
            """
            CREATE TABLE chat_streams (
                id INTEGER PRIMARY KEY,
                stream_id TEXT NOT NULL,
                create_time REAL NOT NULL,
                last_active_time REAL NOT NULL,
                platform TEXT NOT NULL,
                user_id TEXT,
                group_id TEXT,
                group_name TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                message_id TEXT NOT NULL,
                time REAL NOT NULL,
                chat_id TEXT NOT NULL,
                chat_info_platform TEXT,
                user_id TEXT,
                user_nickname TEXT,
                chat_info_group_id TEXT,
                chat_info_group_name TEXT,
                is_mentioned INTEGER,
                is_at INTEGER,
                processed_plain_text TEXT,
                display_message TEXT,
                is_emoji INTEGER,
                is_picid INTEGER,
                is_command INTEGER,
                is_notify INTEGER,
                additional_config TEXT,
                priority_mode TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE action_records (
                id INTEGER PRIMARY KEY,
                action_id TEXT NOT NULL,
                time REAL NOT NULL,
                action_reasoning TEXT,
                action_name TEXT NOT NULL,
                action_data TEXT,
                action_prompt_display TEXT,
                chat_id TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE expression (
                id INTEGER PRIMARY KEY,
                situation TEXT NOT NULL,
                style TEXT NOT NULL,
                content_list TEXT,
                count INTEGER,
                last_active_time REAL NOT NULL,
                chat_id TEXT,
                create_date REAL,
                checked INTEGER,
                rejected INTEGER,
                modified_by TEXT
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE jargon (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                raw_content TEXT,
                meaning TEXT,
                chat_id TEXT,
                is_global INTEGER,
                count INTEGER,
                is_jargon INTEGER,
                last_inference_count INTEGER,
                is_complete INTEGER,
                inference_with_context TEXT,
                inference_content_only TEXT
            )
            """
        )
    )

    connection.execute(
        text(
            """
            INSERT INTO chat_streams (
                id,
                stream_id,
                create_time,
                last_active_time,
                platform,
                user_id,
                group_id,
                group_name
            ) VALUES (
                1,
                'session-1',
                1710000000.0,
                1710000300.0,
                'qq',
                'user-1',
                'group-1',
                '测试群'
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO messages (
                id,
                message_id,
                time,
                chat_id,
                chat_info_platform,
                user_id,
                user_nickname,
                chat_info_group_id,
                chat_info_group_name,
                is_mentioned,
                is_at,
                processed_plain_text,
                display_message,
                is_emoji,
                is_picid,
                is_command,
                is_notify,
                additional_config,
                priority_mode
            ) VALUES (
                1,
                'msg-1',
                1710000010.0,
                'session-1',
                'qq',
                'user-1',
                '测试用户',
                'group-1',
                '测试群',
                1,
                0,
                '你好',
                '你好呀',
                0,
                1,
                0,
                1,
                '{"source":"legacy"}',
                'high'
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO action_records (
                id,
                action_id,
                time,
                action_reasoning,
                action_name,
                action_data,
                action_prompt_display,
                chat_id
            ) VALUES (
                1,
                'action-1',
                1710000020.0,
                '需要调用工具',
                'search',
                '{"query":"MaiBot"}',
                '执行搜索',
                'session-1'
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO expression (
                id,
                situation,
                style,
                content_list,
                count,
                last_active_time,
                chat_id,
                create_date,
                checked,
                rejected,
                modified_by
            ) VALUES (
                1,
                '打招呼',
                '可爱',
                '["你好呀","早上好"]',
                3,
                1710000030.0,
                'session-1',
                1710000040.0,
                1,
                0,
                'ai'
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO jargon (
                id,
                content,
                raw_content,
                meaning,
                chat_id,
                is_global,
                count,
                is_jargon,
                last_inference_count,
                is_complete,
                inference_with_context,
                inference_content_only
            ) VALUES (
                1,
                '上分',
                '["上分"]',
                '提高排名',
                'session-1',
                0,
                5,
                1,
                2,
                1,
                '{"guess":"context"}',
                '{"guess":"content"}'
            )
            """
        )
    )


def test_user_version_store_can_read_and_write_versions(tmp_path: Path) -> None:
    """应支持读取与写入 SQLite ``user_version``。"""
    engine = _create_sqlite_engine(tmp_path / "version_store.db")
    version_store = SQLiteUserVersionStore()

    with engine.begin() as connection:
        assert version_store.read_version(connection) == 0
        version_store.write_version(connection, 7)

    with engine.connect() as connection:
        assert version_store.read_version(connection) == 7


def test_schema_inspector_can_extract_tables_and_columns(tmp_path: Path) -> None:
    """应能提取 SQLite 数据库的表与列结构。"""
    engine = _create_sqlite_engine(tmp_path / "schema_inspector.db")
    inspector = SQLiteSchemaInspector()

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE legacy_records (
                    id INTEGER PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT
                )
                """
            )
        )

    with engine.connect() as connection:
        snapshot = inspector.inspect(connection)

    assert snapshot.has_table("legacy_records")
    assert snapshot.has_column("legacy_records", "payload")
    assert not snapshot.has_column("legacy_records", "missing_column")
    table_schema = snapshot.get_table("legacy_records")

    assert table_schema is not None
    assert table_schema.column_names() == ["created_at", "id", "payload"]


def test_resolver_can_identify_empty_database(tmp_path: Path) -> None:
    """空数据库应被解析为版本 ``0``。"""
    engine = _create_sqlite_engine(tmp_path / "empty_resolver.db")
    resolver = SchemaVersionResolver()

    with engine.connect() as connection:
        resolved_version = resolver.resolve(connection)

    assert resolved_version.version == 0
    assert resolved_version.source == SchemaVersionSource.EMPTY_DATABASE
    assert resolved_version.snapshot is not None
    assert resolved_version.snapshot.is_empty()


def test_resolver_can_use_detector_for_unversioned_legacy_database(tmp_path: Path) -> None:
    """未写入 ``user_version`` 的历史库应支持通过探测器识别版本。"""
    engine = _create_sqlite_engine(tmp_path / "legacy_resolver.db")
    resolver = SchemaVersionResolver(detectors=[FixedVersionDetector()])

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE legacy_records (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"))

    with engine.connect() as connection:
        resolved_version = resolver.resolve(connection)

    assert resolved_version.version == 2
    assert resolved_version.source == SchemaVersionSource.DETECTOR
    assert resolved_version.detector_name == "fixed_version_detector"


def test_registry_and_manager_can_execute_registered_steps(tmp_path: Path) -> None:
    """迁移编排器应能按顺序执行已注册步骤并更新版本号。"""
    engine = _create_sqlite_engine(tmp_path / "manager.db")
    executed_steps: List[str] = []

    def migrate_0_to_1(context: MigrationExecutionContext) -> None:
        """测试迁移步骤 0 -> 1。

        Args:
            context: 当前迁移步骤执行上下文。
        """
        executed_steps.append(f"{context.current_version}->{context.target_version}:step_0_to_1")
        context.connection.execute(text("CREATE TABLE sample_records (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))

    def migrate_1_to_2(context: MigrationExecutionContext) -> None:
        """测试迁移步骤 1 -> 2。

        Args:
            context: 当前迁移步骤执行上下文。
        """
        executed_steps.append(f"{context.current_version}->{context.target_version}:step_1_to_2")
        context.connection.execute(text("ALTER TABLE sample_records ADD COLUMN email TEXT"))

    registry = MigrationRegistry(
        steps=[
            MigrationStep(
                version_from=0,
                version_to=1,
                name="create_sample_records",
                description="创建示例表。",
                handler=migrate_0_to_1,
            ),
            MigrationStep(
                version_from=1,
                version_to=2,
                name="add_sample_email",
                description="为示例表增加邮箱字段。",
                handler=migrate_1_to_2,
            ),
        ]
    )
    manager = DatabaseMigrationManager(engine=engine, registry=registry)

    migration_plan = manager.migrate()

    assert migration_plan.step_count() == 2
    assert executed_steps == ["0->2:step_0_to_1", "1->2:step_1_to_2"]

    with engine.connect() as connection:
        version_store = SQLiteUserVersionStore()
        snapshot = SQLiteSchemaInspector().inspect(connection)
        recorded_version = version_store.read_version(connection)

    assert recorded_version == 2
    assert snapshot.has_table("sample_records")
    assert snapshot.has_column("sample_records", "email")


def test_manager_can_report_step_progress(tmp_path: Path) -> None:
    """迁移编排器应支持通过上下文上报步骤进度。"""
    engine = _create_sqlite_engine(tmp_path / "manager_progress.db")
    reporter_instances: List[FakeMigrationProgressReporter] = []

    def _build_reporter() -> BaseMigrationProgressReporter:
        """构建测试用进度上报器。

        Returns:
            BaseMigrationProgressReporter: 测试用进度上报器实例。
        """
        reporter = FakeMigrationProgressReporter()
        reporter_instances.append(reporter)
        return reporter

    def migrate_1_to_2(context: MigrationExecutionContext) -> None:
        """测试迁移步骤 ``1 -> 2`` 的进度上报。

        Args:
            context: 当前迁移步骤执行上下文。
        """
        context.start_progress(total_tables=3, total_records=30, description="总迁移进度")
        context.advance_progress(records=10, completed_tables=1, item_name="chat_sessions")
        context.advance_progress(records=10, completed_tables=1, item_name="mai_messages")
        context.advance_progress(records=10, completed_tables=1, item_name="tool_records")
        context.connection.execute(text("CREATE TABLE progress_records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"))

    with engine.begin() as connection:
        SQLiteUserVersionStore().write_version(connection, 1)

    registry = MigrationRegistry(
        steps=[
            MigrationStep(
                version_from=1,
                version_to=2,
                name="progress_step",
                description="测试进度上报。",
                handler=migrate_1_to_2,
            )
        ]
    )
    manager = DatabaseMigrationManager(
        engine=engine,
        registry=registry,
        progress_reporter_factory=_build_reporter,
    )

    migration_plan = manager.migrate()

    assert migration_plan.step_count() == 1
    assert len(reporter_instances) == 1
    assert reporter_instances[0].events == [
        ("open", None, None, None),
        ("start", 30, 3, "总迁移进度"),
        ("advance", 10, 1, "chat_sessions"),
        ("advance", 10, 1, "mai_messages"),
        ("advance", 10, 1, "tool_records"),
        ("close", None, None, None),
    ]


def test_default_resolver_can_identify_unversioned_latest_database(tmp_path: Path) -> None:
    """默认解析器应能识别未写入版本号的最新结构数据库。"""
    engine = _create_sqlite_engine(tmp_path / "latest_resolver.db")
    resolver = build_default_schema_version_resolver()

    with engine.begin() as connection:
        _create_current_schema(connection)

    with engine.connect() as connection:
        resolved_version = resolver.resolve(connection)

    assert resolved_version.version == LATEST_SCHEMA_VERSION
    assert resolved_version.source == SchemaVersionSource.DETECTOR
    assert resolved_version.detector_name == "latest_schema_detector"


def test_default_resolver_can_identify_legacy_v1_database(tmp_path: Path) -> None:
    """默认解析器应能识别未写版本号的旧版 ``0.x`` 数据库。"""
    engine = _create_sqlite_engine(tmp_path / "legacy_v1_resolver.db")
    resolver = build_default_schema_version_resolver()

    with engine.begin() as connection:
        _create_legacy_v1_schema_with_sample_data(connection)

    with engine.connect() as connection:
        resolved_version = resolver.resolve(connection)

    assert resolved_version.version == LEGACY_V1_SCHEMA_VERSION
    assert resolved_version.source == SchemaVersionSource.DETECTOR
    assert resolved_version.detector_name == "legacy_v1_schema_detector"


def test_bootstrapper_can_finalize_unversioned_latest_database(tmp_path: Path) -> None:
    """已是最新结构但未写版本号的数据库应直接补写 ``user_version``。"""
    engine = _create_sqlite_engine(tmp_path / "latest_finalize.db")
    bootstrapper = create_database_migration_bootstrapper(engine)

    with engine.begin() as connection:
        _create_current_schema(connection)

    migration_state = bootstrapper.prepare_database()
    bootstrapper.finalize_database(migration_state)

    assert not migration_state.requires_migration()
    assert migration_state.resolved_version.version == LATEST_SCHEMA_VERSION
    assert migration_state.resolved_version.source == SchemaVersionSource.DETECTOR

    with engine.connect() as connection:
        recorded_version = SQLiteUserVersionStore().read_version(connection)

    assert recorded_version == LATEST_SCHEMA_VERSION


def test_bootstrapper_can_finalize_empty_database_to_latest_version(tmp_path: Path) -> None:
    """空库在建表完成后应回写最新 ``user_version``。"""
    engine = _create_sqlite_engine(tmp_path / "bootstrap_empty.db")
    bootstrapper = create_database_migration_bootstrapper(engine)

    migration_state = bootstrapper.prepare_database()

    assert not migration_state.requires_migration()
    assert migration_state.resolved_version.version == EMPTY_SCHEMA_VERSION
    assert migration_state.target_version == LATEST_SCHEMA_VERSION

    with engine.begin() as connection:
        _create_current_schema(connection)

    bootstrapper.finalize_database(migration_state)

    with engine.connect() as connection:
        recorded_version = SQLiteUserVersionStore().read_version(connection)

    assert recorded_version == LATEST_SCHEMA_VERSION


def test_bootstrapper_runs_registered_steps_for_versioned_database(tmp_path: Path) -> None:
    """启动桥接器应在已登记旧版本数据库上执行注册迁移步骤。"""
    engine = _create_sqlite_engine(tmp_path / "bootstrap_registered.db")
    execution_marks: List[str] = []

    def migrate_1_to_2(context: MigrationExecutionContext) -> None:
        """测试桥接器迁移步骤 ``1 -> 2``。

        Args:
            context: 当前迁移步骤执行上下文。
        """
        execution_marks.append(f"step={context.step_name},index={context.step_index}")
        context.connection.execute(text("ALTER TABLE bootstrap_records ADD COLUMN email TEXT"))

    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE bootstrap_records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        )
        SQLiteUserVersionStore().write_version(connection, 1)

    registry = MigrationRegistry(
        steps=[
            MigrationStep(
                version_from=1,
                version_to=2,
                name="bootstrap_add_email",
                description="为桥接器测试表增加邮箱字段。",
                handler=migrate_1_to_2,
            )
        ]
    )
    bootstrapper = DatabaseMigrationBootstrapper(
        manager=DatabaseMigrationManager(engine=engine, registry=registry),
        latest_schema_version=2,
    )

    migration_state = bootstrapper.prepare_database()

    assert migration_state.resolved_version.version == 2
    assert migration_state.target_version == 2
    assert execution_marks == ["step=bootstrap_add_email,index=1"]

    with engine.connect() as connection:
        snapshot = SQLiteSchemaInspector().inspect(connection)
        recorded_version = SQLiteUserVersionStore().read_version(connection)

    assert recorded_version == 2
    assert snapshot.has_table("bootstrap_records")
    assert snapshot.has_column("bootstrap_records", "email")


def test_default_bootstrapper_clears_group_session_user_id_from_v4_database(tmp_path: Path) -> None:
    """v4 -> v5 迁移应清空群聊会话中无归属语义的 ``user_id``。"""

    engine = _create_sqlite_engine(tmp_path / "v4_to_v5.db")
    bootstrapper = create_database_migration_bootstrapper(engine)

    with engine.begin() as connection:
        _create_current_schema(connection)
        connection.execute(
            text(
                """
                INSERT INTO chat_sessions (
                    session_id,
                    created_timestamp,
                    last_active_timestamp,
                    user_id,
                    group_id,
                    platform
                ) VALUES
                    ('group-session', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'first-user', 'group-1', 'qq'),
                    ('private-session', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'private-user', NULL, 'qq')
                """
            )
        )
        SQLiteUserVersionStore().write_version(connection, V4_SCHEMA_VERSION)

    migration_state = bootstrapper.prepare_database()

    assert migration_state.resolved_version.version == LATEST_SCHEMA_VERSION

    with engine.connect() as connection:
        rows = {
            row["session_id"]: row["user_id"]
            for row in connection.execute(
                text(
                    """
                    SELECT session_id, user_id
                    FROM chat_sessions
                    ORDER BY session_id
                    """
                )
            ).mappings()
        }
        recorded_version = SQLiteUserVersionStore().read_version(connection)

    assert recorded_version == LATEST_SCHEMA_VERSION
    assert rows["group-session"] is None
    assert rows["private-session"] == "private-user"


def test_default_bootstrapper_adds_chat_session_route_columns_from_v5_database(tmp_path: Path) -> None:
    """v5 -> v6 迁移应添加路由字段，历史数据默认保持为空。"""

    engine = _create_sqlite_engine(tmp_path / "v5_to_v6.db")
    bootstrapper = create_database_migration_bootstrapper(engine)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE chat_sessions (
                    id INTEGER NOT NULL,
                    session_id VARCHAR(255) NOT NULL,
                    created_timestamp DATETIME,
                    last_active_timestamp DATETIME,
                    user_id VARCHAR(255),
                    group_id VARCHAR(255),
                    platform VARCHAR(100) NOT NULL,
                    PRIMARY KEY (id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO chat_sessions (
                    id,
                    session_id,
                    created_timestamp,
                    last_active_timestamp,
                    user_id,
                    group_id,
                    platform
                ) VALUES (
                    1,
                    'group-session',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP,
                    NULL,
                    'group-1',
                    'qq'
                )
                """
            )
        )
        SQLiteUserVersionStore().write_version(connection, V5_SCHEMA_VERSION)

    migration_state = bootstrapper.prepare_database()

    assert migration_state.resolved_version.version == LATEST_SCHEMA_VERSION

    with engine.connect() as connection:
        snapshot = SQLiteSchemaInspector().inspect(connection)
        row = connection.execute(
            text(
                """
                SELECT account_id, scope
                FROM chat_sessions
                WHERE session_id = 'group-session'
                """
            )
        ).mappings().one()
        recorded_version = SQLiteUserVersionStore().read_version(connection)

    assert recorded_version == LATEST_SCHEMA_VERSION
    assert snapshot.has_column("chat_sessions", "account_id")
    assert snapshot.has_column("chat_sessions", "scope")
    assert row["account_id"] is None
    assert row["scope"] is None


def test_default_bootstrapper_can_migrate_legacy_v1_database(tmp_path: Path) -> None:
    """默认桥接器应能把旧版 ``0.x`` 数据库整体迁移到最新结构。"""
    engine = _create_sqlite_engine(tmp_path / "legacy_v1_to_v2.db")
    bootstrapper = create_database_migration_bootstrapper(engine)

    with engine.begin() as connection:
        _create_legacy_v1_schema_with_sample_data(connection)

    migration_state = bootstrapper.prepare_database()
    bootstrapper.finalize_database(migration_state)

    assert not migration_state.requires_migration()
    assert migration_state.resolved_version.version == LATEST_SCHEMA_VERSION
    assert migration_state.resolved_version.source == SchemaVersionSource.PRAGMA

    with engine.connect() as connection:
        recorded_version = SQLiteUserVersionStore().read_version(connection)
        snapshot = SQLiteSchemaInspector().inspect(connection)
        message_row = connection.execute(
            text(
                """
                SELECT session_id, processed_plain_text, additional_config, raw_content
                FROM mai_messages
                WHERE message_id = 'msg-1'
                """
            )
        ).mappings().one()
        tool_row = connection.execute(
            text(
                """
                SELECT session_id, tool_name, tool_display_prompt
                FROM tool_records
                WHERE tool_id = 'action-1'
                """
            )
        ).mappings().one()
        expression_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM expressions
                """
            )
        ).scalar_one()
        jargon_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM jargons
                """
            )
        ).scalar_one()
        chat_session_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM chat_sessions
                """
            )
        ).scalar_one()

    assert recorded_version == LATEST_SCHEMA_VERSION
    assert snapshot.has_table("__legacy_v1_messages")
    assert snapshot.has_table("chat_sessions")
    assert snapshot.has_table("mai_messages")
    assert snapshot.has_table("tool_records")
    assert not snapshot.has_table("action_records")
    assert not snapshot.has_column("mai_messages", "display_message")

    unpacked_raw_content = msgpack.unpackb(message_row["raw_content"], raw=False)
    additional_config = json.loads(message_row["additional_config"])
    assert message_row["session_id"] == "session-1"
    assert message_row["processed_plain_text"] == "你好"
    assert unpacked_raw_content == [{"type": "text", "data": "你好呀"}]
    assert additional_config == {"priority_mode": "high", "source": "legacy"}
    assert tool_row["session_id"] == "session-1"
    assert tool_row["tool_name"] == "search"
    assert tool_row["tool_display_prompt"] == "执行搜索"
    assert expression_count == 0
    assert jargon_count == 0
    assert chat_session_count == 0


def test_legacy_v1_migration_reports_table_progress(tmp_path: Path) -> None:
    """旧版迁移步骤应按目标表数量推进总进度。"""
    engine = _create_sqlite_engine(tmp_path / "legacy_progress.db")
    reporter_instances: List[FakeMigrationProgressReporter] = []

    def _build_reporter() -> BaseMigrationProgressReporter:
        """构建测试用进度上报器。

        Returns:
            BaseMigrationProgressReporter: 测试用进度上报器实例。
        """
        reporter = FakeMigrationProgressReporter()
        reporter_instances.append(reporter)
        return reporter

    with engine.begin() as connection:
        _create_legacy_v1_schema_with_sample_data(connection)

    manager = DatabaseMigrationManager(
        engine=engine,
        registry=build_default_migration_registry(),
        resolver=build_default_schema_version_resolver(),
        progress_reporter_factory=_build_reporter,
    )

    migration_plan = manager.migrate(target_version=LATEST_SCHEMA_VERSION)

    assert migration_plan.step_count() == 5
    assert len(reporter_instances) == 5
    reporter_events = reporter_instances[0].events

    assert reporter_events[0] == ("open", None, None, None)
    assert reporter_events[1] == ("start", 3, 11, "总迁移进度")
    assert reporter_events[-1] == ("close", None, None, None)
    assert reporter_events.count(("advance", 1, 0, None)) == 3
    assert reporter_events.count(("advance", 0, 1, "chat_sessions")) == 0
    assert reporter_events.count(("advance", 0, 1, "thinking_questions")) == 1
    assert len([event for event in reporter_events if event[0] == "advance"]) == 14


def test_initialize_database_calls_bootstrapper_before_create_all(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """数据库初始化入口应先准备迁移，再建表、补迁移并收尾。"""
    call_order: List[str] = []

    def _fake_prepare_database() -> DatabaseMigrationState:
        """返回测试用迁移状态。

        Returns:
            DatabaseMigrationState: 不包含迁移步骤的测试状态。
        """
        call_order.append("prepare_database")
        return DatabaseMigrationState(
            resolved_version=ResolvedSchemaVersion(version=0, source=SchemaVersionSource.EMPTY_DATABASE),
            target_version=LATEST_SCHEMA_VERSION,
            plan=MigrationPlan(
                current_version=EMPTY_SCHEMA_VERSION,
                target_version=LATEST_SCHEMA_VERSION,
                steps=[],
            ),
        )

    def _fake_create_all(bind) -> None:
        """记录建表调用。

        Args:
            bind: 传入的数据库绑定对象。
        """
        del bind
        call_order.append("create_all")

    def _fake_finalize_database(migration_state: DatabaseMigrationState) -> None:
        """记录迁移收尾调用。

        Args:
            migration_state: 当前数据库迁移状态。
        """
        del migration_state
        call_order.append("finalize_database")

    monkeypatch.setattr(database_module, "_db_initialized", False)
    monkeypatch.setattr(database_module, "_DB_DIR", tmp_path / "data")
    monkeypatch.setattr(database_module._migration_bootstrapper, "prepare_database", _fake_prepare_database)
    monkeypatch.setattr(database_module._migration_bootstrapper, "finalize_database", _fake_finalize_database)
    monkeypatch.setattr(database_module.SQLModel.metadata, "create_all", _fake_create_all)

    database_module.initialize_database()

    assert call_order == [
        "prepare_database",
        "create_all",
        "finalize_database",
    ]
