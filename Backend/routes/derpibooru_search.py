"""Authenticated Derpibooru browser with LLM natural-language tag translation."""
from __future__ import annotations

import json
import re
import asyncio
import random
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from ..chat_modules.derpibooru_images import RATINGS, search_ranked
from ..chat_modules.twibooru_images import search_ranked as search_twibooru
from ..config import logger, model_manager
from ..providers.llm_call import call_llm_payload
from ..reasoning_policy import ReasoningPolicy
from .auth import auth_token_verify

router = APIRouter(prefix="/api/derpibooru", tags=["Derpibooru"])


class SearchRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=300)
    mode: Literal["natural", "tags"] = "natural"
    rating: str = "safe"
    sort: Literal["time", "score", "random"] = "score"
    page: int = Field(default=1, ge=1, le=1000)


def _json_object(text: str) -> dict:
    raw = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
    if fenced:
        raw = fenced.group(1).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end >= start:
        return json.loads(raw[start:end + 1])
    raise ValueError("No JSON object")


def _clean_tags(value) -> list[str]:
    source = value if isinstance(value, list) else str(value or "").split(",")
    result = []
    for item in source:
        tag = re.sub(r"\s+", " ", str(item).strip().lower().replace("_", " "))
        if (re.fullmatch(r"-?[a-z0-9][a-z0-9 '()_-]{0,79}", tag)
                and not re.search(r'\b(or|not|and)\b', tag)
                and tag.lstrip('-') not in RATINGS and tag not in result):
            result.append(tag)
    return result[:12]


async def translate_query(query: str, username: str) -> tuple[list[str], str]:
    model = model_manager.get_model_for_task("web_search") or model_manager.get_active_model()
    if not model or not model.get("api_key"):
        raise RuntimeError("No image-search model")
    model_name = str(model.get("model_name") or model.get("id") or "")
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": (
                "Convert a user's natural-language pony image request into Derpibooru tags. "
                "Return JSON only: {\"tags\":[\"english tag\",...],\"rating\":\"safe\"}. "
                "Use existing concise English "
                "character, action, scene and style tags. Preserve exclusions with a leading minus, "
                "for example no animation means -animated. Choose exactly one content rating from safe, "
                "suggestive, questionable, explicit, semi-grimdark, grimdark, or grotesque according to "
                "the image content the user actually requests. Use safe when no sexual, violent, disturbing, "
                "or dark content is requested. Do not infer a dark rating merely from words such as night or "
                "dark colors. Do not include ratings inside tags, boolean syntax, URLs, explanations, or "
                "invented prose. Preserve the requested subject and important constraints.")},
            {"role": "user", "content": query},
        ],
        "stream": False,
        "temperature": 0.1,
        "max_tokens": 220,
        "max_completion_tokens": 220,
        "response_format": {"type": "json_object"},
    }
    result = await call_llm_payload(payload, model, task="web_search", timeout=30.0,
        reasoning_policy=ReasoningPolicy(), record_usage="main", usage_meter_username=username)
    translated = _json_object(result.text)
    tags = _clean_tags(translated.get("tags"))
    if not tags:
        raise ValueError("Model returned no valid tags")
    rating = str(translated.get("rating") or "").strip().lower()
    if rating not in RATINGS:
        raise ValueError("Model returned no valid rating")
    return tags, rating


async def _authenticated_username(username: str, token: Optional[str], x_username: Optional[str]) -> str:
    claimed = username.strip()
    actual = await auth_token_verify((token or "").removeprefix("Bearer ").strip())
    if not actual or actual != claimed or (x_username and x_username.strip() != claimed):
        raise HTTPException(status_code=401, detail="登录状态已失效")
    return claimed


def _mix_results(derpi: list[dict], twi: list[dict], sort: str) -> list[dict]:
    if sort == "random":
        rows = [*derpi, *twi]
        random.shuffle(rows)
        return rows
    rows = []
    for index in range(max(len(derpi), len(twi))):
        if index < len(derpi):
            rows.append(derpi[index])
        if index < len(twi):
            rows.append(twi[index])
    return rows


async def _filter_known_tags(tags: list[str], transport=None) -> list[str]:
    """Drop a tag only when both boorus confirm that it does not exist."""
    endpoints = (
        "https://derpibooru.org/api/v1/json/search/tags",
        "https://twibooru.org/api/v3/search/tags",
    )

    async def exists(client: httpx.AsyncClient, endpoint: str, tag: str) -> Optional[bool]:
        name = tag.lstrip("-")
        try:
            response = await client.get(endpoint, params={"q": f"name:{name}", "per_page": 10})
            response.raise_for_status()
            if len(response.content) > 400_000:
                return None
            rows = response.json().get("tags", [])
            for row in rows:
                if not isinstance(row, dict):
                    continue
                names = [row.get("name"), *(row.get("aliases") or [])]
                if name in {str(value or "").strip().lower() for value in names}:
                    return True
            return False
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            return None

    async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=6,
            follow_redirects=False, limits=httpx.Limits(max_connections=8)) as client:
        checks = await asyncio.gather(*(
            exists(client, endpoint, tag) for tag in tags for endpoint in endpoints
        ))
    filtered = []
    for index, tag in enumerate(tags):
        pair = checks[index * len(endpoints):(index + 1) * len(endpoints)]
        # Fail open on provider errors; only two authoritative misses remove a tag.
        if True in pair or None in pair:
            filtered.append(tag)
    return filtered


@router.post("/search")
async def search(request: SearchRequest, authorization: Optional[str] = Header(None),
                 x_chat_auth: Optional[str] = Header(None), x_username: Optional[str] = Header(None)):
    username = await _authenticated_username(request.username, x_chat_auth or authorization, x_username)
    if request.rating not in RATINGS:
        raise HTTPException(status_code=400, detail="不支持的图片等级")
    try:
        if request.mode == "natural":
            tags, rating = await translate_query(request.query, username)
        else:
            tags, rating = _clean_tags(request.query), request.rating
        if not tags:
            raise HTTPException(status_code=400, detail="请输入有效的英文标签")
        derpi, twi = await asyncio.gather(
            search_ranked(", ".join(tags), rating=rating,
                sort=request.sort, page=request.page, limit=9, browser_media=True),
            search_twibooru(", ".join(tags), rating=rating,
                sort=request.sort, page=request.page, limit=9),
        )
        rows = _mix_results(derpi, twi, request.sort)
        if request.mode == "natural" and request.page == 1 and not rows:
            filtered_tags = await _filter_known_tags(tags)
            if filtered_tags != tags:
                tags = filtered_tags
                if tags:
                    derpi, twi = await asyncio.gather(
                        search_ranked(", ".join(tags), rating=rating,
                            sort=request.sort, page=request.page, limit=9, browser_media=True),
                        search_twibooru(", ".join(tags), rating=rating,
                            sort=request.sort, page=request.page, limit=9),
                    )
                    rows = _mix_results(derpi, twi, request.sort)
        return {"status": "ok", "tags": tags, "rating": rating,
                "sort": request.sort, "page": request.page, "sources": ["Derpibooru", "Twibooru"],
                "has_more": bool(derpi or twi), "images": rows}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[DerpibooruBrowser] search failed: %s", exc)
        raise HTTPException(status_code=502, detail="找图服务暂时不可用") from exc
