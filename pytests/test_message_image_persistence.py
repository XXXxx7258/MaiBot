from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

import base64
import hashlib

from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, Session, create_engine, select

from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.common.data_models.message_component_data_model import ImageComponent, MessageSequence
from src.common.database.database_model import Images, ImageType
from src.common.utils.utils_message import MessageUtils
from src.plugin_runtime.host.message_utils import PluginMessageUtils


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def test_store_message_to_db_persists_outbound_image_binary(monkeypatch, tmp_path: Path) -> None:
    image_hash = hashlib.sha256(PNG_BYTES).hexdigest()
    cached_image_path = Path("data") / "images" / f"{image_hash}.png"
    cached_image_existed = cached_image_path.exists()

    engine = create_engine(
        f"sqlite:///{tmp_path / 'maibot.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)

    @contextmanager
    def get_test_db_session(auto_commit: bool = True) -> Generator[Session, None, None]:
        session = session_local()
        try:
            yield session
            if auto_commit:
                session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    import src.common.database.database as database_module
    import src.common.message_repository as message_repository

    monkeypatch.setattr(database_module, "get_db_session", get_test_db_session)
    monkeypatch.setattr(message_repository, "get_db_session", get_test_db_session)
    monkeypatch.setattr(database_module, "initialize_database", lambda: None)

    message = SessionMessage(
        message_id="-85525752",
        timestamp=datetime(2026, 5, 14, 18, 0, 0),
        platform="qq",
    )
    message.message_info = MessageInfo(
        user_info=UserInfo(user_id="bot-qq", user_nickname="MaiSaka"),
        group_info=None,
        additional_config={},
    )
    image_component = ImageComponent(binary_hash="", binary_data=PNG_BYTES, content="")
    message.raw_message = MessageSequence([image_component])
    message.session_id = "test-session"
    message.processed_plain_text = ""

    try:
        MessageUtils.store_message_to_db(message)

        with get_test_db_session(auto_commit=False) as session:
            image_record = session.exec(
                select(Images).filter_by(image_hash=image_component.binary_hash, image_type=ImageType.IMAGE).limit(1)
            ).first()

        assert image_record is not None
        assert Path(image_record.full_path).read_bytes() == PNG_BYTES

        from src.services import message_service

        stored_message = message_service.get_message_by_id("-85525752", chat_id="test-session")
        assert stored_message is not None

        serialized = PluginMessageUtils._session_message_to_dict(stored_message, include_binary_data=True)
        raw_message = serialized["raw_message"]
        assert raw_message[0]["type"] == "image"
        assert base64.b64decode(raw_message[0]["binary_data_base64"]) == PNG_BYTES
    finally:
        if not cached_image_existed and cached_image_path.exists():
            cached_image_path.unlink()
