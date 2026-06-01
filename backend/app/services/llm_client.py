from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


def log_llm_raw_response(label: str, raw: str) -> None:
    settings = get_settings()
    if not settings.llm_debug_log_raw:
        return
    limit = max(200, settings.llm_debug_log_chars)
    preview = raw if len(raw) <= limit else f"{raw[:limit]}\n...<truncated {len(raw) - limit} chars>"
    logger.warning("LLM raw response [%s] (%s chars):\n%s", label, len(raw), preview)


def require_openai_client() -> tuple[OpenAI, str]:
    settings = get_settings()
    api_key = settings.chat_openai_api_key.strip()
    base_url = settings.chat_openai_base_url.strip()
    model = settings.chat_openai_model.strip()
    if not api_key or "你的" in api_key:
        raise ValueError("未配置有效的 CHAT_OPENAI_API_KEY，请在项目根目录 .env 中填写。")
    if not model:
        raise ValueError("未配置 CHAT_OPENAI_MODEL。")

    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": settings.openai_request_timeout_sec,
        "max_retries": settings.openai_max_retries,
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs), model


def require_embedding_client() -> tuple[OpenAI, str]:
    settings = get_settings()
    api_key = (settings.embedding_openai_api_key or settings.chat_openai_api_key).strip()
    base_url = (settings.embedding_openai_base_url or settings.chat_openai_base_url).strip()
    model = settings.embedding_openai_model.strip()
    if not api_key or "你的" in api_key:
        raise ValueError("未配置有效的 EMBEDDING_OPENAI_API_KEY，请在项目根目录 .env 中填写。")
    if not model:
        raise ValueError("未配置 EMBEDDING_OPENAI_MODEL。")

    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": settings.embedding_request_timeout_sec,
        "max_retries": settings.openai_max_retries,
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs), model


def llm_status() -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.chat_openai_api_key.strip()
    model = settings.chat_openai_model.strip()
    base_url = settings.chat_openai_base_url.strip() or "https://api.openai.com/v1"
    configured = bool(api_key and model and "你的" not in api_key)
    provider = "SiliconFlow / OpenAI-compatible" if "siliconflow" in base_url.lower() else "OpenAI-compatible"
    return {
        "configured": configured,
        "api_key_present": bool(api_key),
        "base_url": base_url,
        "model": model,
        "provider": provider,
        "used_for": [
            "PDF/DOCX/TXT 文档知识图谱抽取",
            "文档局部问答与 chunk 级引用",
            "ACLED 全局态势问答",
            "事件链分析文本生成",
        ],
        "message": "大模型已配置，可用于图谱抽取与问答。"
        if configured
        else "尚未配置大模型，请在项目根目录 .env 填写 CHAT_OPENAI_API_KEY、CHAT_OPENAI_BASE_URL、CHAT_OPENAI_MODEL。",
        "embedding": embedding_status(),
    }


def embedding_status() -> dict[str, Any]:
    settings = get_settings()
    api_key = (settings.embedding_openai_api_key or settings.chat_openai_api_key).strip()
    base_url = (settings.embedding_openai_base_url or settings.chat_openai_base_url).strip() or "https://api.openai.com/v1"
    model = settings.embedding_openai_model.strip()
    configured = bool(api_key and model and "你的" not in api_key)
    provider = "SiliconFlow / OpenAI-compatible" if "siliconflow" in base_url.lower() else "OpenAI-compatible"
    return {
        "configured": configured,
        "api_key_present": bool(api_key),
        "base_url": base_url,
        "model": model,
        "provider": provider,
        "used_for": [
            "PDF/DOCX/TXT 文档 chunk 向量化",
            "局部文档问答的语义相似度检索",
            "证据片段召回与引用排序",
        ],
        "message": "embedding 模型已配置，可生成文档向量索引。"
        if configured
        else "尚未配置 embedding 模型；文档问答会退回关键词 + 图谱检索。",
    }


def create_json_chat_completion(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    request = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
        **kwargs,
    }
    if max_tokens is not None:
        request["max_tokens"] = max_tokens
    start = time.perf_counter()
    logger.info(
        "LLM json completion started: model=%s timeout=%s max_tokens=%s",
        model,
        request.get("timeout", "client-default"),
        request.get("max_tokens"),
    )
    try:
        response = client.chat.completions.create(
            **request,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if "response_format" not in str(exc):
            logger.warning("LLM json completion failed after %sms with model=%s: %s", elapsed_ms, model, exc)
            raise
        response = client.chat.completions.create(**request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    raw = response.choices[0].message.content or "{}"
    logger.info("LLM json completion finished in %sms with model=%s", elapsed_ms, model)
    log_llm_raw_response("json_chat_completion", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型返回非合法 JSON：{raw[:200]}...") from exc


def test_llm_connection() -> dict[str, Any]:
    client, model = require_openai_client()
    settings = get_settings()
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        max_tokens=64,
        messages=[
            {"role": "system", "content": "你是一个连接测试助手。"},
            {"role": "user", "content": "请只回复：模型连接正常"},
        ],
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "ok": True,
        "model": model,
        "base_url": settings.chat_openai_base_url.strip() or "https://api.openai.com/v1",
        "reply": response.choices[0].message.content or "",
        "latency_ms": elapsed_ms,
    }


def test_embedding_connection() -> dict[str, Any]:
    client, model = require_embedding_client()
    settings = get_settings()
    start = time.perf_counter()
    response = client.embeddings.create(
        model=model,
        input=["俄乌冲突公开事件检索测试"],
    )
    vector = response.data[0].embedding
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return {
        "ok": True,
        "model": model,
        "base_url": (settings.embedding_openai_base_url or settings.chat_openai_base_url).strip()
        or "https://api.openai.com/v1",
        "dimension": len(vector),
        "latency_ms": elapsed_ms,
    }
