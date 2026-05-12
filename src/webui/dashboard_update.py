"""WebUI dashboard 版本检查与自动更新。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as get_package_version
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import asyncio
import os
import shutil
import subprocess
import sys
import time

import httpx

from src.common.logger import get_logger

logger = get_logger("webui_dashboard_update")

DASHBOARD_PACKAGE_NAME = "maibot-dashboard"
PYTHON_OVERLAY_TARGET_ENV = "MAIBOT_PYTHON_OVERLAY_TARGET"
PYPI_JSON_URL = f"https://pypi.org/pypi/{DASHBOARD_PACKAGE_NAME}/json"
PYPI_PROJECT_URL = f"https://pypi.org/project/{DASHBOARD_PACKAGE_NAME}/"
PYPI_CACHE_TTL_SECONDS = 60 * 60 * 6

PackageRunner = Literal["uv", "pip", "unknown"]
_pypi_version_cache: Dict[str, Any] = {"checked_at": 0.0, "latest_version": None}


@dataclass(frozen=True)
class DashboardVersionInfo:
    """WebUI dashboard 版本检查结果。"""

    current_version: str
    latest_version: Optional[str]
    has_update: bool
    package_name: str = DASHBOARD_PACKAGE_NAME
    pypi_url: str = PYPI_PROJECT_URL


@dataclass(frozen=True)
class DashboardUpdateResult:
    """WebUI dashboard 自动更新结果。"""

    checked: bool
    updated: bool
    current_version: str
    latest_version: Optional[str]
    runner: PackageRunner
    message: str


def get_installed_dashboard_version() -> str:
    try:
        return get_package_version(DASHBOARD_PACKAGE_NAME)
    except PackageNotFoundError:
        return "unknown"


def normalize_version(version: str) -> tuple[int, ...]:
    clean_version = version.strip().lower().removeprefix("v")
    numeric_part = clean_version.split("-", 1)[0].split("+", 1)[0]
    parts = []
    for item in numeric_part.split("."):
        number = ""
        for char in item:
            if not char.isdigit():
                break
            number += char
        parts.append(int(number) if number else 0)
    return tuple(parts)


def is_newer_version(latest_version: Optional[str], current_version: str) -> bool:
    if not latest_version or not current_version or current_version == "unknown":
        return False

    latest_parts = normalize_version(latest_version)
    current_parts = normalize_version(current_version)
    width = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (width - len(latest_parts)) > current_parts + (0,) * (width - len(current_parts))


async def get_latest_dashboard_version_from_pypi() -> Optional[str]:
    now = time.time()
    cached_version = _pypi_version_cache.get("latest_version")
    checked_at = float(_pypi_version_cache.get("checked_at", 0.0))
    if cached_version and now - checked_at < PYPI_CACHE_TTL_SECONDS:
        return str(cached_version)

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(PYPI_JSON_URL)
            response.raise_for_status()
            payload = response.json()
    except Exception as e:
        logger.debug(f"检查 WebUI PyPI 版本失败: {e}")
        return str(cached_version) if cached_version else None

    latest_version = payload.get("info", {}).get("version")
    if isinstance(latest_version, str) and latest_version.strip():
        _pypi_version_cache["checked_at"] = now
        _pypi_version_cache["latest_version"] = latest_version.strip()
        return latest_version.strip()

    return str(cached_version) if cached_version else None


async def get_dashboard_version_info(current_version: Optional[str] = None) -> DashboardVersionInfo:
    resolved_current_version = current_version or get_installed_dashboard_version()
    latest_version = await get_latest_dashboard_version_from_pypi()

    return DashboardVersionInfo(
        current_version=resolved_current_version,
        latest_version=latest_version,
        has_update=is_newer_version(latest_version, resolved_current_version),
    )


def _get_parent_command_line() -> str:
    parent_pid = _get_parent_pid(os.getpid())
    if parent_pid is None:
        return ""
    return _get_process_command_line(parent_pid)


def _get_parent_pid(pid: int) -> Optional[int]:
    if os.name == "nt":
        return _get_windows_parent_pid(pid)
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        stat_text = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    parts = stat_text.split()
    if len(parts) >= 4 and parts[3].isdigit():
        return int(parts[3])
    return None


def _get_process_command_line(pid: int) -> str:
    if os.name == "nt":
        return _get_windows_process_command_line(pid)
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        return cmdline_path.read_text(encoding="utf-8").replace("\x00", " ").strip()
    except OSError:
        return ""


def _get_windows_parent_pid(pid: int) -> Optional[int]:
    output = _run_wmic_query(pid, "ParentProcessId")
    parent_pid = output.get("ParentProcessId")
    if parent_pid and parent_pid.isdigit():
        return int(parent_pid)
    return None


def _get_windows_process_command_line(pid: int) -> str:
    output = _run_wmic_query(pid, "CommandLine")
    return output.get("CommandLine", "")


def _run_wmic_query(pid: int, field: str) -> Dict[str, str]:
    wmic_path = shutil.which("wmic")
    if not wmic_path:
        return {}

    try:
        result = subprocess.run(
            [wmic_path, "process", "where", f"ProcessId={pid}", "get", field, "/format:list"],
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    values = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def detect_package_runner() -> PackageRunner:
    """检测当前进程更像是由 uv 还是 pip/普通 python 启动。"""

    uv_markers = ["UV", "UV_PROJECT_ENVIRONMENT", "UV_RUN_RECURSION_DEPTH"]
    if any(os.getenv(marker) for marker in uv_markers):
        return "uv"

    parent_command = _get_parent_command_line().lower()
    if parent_command:
        executable = parent_command.split(maxsplit=1)[0]
        if executable.endswith("uv.exe") or executable.endswith("/uv") or executable == "uv":
            return "uv"
        if " pip " in f" {parent_command} " or executable.endswith("pip.exe") or executable.endswith("/pip"):
            return "pip"

    if sys.prefix != sys.base_prefix or os.getenv("VIRTUAL_ENV"):
        return "pip"

    return "unknown"


def _build_update_command(runner: PackageRunner) -> list[str]:
    overlay_target = os.getenv(PYTHON_OVERLAY_TARGET_ENV, "").strip()
    if overlay_target:
        base_command = (
            ["uv", "pip", "install", "--python", sys.executable]
            if runner == "uv" and shutil.which("uv")
            else [sys.executable, "-m", "pip", "install"]
        )
        return [
            *base_command,
            "--upgrade",
            "--target",
            overlay_target,
            "--no-compile",
            "--no-warn-script-location",
            DASHBOARD_PACKAGE_NAME,
        ]

    if runner == "uv" and shutil.which("uv"):
        return ["uv", "pip", "install", "--python", sys.executable, "--upgrade", DASHBOARD_PACKAGE_NAME]
    return [sys.executable, "-m", "pip", "install", "--upgrade", DASHBOARD_PACKAGE_NAME]


async def auto_update_dashboard_if_needed() -> DashboardUpdateResult:
    version_info = await get_dashboard_version_info()
    runner = detect_package_runner()
    if not version_info.latest_version:
        return DashboardUpdateResult(
            checked=True,
            updated=False,
            current_version=version_info.current_version,
            latest_version=None,
            runner=runner,
            message="无法获取 WebUI 最新版本，跳过自动更新",
        )
    if not version_info.has_update:
        return DashboardUpdateResult(
            checked=True,
            updated=False,
            current_version=version_info.current_version,
            latest_version=version_info.latest_version,
            runner=runner,
            message="WebUI 已是最新版本",
        )

    update_runner = runner if runner != "unknown" else "pip"
    command = _build_update_command(update_runner)
    overlay_target = os.getenv(PYTHON_OVERLAY_TARGET_ENV, "").strip()
    if overlay_target:
        logger.info(f"WebUI auto update target: {overlay_target}")
    logger.info(
        f"检测到 WebUI 新版本: {version_info.current_version} -> {version_info.latest_version}，"
        f"使用 {update_runner} 自动更新"
    )

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
    except OSError as e:
        logger.warning(f"WebUI 自动更新启动失败: {e}")
        return DashboardUpdateResult(
            checked=True,
            updated=False,
            current_version=version_info.current_version,
            latest_version=version_info.latest_version,
            runner=update_runner,
            message=f"自动更新启动失败: {e}",
        )

    if process.returncode != 0:
        error_text = stderr.decode(errors="ignore").strip() or stdout.decode(errors="ignore").strip()
        logger.warning(f"WebUI 自动更新失败: {error_text}")
        return DashboardUpdateResult(
            checked=True,
            updated=False,
            current_version=version_info.current_version,
            latest_version=version_info.latest_version,
            runner=update_runner,
            message=f"自动更新失败: {error_text}",
        )

    logger.info(f"WebUI 自动更新完成: {version_info.current_version} -> {version_info.latest_version}")
    return DashboardUpdateResult(
        checked=True,
        updated=True,
        current_version=version_info.current_version,
        latest_version=version_info.latest_version,
        runner=update_runner,
        message="WebUI 自动更新完成，重启后生效",
    )
