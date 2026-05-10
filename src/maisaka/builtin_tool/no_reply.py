"""no_reply 内置工具。"""

from typing import Optional

from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from .context import BuiltinToolRuntimeContext


def get_tool_spec() -> ToolSpec:
    """获取 no_reply 工具声明。"""

    return ToolSpec(
        name="no_reply",
        description="本轮不进行回复，等待其他用户的新消息；也用于用户可能还没说完、需要先把发言权交还给用户的场景。",
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 no_reply 内置工具。"""

    del context
    tool_ctx.runtime._enter_stop_state()
    return tool_ctx.build_success_result(
        invocation.tool_name,
        "当前暂时停止思考，等待新消息到来。",
        metadata={"pause_execution": True},
    )
