"""CLI 下的 Prompt 可视化渲染模块。"""

from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal
from urllib.parse import quote

import hashlib
import html
import json
import tempfile

from pydantic import BaseModel, Field as PydanticField
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.pretty import Pretty
from rich.text import Text

from .display_utils import (
    format_token_count,
    format_tool_call_for_display as normalize_tool_call_for_display,
    get_request_panel_style as get_shared_request_panel_style,
    get_role_badge_label as get_shared_role_badge_label,
    get_role_badge_style as get_shared_role_badge_style,
)
from .preview_path_utils import build_display_path, build_file_uri, REPO_ROOT
from .prompt_preview_logger import PromptPreviewLogger

DATA_IMAGE_DIR = REPO_ROOT / "data" / "images"


def _build_prompt_preview_web_uri(file_path: Path) -> str:
    """构建 WebUI 可访问的 Prompt 预览地址。"""

    try:
        relative_path = file_path.resolve().relative_to(PromptPreviewLogger._BASE_DIR.resolve())
    except ValueError:
        return build_file_uri(file_path)
    return f"/api/webui/config/maisaka-prompt-preview?path={quote(relative_path.as_posix(), safe='')}"


@dataclass(frozen=True)
class PromptPreviewAccess:
    """Prompt 预览文件的展示入口和可直接打开的路径。"""

    body: RenderableType
    viewer_path: Path
    viewer_uri: str
    viewer_web_uri: str
    dump_path: Path
    dump_uri: str


@dataclass(frozen=True)
class PromptSectionResult:
    """Prompt 面板及其可选 HTML 预览入口。"""

    panel: Panel
    preview_access: PromptPreviewAccess | None = None


class PromptImageDisplayMode(str, Enum):
    """图片在终端中的展示模式。"""

    LEGACY = "legacy"
    """不新增链接，仅保留原有的元信息展示。"""

    PATH_LINK = "path_link"
    """把图片落盘到临时目录并输出可点击路径。"""


class PromptImageDisplaySettings(BaseModel):
    """图片展示参数。"""

    display_mode: PromptImageDisplayMode = PydanticField(default=PromptImageDisplayMode.LEGACY)
    """图片展示模式。"""



@dataclass(slots=True)
class _MessageRenderResult:
    """可渲染结果与是否有工具调用信息。"""

    message_panel: Panel
    tool_call_panels: List[Panel]


