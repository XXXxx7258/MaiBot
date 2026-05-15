from os import getenv
from typing import Any, Dict
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.common.logger import get_logger

logger = get_logger("webui.plugin_stats_proxy")

router = APIRouter()

PLUGIN_STATS_BASE_URL = getenv("MAIBOT_PLUGIN_STATS_BASE_URL", "http://hyybuth.xyz:10059").rstrip("/")
PLUGIN_STATS_TIMEOUT = float(getenv("MAIBOT_PLUGIN_STATS_TIMEOUT", "8"))


class VoteRequest(BaseModel):
    plugin_id: str = Field(..., min_length=1, max_length=200)
    user_id: str = Field(..., min_length=1, max_length=300)


class RatingRequest(BaseModel):
    plugin_id: str = Field(..., min_length=1, max_length=200)
    user_id: str = Field(..., min_length=1, max_length=300)
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=500)


class DownloadRequest(BaseModel):
    plugin_id: str = Field(..., min_length=1, max_length=200)


async def _request_stats_service(method: str, path: str, payload: Dict[str, Any] | None = None) -> JSONResponse:
    url = f"{PLUGIN_STATS_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=PLUGIN_STATS_TIMEOUT) as client:
            response = await client.request(method, url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning(f"插件统计服务请求失败: {url} - {type(exc).__name__}: {exc!r}")
        raise HTTPException(status_code=502, detail="插件统计服务暂不可用") from exc

    try:
        data = response.json()
    except ValueError as exc:
        logger.warning(f"插件统计服务返回了非 JSON 响应: {url} - status={response.status_code}")
        raise HTTPException(status_code=502, detail="插件统计服务响应格式无效") from exc

    return JSONResponse(status_code=response.status_code, content=data)


@router.get("/stats-proxy/stats/{plugin_id}")
async def get_plugin_stats(plugin_id: str) -> JSONResponse:
    return await _request_stats_service("GET", f"/stats/{quote(plugin_id, safe='')}")


@router.post("/stats-proxy/stats/like")
async def like_plugin(request: VoteRequest) -> JSONResponse:
    return await _request_stats_service("POST", "/stats/like", request.model_dump())


@router.post("/stats-proxy/stats/dislike")
async def dislike_plugin(request: VoteRequest) -> JSONResponse:
    return await _request_stats_service("POST", "/stats/dislike", request.model_dump())


@router.post("/stats-proxy/stats/rate")
async def rate_plugin(request: RatingRequest) -> JSONResponse:
    return await _request_stats_service("POST", "/stats/rate", request.model_dump())


@router.post("/stats-proxy/stats/download")
async def record_plugin_download(request: DownloadRequest) -> JSONResponse:
    return await _request_stats_service("POST", "/stats/download", request.model_dump())
