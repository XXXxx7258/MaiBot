from src.common.data_models.message_component_data_model import (
    ImageComponent,
    MessageSequence,
    ReplyComponent,
    TextComponent,
)
from src.llm_models.payload_content.message import RoleType
from src.maisaka.context_messages import _build_message_from_sequence
from src.maisaka.message_adapter import build_visible_text_from_sequence


def test_image_only_message_keeps_placeholder_in_text_fallback() -> None:
    message_sequence = MessageSequence(
        [
            TextComponent('<message msg_id="1385025976" time="19:21:20" user="William730">\n'),
            ImageComponent(binary_hash="hash", content=None, binary_data=None),
        ]
    )

    message = _build_message_from_sequence(
        RoleType.User,
        message_sequence,
        '<message msg_id="1385025976" time="19:21:20" user="William730">\n[图片]',
    )

    assert message is not None
    assert '<message msg_id="1385025976" time="19:21:20" user="William730">' in message.get_text_content()
    assert "[图片，识别中.....]" in message.get_text_content()


def test_whitespace_image_content_uses_placeholder_in_text_fallback() -> None:
    message_sequence = MessageSequence(
        [
            TextComponent("[发言内容]"),
            ImageComponent(binary_hash="hash", content="   ", binary_data=None),
        ]
    )

    message = _build_message_from_sequence(
        RoleType.User,
        message_sequence,
        "[发言内容][图片]",
        enable_visual_message=False,
    )

    assert message is not None
    assert message.get_text_content() == "[发言内容][图片，识别中.....]"


def test_visible_text_uses_image_placeholder_for_whitespace_content() -> None:
    visible_text = build_visible_text_from_sequence(
        MessageSequence(
            [
                TextComponent("看这个"),
                ImageComponent(binary_hash="hash", content="   ", binary_data=None),
            ]
        )
    )

    assert visible_text == "看这个[图片，识别中.....]"


def test_visible_text_adds_body_marker_after_reply_component() -> None:
    visible_text = build_visible_text_from_sequence(
        MessageSequence(
            [
                ReplyComponent(target_message_id="75625487"),
                TextComponent("你说是那就是"),
            ]
        )
    )

    assert visible_text == "[引用消息]75625487\n[发言内容]你说是那就是"