class PromptCLIVisualizer:
    """负责构建 CLI 下 prompt 展示所需的所有可视化组件。"""

    @staticmethod
    def get_request_panel_style(request_kind: str) -> tuple[str, str]:
        """返回不同请求类型对应的标题与边框颜色。"""

        return get_shared_request_panel_style(request_kind)

    @staticmethod
    def _get_role_badge_style(role: str) -> str:
        return get_shared_role_badge_style(role)

    @staticmethod
    def _get_role_badge_label(role: str) -> str:
        return get_shared_role_badge_label(role)

    @staticmethod
    def _format_token_count(token_count: int) -> str:
        return format_token_count(token_count)

    @classmethod
    def build_prompt_stats_text(
        cls,
        *,
        selected_history_count: int,
        built_message_count: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> str:
        """构造 prompt 统计文本。"""
        return (
            f"上下文消息数量={selected_history_count} "
            f"已构建消息数={built_message_count} "
            f"实际输入Token={cls._format_token_count(prompt_tokens)} "
            f"输出Token={cls._format_token_count(completion_tokens)} "
            f"总Token={cls._format_token_count(total_tokens)}"
        )

    @staticmethod
    def _normalize_image_format(image_format: str) -> str:
        """归一化图片扩展名。"""
        normalized = image_format.strip().lower()
        if normalized == "jpg":
            return "jpeg"
        return normalized

    @staticmethod
    def _build_image_cache_path(image_format: str, image_base64: str) -> Path:
        image_format = PromptCLIVisualizer._normalize_image_format(image_format)
        root = Path(tempfile.gettempdir()) / "maisaka_prompt_images"
        root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(image_base64.encode("utf-8")).hexdigest()
        return root / f"{digest}.{image_format}"

    @staticmethod
    def _build_official_image_path(image_format: str, image_base64: str) -> Path | None:
        normalized_format = PromptCLIVisualizer._normalize_image_format(image_format)
        try:
            image_bytes = b64decode(image_base64)
        except Exception:
            return None

        digest = hashlib.sha256(image_bytes).hexdigest()
        official_path = DATA_IMAGE_DIR / f"{digest}.{normalized_format}"
        if official_path.exists():
            return official_path
        return None

    @staticmethod
    def _build_image_file_link(image_format: str, image_base64: str) -> tuple[str, Path] | None:
        """优先返回正式图片路径；不存在时回退到临时缓存路径。"""
        normalized_format = PromptCLIVisualizer._normalize_image_format(image_format) or "bin"
        official_path = PromptCLIVisualizer._build_official_image_path(image_format, image_base64)
        if official_path is not None:
            return build_file_uri(official_path), official_path

        try:
            image_bytes = b64decode(image_base64)
        except Exception:
            return None

        path = PromptCLIVisualizer._build_image_cache_path(normalized_format, image_base64)
        if not path.exists():
            try:
                path.write_bytes(image_bytes)
            except Exception:
                return None
        return build_file_uri(path), path

    @classmethod
    def _render_image_item(cls, image_format: str, image_base64: str, settings: PromptImageDisplaySettings) -> Panel:
        normalized_format = cls._normalize_image_format(image_format)
        approx_size = max(0, len(image_base64) * 3 // 4)
        size_text = f"{approx_size / 1024:.1f} KB" if approx_size >= 1024 else f"{approx_size} B"

        preview_parts: List[RenderableType] = [
            Text(f"图片格式 image/{normalized_format}  {size_text}", style="magenta")
        ]

        if settings.display_mode == PromptImageDisplayMode.PATH_LINK:
            path_result = cls._build_image_file_link(image_format, image_base64)
            if path_result is not None:
                file_uri, file_path = path_result
                display_path = build_display_path(file_path)
                preview_parts: List[RenderableType] = [
                    Text(f"图片格式 image/{normalized_format}  {size_text} 路径：{display_path}", style="magenta")
                ]
                
                preview_parts.append(Text.from_markup(f"[link={file_uri}]点击打开图片[/link]", style="cyan"))

        return Panel(
            Group(*preview_parts),
            border_style="magenta",
            padding=(0, 1),
        )

    @staticmethod
    def _extract_image_pair(item: Any) -> tuple[str, str] | None:
        """兼容图片片段被序列化为 tuple 或 list 的两种形式。"""

        if isinstance(item, (tuple, list)) and len(item) == 2:
            image_format, image_base64 = item
            if isinstance(image_format, str) and isinstance(image_base64, str):
                return image_format, image_base64
        return None

    @classmethod
    def _render_message_content(cls, content: Any, settings: PromptImageDisplaySettings) -> RenderableType:
        if isinstance(content, str):
            return Text(content)

        if isinstance(content, list):
            parts: List[RenderableType] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(Text(item))
                    continue
                image_pair = cls._extract_image_pair(item)
                if image_pair is not None:
                    image_format, image_base64 = image_pair
                    parts.append(cls._render_image_item(image_format, image_base64, settings))
                    continue
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(Text(item["text"]))
                else:
                    parts.append(Pretty(item, expand_all=True))
            return Group(*parts) if parts else Text("")

        if content is None:
            return Text("")

        return Pretty(content, expand_all=True)

    @classmethod
    def _serialize_message_content_for_dump(cls, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                image_pair = cls._extract_image_pair(item)
                if image_pair is not None:
                    image_format, image_base64 = image_pair
                    approx_size = max(0, len(str(image_base64)) * 3 // 4)
                    parts.append(f"[图片 image/{image_format} {approx_size} B]")
                    continue
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                    continue
                try:
                    parts.append(json.dumps(item, ensure_ascii=False, indent=2, default=str))
                except Exception:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part).strip()
        if content is None:
            return ""
        try:
            return json.dumps(content, ensure_ascii=False, indent=2, default=str)
        except Exception:
            return str(content)

    @classmethod
    def format_tool_call_for_display(cls, tool_call: Any) -> Dict[str, Any]:
        return normalize_tool_call_for_display(tool_call)

    @classmethod
    def _build_tool_card_title(cls, tool_call: Any) -> str:
        """构建 HTML 中工具卡片的折叠标题。"""

        normalized_tool_call = cls.format_tool_call_for_display(tool_call)
        tool_name = str(normalized_tool_call.get("name") or "").strip()
        return tool_name or "unknown"

    @classmethod
    def _build_tool_call_html(cls, tool_call: Any) -> str:
        """将单个工具调用渲染为默认折叠的 HTML 卡片。"""

        normalized_tool_call = cls.format_tool_call_for_display(tool_call)
        tool_name = cls._build_tool_card_title(tool_call)
        tool_call_id = str(normalized_tool_call.get("id") or "").strip()
        tool_arguments = normalized_tool_call.get("arguments")

        tool_meta_html = ""
        if tool_call_id:
            tool_meta_html = (
                "<div class='tool-card-meta'>"
                "<span class='tool-card-meta-label'>调用 ID</span>"
                f"<code>{html.escape(tool_call_id)}</code>"
                "</div>"
            )

        return (
            "<details class='tool-card tool-call-card'>"
            "<summary class='tool-card-summary'>"
            f"<span class='tool-card-name'>{html.escape(tool_name)}</span>"
            "</summary>"
            "<div class='tool-card-body'>"
            f"{tool_meta_html}"
            f"<pre>{html.escape(json.dumps(tool_arguments, ensure_ascii=False, indent=2, default=str))}</pre>"
            "</div>"
            "</details>"
        )

    @classmethod
    def _extract_tool_definition_fields(cls, tool_definition: dict[str, Any]) -> tuple[str, str, Any]:
        """提取工具定义中的名称、描述和详情内容。"""

        function_info = tool_definition.get("function")
        if isinstance(function_info, dict):
            tool_name = str(function_info.get("name") or "").strip() or "unknown"
            description = str(function_info.get("description") or "").strip()
            detail_payload = function_info
        else:
            tool_name = str(tool_definition.get("name") or "").strip() or "unknown"
            description = str(tool_definition.get("description") or "").strip()
            detail_payload = tool_definition
        return tool_name, description, detail_payload

    @classmethod
    def _build_tool_definition_html(cls, tool_definition: dict[str, Any]) -> str:
        """将单个传入工具定义渲染为默认折叠的 HTML 卡片。"""

        tool_name, description, detail_payload = cls._extract_tool_definition_fields(tool_definition)
        description_html = ""
        if description:
            description_html = (
                "<div class='tool-card-meta'>"
                "<span class='tool-card-meta-label'>说明</span>"
                f"<span>{html.escape(description)}</span>"
                "</div>"
            )

        return (
            "<details class='tool-card tool-definition-card'>"
            "<summary class='tool-card-summary'>"
            f"<span class='tool-card-name'>{html.escape(tool_name)}</span>"
            "</summary>"
            "<div class='tool-card-body'>"
            f"{description_html}"
            f"<pre>{html.escape(json.dumps(detail_payload, ensure_ascii=False, indent=2, default=str))}</pre>"
            "</div>"
            "</details>"
        )

    @classmethod
    def _render_tool_call_panel(cls, tool_call: Any, index: int, parent_index: int) -> Panel:
        title = Text.assemble(
            Text(" 工具调用 ", style="bold white on magenta"),
            Text(f"  #{parent_index}.{index}", style="muted"),
        )
        return Panel(
            Pretty(cls.format_tool_call_for_display(tool_call), expand_all=True),
            title=title,
            border_style="magenta",
            padding=(0, 1),
        )

    @classmethod
    def _build_prompt_dump_text(cls, messages: list[Any]) -> str:
        sections: List[str] = []
        for index, message in enumerate(messages, start=1):
            if isinstance(message, dict):
                raw_role = message.get("role", "unknown")
                content = message.get("content")
                tool_call_id = message.get("tool_call_id")
                tool_calls = message.get("tool_calls") or []
            else:
                raw_role = getattr(message, "role", "unknown")
                content = getattr(message, "content", None)
                tool_call_id = getattr(message, "tool_call_id", None)
                tool_calls = getattr(message, "tool_calls", None) or []

            role = raw_role.value if hasattr(raw_role, "value") else str(raw_role)
            block_lines = [f"[{index}] role={role}"]
            if tool_call_id:
                block_lines.append(f"tool_call_id={tool_call_id}")

            normalized_content = cls._serialize_message_content_for_dump(content)
            if normalized_content:
                block_lines.append("")
                block_lines.append(normalized_content)

            if tool_calls:
                block_lines.append("")
                block_lines.append("tool_calls:")
                for tool_call in tool_calls:
                    normalized_tool_call = cls.format_tool_call_for_display(tool_call)
                    block_lines.append(json.dumps(normalized_tool_call, ensure_ascii=False, indent=2, default=str))

            sections.append("\n".join(block_lines).strip())

        return "\n\n" + ("\n\n" + ("=" * 80) + "\n\n").join(sections) if sections else "[空 Prompt]"

    @classmethod
    def _build_tool_definition_dump_text(cls, tool_definitions: list[dict[str, Any]] | None) -> str:
        """构建传入工具定义的文本备份内容。"""

        if not tool_definitions:
            return ""

        sections: List[str] = ["[tool_definitions]"]
        for index, tool_definition in enumerate(tool_definitions, start=1):
            tool_name, _, detail_payload = cls._extract_tool_definition_fields(tool_definition)
            sections.append(f"[{index}] name={tool_name}")
            sections.append(json.dumps(detail_payload, ensure_ascii=False, indent=2, default=str))
        return "\n\n".join(sections).strip()

    @classmethod
    def _render_message_content_html(cls, content: Any) -> str:
        if isinstance(content, str):
            return f"<pre>{html.escape(content)}</pre>"

        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(f"<pre>{html.escape(item)}</pre>")
                    continue
                image_pair = cls._extract_image_pair(item)
                if image_pair is not None:
                    image_format, image_base64 = image_pair
                    image_html = cls._render_image_item_html(str(image_format), str(image_base64))
                    parts.append(image_html)
                    continue
                if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(f"<pre>{html.escape(item['text'])}</pre>")
                    continue
                parts.append(f"<pre>{html.escape(json.dumps(item, ensure_ascii=False, indent=2, default=str))}</pre>")
            return "".join(parts) if parts else "<pre></pre>"

        if content is None:
            return "<pre></pre>"

        return f"<pre>{html.escape(json.dumps(content, ensure_ascii=False, indent=2, default=str))}</pre>"

    @classmethod
    def _render_image_item_html(cls, image_format: str, image_base64: str) -> str:
        normalized_format = cls._normalize_image_format(image_format)
        approx_size = max(0, len(image_base64) * 3 // 4)
        size_text = f"{approx_size / 1024:.1f} KB" if approx_size >= 1024 else f"{approx_size} B"
        path_result = cls._build_image_file_link(image_format, image_base64)
        if path_result is None:
            return (
                "<div class='image-card'>"
                f"<div class='image-meta'>图片 image/{html.escape(normalized_format)} {html.escape(size_text)}</div>"
                "</div>"
            )

        file_uri, file_path = path_result
        display_path = build_display_path(file_path)
        return (
            "<div class='image-card'>"
            f"<div class='image-meta'>图片 image/{html.escape(normalized_format)} {html.escape(size_text)}</div>"
            f"<a class='image-preview-link' href='{html.escape(file_uri, quote=True)}'>"
            f"<img class='image-preview' src='{html.escape(file_uri, quote=True)}' alt='图片预览' />"
            "</a>"
            f"<div class='image-path'>{html.escape(display_path)}</div>"
            f"<a class='image-link' href='{html.escape(file_uri, quote=True)}'>打开图片</a>"
            "</div>"
        )

    @staticmethod
    def _build_preview_access_body(
        *,
        viewer_label: str,
        viewer_path: Path,
        viewer_link_text: str,
        dump_label: str,
        dump_path: Path,
        dump_link_text: str,
    ) -> RenderableType:
        viewer_uri = build_file_uri(viewer_path)
        dump_uri = build_file_uri(dump_path)
        viewer_display_path = build_display_path(viewer_path)
        dump_display_path = build_display_path(dump_path)

        return Group(
            Text.from_markup(
                f"[bold green]{viewer_label}：{viewer_display_path}[/bold green] "
                f"[link={viewer_uri}]{viewer_link_text}[/link]"
            ),
            Text.from_markup(
                f"[magenta]{dump_label}：{dump_display_path}[/magenta] "
                f"[cyan][link={dump_uri}]{dump_link_text}[/link][/cyan]"
            ),
        )

    @classmethod
    def build_prompt_preview_access(
        cls,
        messages: list[Any],
        *,
        category: str,
        chat_id: str,
        request_kind: str,
        selection_reason: str,
        tool_definitions: list[dict[str, Any]] | None = None,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> PromptPreviewAccess:
        """保存 Prompt 预览文件，并返回 CLI 展示入口与浏览器可打开的 URI。"""

        viewer_messages: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, dict):
                viewer_messages.append(dict(message))
                continue

            normalized_message = {
                "content": getattr(message, "content", None),
                "role": getattr(getattr(message, "role", "unknown"), "value", getattr(message, "role", "unknown")),
            }
            tool_call_id = getattr(message, "tool_call_id", None)
            if tool_call_id:
                normalized_message["tool_call_id"] = tool_call_id

            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                normalized_message["tool_calls"] = [
                    cls.format_tool_call_for_display(tool_call) for tool_call in tool_calls
                ]
            viewer_messages.append(normalized_message)

        prompt_dump_text = cls._build_prompt_dump_text(messages)
        if output_content not in (None, "", []):
            output_dump_text = cls._serialize_message_content_for_dump(output_content)
            prompt_dump_text = f"[{output_title}]\n\n{output_dump_text}\n\n{'=' * 80}\n\n{prompt_dump_text}"
        tool_definition_dump_text = cls._build_tool_definition_dump_text(tool_definitions)
        if tool_definition_dump_text:
            prompt_dump_text = f"{prompt_dump_text}\n\n{'=' * 80}\n\n{tool_definition_dump_text}"
        viewer_html_text = cls._build_prompt_viewer_html(
            viewer_messages,
            request_kind=request_kind,
            selection_reason=selection_reason,
            tool_definitions=tool_definitions,
            output_content=output_content,
            output_title=output_title,
        )
        saved_paths = PromptPreviewLogger.save_preview_files(
            chat_id,
            category,
            {
                ".html": viewer_html_text,
                ".txt": prompt_dump_text,
            },
        )
        viewer_html_path = saved_paths[".html"]
        prompt_dump_path = saved_paths[".txt"]
        body = cls._build_preview_access_body(
            viewer_label="html预览",
            viewer_path=viewer_html_path,
            viewer_link_text="在浏览器打开 Prompt",
            dump_label="原始文本",
            dump_path=prompt_dump_path,
            dump_link_text="点击打开 Prompt 文本",
        )
        return PromptPreviewAccess(
            body=body,
            viewer_path=viewer_html_path,
            viewer_uri=build_file_uri(viewer_html_path),
            viewer_web_uri=_build_prompt_preview_web_uri(viewer_html_path),
            dump_path=prompt_dump_path,
            dump_uri=build_file_uri(prompt_dump_path),
        )

    @classmethod
    def _build_html_role_class(cls, role: str) -> str:
        return {
            "system": "system",
            "user": "user",
            "assistant": "assistant",
            "tool": "tool",
        }.get(role, "unknown")

    @classmethod
    def _build_prompt_viewer_html(
        cls,
        messages: list[dict[str, Any]],
        *,
        request_kind: str,
        selection_reason: str,
        tool_definitions: list[dict[str, Any]] | None = None,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> str:
        panel_title, _ = cls.get_request_panel_style(request_kind)
        message_cards: List[str] = []
        for index, message in enumerate(messages, start=1):
            raw_role = message.get("role", "unknown")
            role = raw_role.value if hasattr(raw_role, "value") else str(raw_role)
            role_label = cls._get_role_badge_label(role)
            role_class = cls._build_html_role_class(role)
            content_html = cls._render_message_content_html(message.get("content"))
            tool_call_id = message.get("tool_call_id")
            tool_call_html = ""
            if tool_call_id:
                tool_call_html = (
                    "<div class='tool-call-id'>"
                    "<span class='tool-call-label'>工具调用 ID</span>"
                    f"<code>{html.escape(str(tool_call_id))}</code>"
                    "</div>"
                )

            tool_panels = ""
            raw_tool_calls = message.get("tool_calls") or []
            if isinstance(raw_tool_calls, list) and raw_tool_calls:
                tool_panels = (
                    "<div class='tool-list'>"
                    "<div class='tool-list-title'>工具调用</div>"
                    f"{''.join(cls._build_tool_call_html(tool_call) for tool_call in raw_tool_calls)}"
                    "</div>"
                )

            message_cards.append(
                "<section class='message-card'>"
                "<div class='message-head'>"
                f"<span class='role-badge {role_class}'>{html.escape(role_label)}</span>"
                f"<span class='message-index'>#{index}</span>"
                "</div>"
                f"<div class='message-content'>{content_html}</div>"
                f"{tool_call_html}"
                f"{tool_panels}"
                "</section>"
            )

        output_section_html = ""
        if output_content not in (None, "", []):
            output_section_html = (
                "<section class='message-card output-card'>"
                "<div class='message-head'>"
                f"<span class='role-badge output'>{html.escape(output_title)}</span>"
                "</div>"
                f"<div class='message-content'>{cls._render_message_content_html(output_content)}</div>"
                "</section>"
            )

        subtitle_html = ""
        if selection_reason.strip():
            subtitle_html = f"<div class='subtitle'>{html.escape(selection_reason)}</div>"

        tool_definition_section_html = ""
        if tool_definitions:
            tool_definition_section_html = (
                "<section class='message-card tool-definition-section'>"
                "<div class='message-head'>"
                "<span class='role-badge tool'>全部工具</span>"
                f"<span class='message-index'>{len(tool_definitions)} 个</span>"
                "</div>"
                "<div class='tool-list'>"
                "<div class='tool-list-title'>本次送入模型的工具定义</div>"
                f"{''.join(cls._build_tool_definition_html(tool_definition) for tool_definition in tool_definitions)}"
                "</div>"
                "</section>"
            )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(panel_title)}</title>
  <style>
    :root {{
      --bg: #f5f7fb;
      --card: #ffffff;
      --border: #d7dfeb;
      --text: #18212f;
      --muted: #5b6878;
      --system: #1d4ed8;
      --user: #16a34a;
      --assistant: #ca8a04;
      --tool: #c026d3;
      --output: #0f766e;
      --unknown: #475569;
      --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(29, 78, 216, 0.12), transparent 28%),
        radial-gradient(circle at top right, rgba(192, 38, 211, 0.10), transparent 26%),
        var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .page {{
      width: min(1200px, calc(100vw - 40px));
      margin: 24px auto 40px;
    }}
    .hero {{
      background: linear-gradient(135deg, #ffffff 0%, #eef4ff 100%);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow: var(--shadow);
      padding: 20px 24px;
      margin-bottom: 18px;
    }}
    .title {{
      font-size: 26px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .subtitle {{
      margin-top: 10px;
      color: var(--muted);
      white-space: pre-wrap;
    }}
    .message-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 16px 18px;
      margin-bottom: 14px;
    }}
    .message-head {{
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .role-badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 5px 12px;
      color: #fff;
      font-size: 13px;
      font-weight: 700;
    }}
    .role-badge.system {{ background: var(--system); }}
    .role-badge.user {{ background: var(--user); }}
    .role-badge.assistant {{ background: var(--assistant); color: #1f2937; }}
    .role-badge.tool {{ background: var(--tool); }}
    .role-badge.output {{ background: var(--output); }}
    .role-badge.unknown {{ background: var(--unknown); }}
    .output-card {{
      border-color: rgba(15, 118, 110, 0.38);
      background: linear-gradient(180deg, #ffffff 0%, #f0fdfa 100%);
    }}
    .message-index {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
    }}
    .message-content pre,
    .tool-card pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
      font-size: 13px;
      line-height: 1.55;
      color: #1e293b;
    }}
    .tool-call-id {{
      margin-top: 12px;
      color: var(--tool);
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .tool-call-label {{
      font-weight: 700;
    }}
    .tool-call-id code {{
      background: #faf5ff;
      border: 1px solid #e9d5ff;
      border-radius: 8px;
      padding: 3px 8px;
    }}
    .tool-list {{
      margin-top: 14px;
    }}
    .tool-list-title {{
      color: #86198f;
      font-size: 13px;
      font-weight: 800;
      margin-bottom: 10px;
    }}
    .tool-card {{
      margin-top: 12px;
      background: #fcf4ff;
      border: 1px solid #f0d7fb;
      border-radius: 14px;
      overflow: hidden;
    }}
    .tool-call-card {{
      border-color: #ff8700;
    }}
    .tool-card:first-of-type {{
      margin-top: 0;
    }}
    .tool-card-summary {{
      list-style: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 14px;
      color: #86198f;
      font-size: 13px;
      font-weight: 800;
    }}
    .tool-card-summary::-webkit-details-marker {{
      display: none;
    }}
    .tool-card-summary::after {{
      content: "展开";
      color: #a21caf;
      font-size: 12px;
      font-weight: 700;
    }}
    .tool-card[open] .tool-card-summary::after {{
      content: "收起";
    }}
    .tool-card-name {{
      word-break: break-word;
    }}
    .tool-card-body {{
      border-top: 1px solid #f0d7fb;
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.52);
    }}
    .tool-call-card .tool-card-body {{
      border-top-color: #ff8700;
    }}
    .tool-card-meta {{
      margin-bottom: 10px;
      color: #a21caf;
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .tool-card-meta-label {{
      font-weight: 700;
    }}
    .tool-card-meta code {{
      background: #faf5ff;
      border: 1px solid #e9d5ff;
      border-radius: 8px;
      padding: 3px 8px;
    }}
    .tool-card pre {{
      color: #3b0764;
    }}
    .image-card {{
      background: #f8fafc;
      border: 1px solid #dbe4f0;
      border-radius: 14px;
      padding: 12px 14px;
      margin: 8px 0;
    }}
    .image-meta {{
      color: #a21caf;
      font-weight: 700;
    }}
    .image-path {{
      margin-top: 6px;
      color: var(--muted);
      font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
      word-break: break-all;
    }}
    .image-preview-link {{
      display: block;
      margin-top: 10px;
    }}
    .image-preview {{
      display: block;
      max-width: min(100%, 560px);
      max-height: 420px;
      width: auto;
      height: auto;
      border-radius: 12px;
      border: 1px solid #dbe4f0;
      background: #fff;
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
      object-fit: contain;
    }}
    .image-link {{
      display: inline-block;
      margin-top: 8px;
      color: #0f766e;
      font-weight: 700;
      text-decoration: none;
    }}
    .image-link:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <div class="title">{html.escape(panel_title)}</div>
      {subtitle_html}
    </header>
    {output_section_html}
    {''.join(message_cards)}
    {tool_definition_section_html}
  </main>
</body>
</html>"""

    @classmethod
    def build_prompt_access_panel(
        cls,
        messages: list[Any],
        *,
        category: str,
        chat_id: str,
        request_kind: str,
        selection_reason: str,
        image_display_mode: Literal["legacy", "path_link"] = "path_link",
        tool_definitions: list[dict[str, Any]] | None = None,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> RenderableType:
        """构建用于查看完整 prompt 的折叠入口内容。"""

        return cls.build_prompt_preview_access(
            messages,
            category=category,
            chat_id=chat_id,
            request_kind=request_kind,
            selection_reason=selection_reason,
            tool_definitions=tool_definitions,
            output_content=output_content,
            output_title=output_title,
        ).body

    @classmethod
    def build_prompt_section(
        cls,
        messages: list[Any],
        *,
        category: str,
        chat_id: str,
        request_kind: str,
        selection_reason: str,
        image_display_mode: Literal["legacy", "path_link"] = "path_link",
        folded: bool,
        tool_definitions: list[dict[str, Any]] | None = None,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> Panel:
        """构建用于嵌入结果面板中的 Prompt 区块。"""

        return cls.build_prompt_section_result(
            messages,
            category=category,
            chat_id=chat_id,
            request_kind=request_kind,
            selection_reason=selection_reason,
            image_display_mode=image_display_mode,
            folded=folded,
            tool_definitions=tool_definitions,
            output_content=output_content,
            output_title=output_title,
        ).panel

    @classmethod
    def build_prompt_section_result(
        cls,
        messages: list[Any],
        *,
        category: str,
        chat_id: str,
        request_kind: str,
        selection_reason: str,
        image_display_mode: Literal["legacy", "path_link"] = "path_link",
        folded: bool,
        tool_definitions: list[dict[str, Any]] | None = None,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> PromptSectionResult:
        """构建 Prompt 面板，并在折叠模式下返回对应的 HTML 预览入口。"""

        panel_title, panel_border_style = cls.get_request_panel_style(request_kind)
        preview_access = cls.build_prompt_preview_access(
            messages,
            category=category,
            chat_id=chat_id,
            request_kind=request_kind,
            selection_reason=selection_reason,
            tool_definitions=tool_definitions,
            output_content=output_content,
            output_title=output_title,
        )
        if folded:
            prompt_renderable = preview_access.body
        else:
            ordered_panels = cls.build_prompt_panels(messages)
            prompt_renderable = Group(*ordered_panels)

        return PromptSectionResult(
            panel=Panel(
                prompt_renderable,
                title=panel_title,
                subtitle=selection_reason,
                border_style=panel_border_style,
                padding=(0, 1),
            ),
            preview_access=preview_access,
        )

    @classmethod
    def _build_text_preview_html(
        cls,
        content: str,
        *,
        request_kind: str,
        subtitle: str,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> str:
        panel_title, _ = cls.get_request_panel_style(request_kind)
        subtitle_html = f"<div class='subtitle'>{html.escape(subtitle)}</div>" if subtitle.strip() else ""
        output_section_html = ""
        if output_content not in (None, "", []):
            output_section_html = (
                "<section class='content-card output-card'>"
                f"<div class='output-title'>{html.escape(output_title)}</div>"
                f"{cls._render_message_content_html(output_content)}"
                "</section>"
            )
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(panel_title)}</title>
  <style>
    :root {{
      --bg: #f6f7fb;
      --card: #ffffff;
      --border: #d7dfeb;
      --text: #18212f;
      --muted: #5b6878;
      --shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
    }}
    body {{
      margin: 0;
      background:
        radial-gradient(circle at top left, rgba(202, 138, 4, 0.12), transparent 24%),
        radial-gradient(circle at top right, rgba(29, 78, 216, 0.10), transparent 24%),
        var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .page {{
      width: min(1200px, calc(100vw - 40px));
      margin: 24px auto 40px;
    }}
    .hero {{
      background: linear-gradient(135deg, #ffffff 0%, #fff8eb 100%);
      border: 1px solid var(--border);
      border-radius: 20px;
      box-shadow: var(--shadow);
      padding: 20px 24px;
      margin-bottom: 18px;
    }}
    .title {{
      font-size: 26px;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .subtitle {{
      margin-top: 10px;
      color: var(--muted);
      white-space: pre-wrap;
    }}
    .content-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 18px 20px;
      margin-bottom: 14px;
    }}
    .output-card {{
      border-color: rgba(15, 118, 110, 0.38);
      background: linear-gradient(180deg, #ffffff 0%, #f0fdfa 100%);
    }}
    .output-title {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 5px 12px;
      color: #fff;
      background: #0f766e;
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 12px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", monospace;
      font-size: 13px;
      line-height: 1.6;
      color: #1e293b;
    }}
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <div class="title">{html.escape(panel_title)}</div>
      {subtitle_html}
    </header>
    {output_section_html}
    <section class="content-card">
      <pre>{html.escape(content)}</pre>
    </section>
  </main>
</body>
</html>"""

    @classmethod
    def build_text_access_panel(
        cls,
        content: str,
        *,
        category: str,
        chat_id: str,
        request_kind: str,
        subtitle: str,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> RenderableType:
        """构建文本型 Prompt 的折叠入口内容。"""

        html_content = cls._build_text_preview_html(
            content,
            request_kind=request_kind,
            subtitle=subtitle,
            output_content=output_content,
            output_title=output_title,
        )
        text_content = content
        if output_content not in (None, "", []):
            output_dump_text = cls._serialize_message_content_for_dump(output_content)
            text_content = f"[{output_title}]\n\n{output_dump_text}\n\n{'=' * 80}\n\n{content}"
        saved_paths = PromptPreviewLogger.save_preview_files(
            chat_id,
            category,
            {
                ".html": html_content,
                ".txt": text_content,
            },
        )
        viewer_html_path = saved_paths[".html"]
        text_dump_path = saved_paths[".txt"]
        body = cls._build_preview_access_body(
            viewer_label="富文本预览",
            viewer_path=viewer_html_path,
            viewer_link_text="点击在浏览器打开富文本 Prompt 视图",
            dump_label="原始文本备份",
            dump_path=text_dump_path,
            dump_link_text="点击直接打开 Prompt 文本",
        )
        return body

    @classmethod
    def build_text_section(
        cls,
        content: str,
        *,
        category: str,
        chat_id: str,
        request_kind: str,
        subtitle: str,
        folded: bool,
        output_content: Any | None = None,
        output_title: str = "输出结果",
    ) -> Panel:
        """构建文本型 Prompt 的嵌入区块。"""

        panel_title, panel_border_style = cls.get_request_panel_style(request_kind)
        if folded:
            prompt_renderable = cls.build_text_access_panel(
                content,
                category=category,
                chat_id=chat_id,
                request_kind=request_kind,
                subtitle=subtitle,
                output_content=output_content,
                output_title=output_title,
            )
        else:
            prompt_renderable = Text(content)

        return Panel(
            prompt_renderable,
            title=panel_title,
            subtitle=subtitle,
            border_style=panel_border_style,
            padding=(0, 1),
        )

    @classmethod
    def _render_message_panel(cls, message: Any, index: int, settings: PromptImageDisplaySettings) -> _MessageRenderResult:
        if isinstance(message, dict):
            raw_role = message.get("role", "unknown")
            content = message.get("content")
            tool_call_id = message.get("tool_call_id")
        else:
            raw_role = getattr(message, "role", "unknown")
            content = getattr(message, "content", None)
            tool_call_id = getattr(message, "tool_call_id", None)

        role = raw_role.value if hasattr(raw_role, "value") else str(raw_role)
        title = Text.assemble(
            Text(f" {cls._get_role_badge_label(role)} ", style=cls._get_role_badge_style(role)),
            Text(f"  #{index}", style="muted"),
        )

        parts: List[RenderableType] = []
        if content not in (None, "", []):
            parts.append(cls._render_message_content(content, settings))

        if tool_call_id:
            parts.append(
                Text.assemble(
                    Text(" 工具调用ID ", style="bold magenta"),
                    Text(" "),
                    Text(str(tool_call_id), style="magenta"),
                )
            )

        if not parts:
            parts.append(Text("[空]", style="muted"))

        message_panel = Panel(
            Group(*parts),
            title=title,
            border_style="dim",
            padding=(0, 1),
        )

        tool_call_panels: List[Panel] = []
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            for tool_call_index, tool_call in enumerate(tool_calls, start=1):
                tool_call_panels.append(cls._render_tool_call_panel(tool_call, tool_call_index, index))

        return _MessageRenderResult(message_panel=message_panel, tool_call_panels=tool_call_panels)

    @classmethod
    def build_prompt_panels(
        cls,
        messages: list[Any],
        *,
        image_display_mode: Literal["legacy", "path_link"] = "path_link",
    ) -> List[Panel]:
        """构建完整 prompt 可视化面板。"""
        settings = PromptImageDisplaySettings(
            display_mode=PromptImageDisplayMode(image_display_mode),
        )

        ordered_panels: List[Panel] = []
        for index, message in enumerate(messages, start=1):
            message_render_result = cls._render_message_panel(message, index, settings)
            ordered_panels.append(message_render_result.message_panel)
            ordered_panels.extend(message_render_result.tool_call_panels)
        return ordered_panels
