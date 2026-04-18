"""
stt_service.py — STT 调用封装（faster-whisper 本地 + API fallback）
"""
import os
import logging
import tempfile
from typing import Optional

from database import get_db

logger = logging.getLogger(__name__)

_whisper_model = None
_whisper_model_name = None


def get_stt_config() -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM stt_configs WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _get_whisper_model(model_name: str = "small"):
    global _whisper_model, _whisper_model_name
    if _whisper_model is None or _whisper_model_name != model_name:
        try:
            from faster_whisper import WhisperModel
            logger.info(f"Loading faster-whisper model: {model_name}")
            _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _whisper_model_name = model_name
            logger.info("faster-whisper model loaded")
        except Exception as e:
            logger.error(f"Failed to load faster-whisper: {e}")
            _whisper_model = None
    return _whisper_model


async def transcribe_audio(audio_bytes: bytes, filename: str, user_id: Optional[int] = None) -> str:
    """将音频字节流转为文字"""
    config = get_stt_config()
    if not config:
        return ""

    provider = config.get("provider", "faster-whisper")

    if provider == "faster-whisper":
        return await _transcribe_local(audio_bytes, filename, config, user_id)
    elif provider == "openai":
        return await _transcribe_openai(audio_bytes, filename, config, user_id)
    else:
        logger.warning(f"Unknown STT provider: {provider}, falling back to faster-whisper")
        return await _transcribe_local(audio_bytes, filename, config, user_id)


async def _transcribe_local(audio_bytes: bytes, filename: str, config: dict, user_id) -> str:
    model_name = config.get("model_name", "small")
    model = _get_whisper_model(model_name)
    if not model:
        return "【STT 服务不可用，请检查 faster-whisper 安装】"

    # 写临时文件
    suffix = os.path.splitext(filename)[-1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        import asyncio
        import time

        def do_transcribe():
            t0 = time.time()
            segs, info = model.transcribe(tmp_path, language="zh")
            text = " ".join(s.text.strip() for s in segs)
            duration = time.time() - t0
            return text, duration

        loop = asyncio.get_event_loop()
        text, duration = await loop.run_in_executor(None, do_transcribe)

        _log_stt_call(user_id, duration, "faster-whisper")
        return text.strip()
    except Exception as e:
        logger.error(f"Local STT error: {e}")
        return "【语音识别失败，请重试】"
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


async def _transcribe_openai(audio_bytes: bytes, filename: str, config: dict, user_id) -> str:
    try:
        from openai import AsyncOpenAI
        import time

        client = AsyncOpenAI(
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url") or None,
        )
        suffix = os.path.splitext(filename)[-1] or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name

        try:
            t0 = time.time()
            with open(tmp_path, "rb") as af:
                resp = await client.audio.transcriptions.create(
                    model=config.get("model_name", "whisper-1"),
                    file=af,
                    language="zh",
                )
            duration = time.time() - t0
            _log_stt_call(user_id, duration, "openai")
            return resp.text.strip()
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        logger.error(f"OpenAI STT error: {e}")
        return "【语音识别失败，请重试】"


def _log_stt_call(user_id, duration_seconds, provider):
    try:
        from datetime import datetime
        with get_db() as conn:
            conn.execute(
                "INSERT INTO stt_call_logs (user_id, duration_seconds, provider, created_at) VALUES (?,?,?,?)",
                (user_id, duration_seconds, provider, datetime.utcnow().isoformat()),
            )
    except Exception as e:
        logger.warning(f"Failed to log STT call: {e}")
