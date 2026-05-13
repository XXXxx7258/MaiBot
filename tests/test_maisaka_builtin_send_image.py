from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.data_models.message_component_data_model import ImageComponent, MessageSequence, TextComponent
from src.core.tooling import ToolInvocation
from src.maisaka.builtin_tool.context import BuiltinToolRuntimeContext
from src.maisaka.builtin_tool.send_image import handle_tool
from src.maisaka.context_messages import SessionBackedMessage


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_send_image_can_use_tool_result_media_index(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_image_to_stream(**kwargs: object) -> bool:
        captured.update(kwargs)
        return True

    monkeypatch.setattr("src.maisaka.builtin_tool.send_image.send_service.image_to_stream", fake_image_to_stream)

    media_index = "tool_result:call_1:1"
    runtime = SimpleNamespace(
        session_id="session-1",
        log_prefix="[test]",
        _chat_history=[
            SessionBackedMessage(
                raw_message=MessageSequence(
                    [
                        TextComponent(f"[工具返回媒体]索引={media_index}"),
                        ImageComponent(binary_hash="", binary_data=PNG_1X1),
                    ]
                ),
                visible_text=f"[工具返回媒体]索引={media_index}",
                timestamp=datetime.now(),
                message_id=media_index,
                source_kind="tool_result_media",
            )
        ],
        find_source_message_by_id=lambda _message_id: None,
    )
    tool_ctx = BuiltinToolRuntimeContext(engine=SimpleNamespace(), runtime=runtime)

    result = await handle_tool(
        tool_ctx,
        ToolInvocation(
            tool_name="better_image_send_context",
            arguments={"media_index": media_index},
        ),
    )

    assert result.success is True
    assert captured["stream_id"] == "session-1"
    assert captured["sync_to_maisaka_history"] is True
    assert captured["image_base64"]
