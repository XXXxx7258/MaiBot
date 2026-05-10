from base64 import b64encode
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.data_models.message_component_data_model import ImageComponent
from src.core.tooling import ToolContentItem, ToolExecutionResult
from src.llm_models.payload_content.tool_option import ToolCall
from src.maisaka.context_messages import AssistantMessage, SessionBackedMessage, ToolResultMessage
from src.maisaka.history_utils import drop_orphan_tool_results
from src.maisaka.reasoning_engine import MaisakaReasoningEngine


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff"
    b"\xff?\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_tool_result_image_item_is_split_into_tool_and_user_messages() -> None:
    engine = MaisakaReasoningEngine.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_chat_history=[])
    tool_call = ToolCall(call_id="call_1", func_name="plugin_image", args={})
    result = ToolExecutionResult(
        tool_name="plugin_image",
        success=True,
        content="生成完成",
        content_items=[
            ToolContentItem(
                content_type="image",
                data=b64encode(PNG_1X1).decode("ascii"),
                mime_type="image/png",
                name="out.png",
            )
        ],
    )

    engine._append_tool_execution_result(tool_call, result)

    assert len(engine._runtime._chat_history) == 2
    tool_result = engine._runtime._chat_history[0]
    media_message = engine._runtime._chat_history[1]
    assert isinstance(tool_result, ToolResultMessage)
    assert "tool_result:call_1:1" in tool_result.content
    assert isinstance(media_message, SessionBackedMessage)
    assert media_message.source_kind == "tool_result_media"
    assert any(isinstance(component, ImageComponent) for component in media_message.raw_message.components)


def test_orphan_tool_result_media_message_is_dropped_with_orphan_tool_result() -> None:
    engine = MaisakaReasoningEngine.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_chat_history=[])
    tool_call = ToolCall(call_id="call_1", func_name="plugin_image", args={})
    result = ToolExecutionResult(
        tool_name="plugin_image",
        success=True,
        content_items=[
            ToolContentItem(
                content_type="image",
                data=b64encode(PNG_1X1).decode("ascii"),
                mime_type="image/png",
            )
        ],
    )
    engine._append_tool_execution_result(tool_call, result)

    filtered_history, removed_count = drop_orphan_tool_results(engine._runtime._chat_history)

    assert filtered_history == []
    assert removed_count == 2


def test_tool_result_media_message_is_kept_when_tool_call_exists() -> None:
    engine = MaisakaReasoningEngine.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_chat_history=[])
    tool_call = ToolCall(call_id="call_1", func_name="plugin_image", args={})
    result = ToolExecutionResult(
        tool_name="plugin_image",
        success=True,
        content_items=[
            ToolContentItem(
                content_type="image",
                data=b64encode(PNG_1X1).decode("ascii"),
                mime_type="image/png",
            )
        ],
    )
    assistant_message = AssistantMessage(content="", timestamp=datetime.now(), tool_calls=[tool_call])
    engine._append_tool_execution_result(tool_call, result)

    filtered_history, removed_count = drop_orphan_tool_results([assistant_message, *engine._runtime._chat_history])

    assert len(filtered_history) == 3
    assert removed_count == 0
