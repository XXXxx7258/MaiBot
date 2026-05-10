"""view_complex_message 内置工具。"""

from typing import Optional

from src.common.logger import get_logger
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from ..context_messages import build_full_complex_message_content, contains_complex_message
from .context import BuiltinToolRuntimeContext

logger = get_logger("maisaka_builtin_view_complex_message")


def get_tool_spec() -> ToolSpec:
    """获取 view_complex_message 工具声明。"""

    return ToolSpec(
        name="view_complex_message",
        description="根据 msg_id 查看复杂消息的完整内容，适用于 Prompt 中标记为 [消息类型]复杂消息 的消息。",
        parameters_schema={
            "type": "object",
            "properties": {
                "msg_id": {
                    "type": "string",
                    "description": "要查看完整内容的目标消息编号。",
                },
            },
            "required": ["msg_id"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 view_complex_message 内置工具。"""

    del context
    target_message_id = str(invocation.arguments.get("msg_id") or "").strip()
    if not target_message_id:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "查看复杂消息工具需要提供有效的 `msg_id` 参数。",
        )

    target_message = tool_ctx.runtime.find_source_message_by_id(target_message_id)
    if target_message is None:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"未找到目标复杂消息，msg_id={target_message_id}",
        )

    if not contains_complex_message(target_message.raw_message):
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"目标消息不是可展开查看的转发消息，msg_id={target_message_id}",
        )

    logger.info(
        f"{tool_ctx.runtime.log_prefix} 触发复杂消息查看工具，目标消息编号={target_message_id}"
    )
    try:
        full_content = await build_full_complex_message_content(target_message)
    except Exception as exc:
        logger.exception(
            f"{tool_ctx.runtime.log_prefix} 查看复杂消息时发生异常: 目标消息编号={target_message_id} 异常={exc}"
        )
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "查看复杂消息完整内容时发生异常。",
        )

    if not full_content:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            f"复杂消息内容为空，msg_id={target_message_id}",
        )

    return tool_ctx.build_success_result(
        invocation.tool_name,
        full_content,
        structured_content={
            "msg_id": target_message_id,
            "message_type": "forward",
            "full_content": full_content,
        },
        metadata={
            "record_display_prompt": f"你查看了复杂消息 {target_message_id} 的完整内容。",
        },
    )
