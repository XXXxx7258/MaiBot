"""Maisaka Prompt 预览落盘器。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .preview_path_utils import build_preview_chat_dir_name, normalize_preview_name


class PromptPreviewLogger:
    """负责保存 Maisaka Prompt 预览文件并控制目录容量。

    写入与清理在单线程后台 executor 中执行：目录内文件可达数千个，
    iterdir/stat/unlink 直接跑在事件循环上会造成秒级卡顿。
    """

    _BASE_DIR = Path("logs") / "maisaka_prompt"
    _DEFAULT_MAX_PREVIEW_GROUPS_PER_CHAT = 256
    _TRIM_COUNT = 100

    _io_executor: ThreadPoolExecutor | None = None
    _last_stem_base: str = ""
    _last_stem_suffix: int = 0

    @classmethod
    def _get_io_executor(cls) -> ThreadPoolExecutor:
        if cls._io_executor is None:
            cls._io_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prompt-preview")
        return cls._io_executor

    @classmethod
    def _build_file_stem(cls) -> str:
        base_stem = str(int(time.time() * 1000))
        if base_stem == cls._last_stem_base:
            cls._last_stem_suffix += 1
            return f"{base_stem}_{cls._last_stem_suffix}"
        cls._last_stem_base = base_stem
        cls._last_stem_suffix = 0
        return base_stem

    @classmethod
    def save_preview_file(
        cls,
        chat_id: str,
        category: str,
        content: str,
    ) -> Path:
        """保存 Prompt 预览 JSON 并执行超量清理。写入在后台线程完成。"""

        normalized_category = normalize_preview_name(category)
        chat_dir = (cls._BASE_DIR / normalized_category / build_preview_chat_dir_name(chat_id)).resolve()
        stem = cls._build_file_stem()
        file_path = chat_dir / f"{stem}.json"
        cls._get_io_executor().submit(cls._write_and_trim, chat_dir, file_path, content)
        return file_path

    @classmethod
    def _write_and_trim(cls, chat_dir: Path, file_path: Path, content: str) -> None:
        try:
            chat_dir.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        finally:
            cls._trim_overflow(chat_dir)

    @staticmethod
    def _group_sort_key(item: tuple[str, list[Path]]) -> float:
        stem = item[0]
        try:
            return float(stem.split("_", 1)[0])
        except ValueError:
            try:
                return min(path.stat().st_mtime * 1000 for path in item[1])
            except OSError:
                return 0.0

    @classmethod
    def _trim_overflow(cls, chat_dir: Path) -> None:
        """超过阈值时按批次删除最老的若干组预览文件。"""

        max_preview_groups = cls._get_max_preview_groups_per_chat()
        grouped_files: dict[str, list[Path]] = {}
        for file_path in chat_dir.iterdir():
            if not file_path.is_file():
                continue
            grouped_files.setdefault(file_path.stem, []).append(file_path)

        if len(grouped_files) <= max_preview_groups:
            return

        sorted_groups = sorted(grouped_files.items(), key=cls._group_sort_key)
        overflow_count = len(grouped_files) - max_preview_groups
        trim_count = min(len(sorted_groups), max(cls._TRIM_COUNT, overflow_count))
        for _, file_group in sorted_groups[:trim_count]:
            for old_file in file_group:
                try:
                    old_file.unlink()
                except FileNotFoundError:
                    continue

    @classmethod
    def _get_max_preview_groups_per_chat(cls) -> int:
        try:
            from src.config.config import global_config

            configured_limit = global_config.log.maisaka_prompt_preview_limit
            return max(1, int(configured_limit or cls._DEFAULT_MAX_PREVIEW_GROUPS_PER_CHAT))
        except Exception:
            return cls._DEFAULT_MAX_PREVIEW_GROUPS_PER_CHAT
