"""
llm_service.py — LLM 调用封装（支持多 provider，OpenAI 兼容接口）
"""
import json
import logging
from datetime import datetime
from typing import AsyncIterator, Optional

from openai import AsyncOpenAI

from database import get_db

logger = logging.getLogger(__name__)


def get_llm_config(use_for: str = None) -> Optional[dict]:
    """从数据库获取活跃的 LLM 配置（全局唯一激活配置）"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM llm_configs WHERE is_active=1 ORDER BY id DESC LIMIT 1",
        ).fetchone()
    return dict(row) if row else None


def get_openai_client(config: dict) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=config["api_key"],
        base_url=config.get("base_url") or None,
    )


async def chat_stream(
    messages: list,
    user_id: Optional[int] = None,
) -> AsyncIterator[str]:
    """流式对话，yield 文本片段"""
    config = get_llm_config(use_for)
    if not config:
        yield "【LLM 配置未找到，请联系管理员】"
        return

    client = get_openai_client(config)
    input_tokens = 0
    output_tokens = 0
    try:
        stream = await client.chat.completions.create(
            model=config["model_name"],
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                output_tokens += 1  # 估算
                yield delta.content
            # 尝试读取 usage（最后一个 chunk）
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = chunk.usage.prompt_tokens or 0
                output_tokens = chunk.usage.completion_tokens or 0
    except Exception as e:
        logger.error(f"LLM chat_stream error: {e}")
        yield f"\n\n【AI 暂时无法响应：{str(e)[:100]}】"
    finally:
        _log_llm_call(user_id, use_for, config["model_name"], input_tokens, output_tokens)


async def chat_complete(
    messages: list,
    use_for: str = "chat",
    user_id: Optional[int] = None,
) -> str:
    """非流式对话，返回完整文本"""
    config = get_llm_config(use_for)
    if not config:
        return "【LLM 配置未找到】"

    client = get_openai_client(config)
    try:
        resp = await client.chat.completions.create(
            model=config["model_name"],
            messages=messages,
            stream=False,
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        _log_llm_call(user_id, use_for, config["model_name"],
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
        )
        return text
    except Exception as e:
        logger.error(f"LLM chat_complete error: {e}")
        return f"【AI 调用失败：{str(e)[:100]}】"


def _log_llm_call(user_id, use_for, model_name, input_tokens, output_tokens):
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO llm_call_logs
                   (user_id, use_for, model_name, input_tokens, output_tokens, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, "global", model_name, input_tokens, output_tokens,
                 datetime.utcnow().isoformat()),
            )
    except Exception as e:
        logger.warning(f"Failed to log LLM call: {e}")
