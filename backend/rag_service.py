"""
rag_service.py — FTS 检索，召回相关摘要片段注入 System Prompt
"""
import json
import logging
from typing import Optional

from database import get_db

logger = logging.getLogger(__name__)


def index_summary(user_id: int, summary_type: str, ref_id: int, date_label: str, content: str, tags: list):
    """将摘要写入 FTS 索引"""
    try:
        with get_db() as conn:
            # 先删旧索引
            conn.execute(
                "DELETE FROM summaries_fts WHERE user_id=? AND summary_type=? AND ref_id=?",
                (user_id, summary_type, ref_id),
            )
            conn.execute(
                "INSERT INTO summaries_fts (user_id, summary_type, ref_id, date_label, content, tags) VALUES (?,?,?,?,?,?)",
                (user_id, summary_type, ref_id, date_label, content, json.dumps(tags, ensure_ascii=False)),
            )
    except Exception as e:
        logger.warning(f"FTS index error: {e}")


def search_summaries(user_id: int, query: str, limit: int = 5) -> str:
    """FTS 检索，返回相关片段文本"""
    if not query or len(query.strip()) < 2:
        return ""
    try:
        with get_db() as conn:
            # FTS5 匹配，过滤用户
            rows = conn.execute(
                """SELECT date_label, content, summary_type
                   FROM summaries_fts
                   WHERE user_id=? AND summaries_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (user_id, query.strip(), limit),
            ).fetchall()
        if not rows:
            return ""
        parts = []
        for r in rows:
            parts.append(f"[{r['summary_type']} · {r['date_label']}]\n{r['content'][:300]}")
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"FTS search error: {e}")
        return ""


def build_system_prompt(user: dict, last_message: str = "") -> str:
    """构建完整 System Prompt"""
    import json
    from datetime import datetime

    now_year = datetime.utcnow().year
    age = now_year - (user.get("birth_year") or now_year)

    if age < 30:
        age_style = "语气平等、活泼、接地气，像同龄朋友一样交流"
    elif age < 45:
        age_style = "语气沉稳、有深度、注重实践，给予成熟的建议"
    else:
        age_style = "语气温和、尊重，不说教，充分肯定人生经验"

    tags = user.get("personality_tags", "[]")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except Exception:
            tags = []

    # 获取近期摘要
    daily_ctx = _get_recent_daily(user["id"])
    weekly_ctx = _get_recent_weekly(user["id"])
    monthly_ctx = _get_recent_monthly(user["id"])

    # RAG 检索
    rag_ctx = ""
    if last_message:
        rag_ctx = search_summaries(user["id"], last_message[:100])

    parts = [
        """[身份]
你是「言己」的 AI 伴侣，一位博学的智者——既是导师，也是朋友。
你了解这位用户，你的目标是陪伴 ta 记录生活、整理思绪、看见成长。""",

        f"""[对话原则]
- 先感受情绪，再给建议；承接情绪，不急着解决
- 适时反问，引导用户自己找答案，而不是给标准答案
- {age_style}
- 鼓励为主，看见 ta 的进步，说出来
- 不说教，不评判，不给"正确答案"
- 回复长度适中，不要过于啰嗦""",

        f"""[用户档案]
昵称：{user.get('nickname', '用户')}
年龄：{age} 岁（{user.get('birth_year', '')} 年生，{user.get('birth_month', '')} 月）
性别：{user.get('gender') or '未填写'}
一句话描述：{user.get('self_desc') or '未填写'}
性格标签：{', '.join(tags) if tags else '暂无'}""",
    ]

    if daily_ctx:
        parts.append(f"[近期记忆 — 最近几日]\n{daily_ctx}")
    if weekly_ctx:
        parts.append(f"[近期记忆 — 近期周回顾]\n{weekly_ctx}")
    if monthly_ctx:
        parts.append(f"[近期记忆 — 本月回顾]\n{monthly_ctx}")
    if rag_ctx:
        parts.append(f"[相关历史记忆（智能检索）]\n{rag_ctx}")

    return "\n\n".join(parts)


def _get_recent_daily(user_id: int, n: int = 3) -> str:
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT date, content FROM daily_summaries WHERE user_id=? ORDER BY date DESC LIMIT ?",
                (user_id, n),
            ).fetchall()
        if not rows:
            return ""
        parts = [f"【{r['date']}】{r['content'][:400]}" for r in reversed(rows)]
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"get_recent_daily error: {e}")
        return ""


def _get_recent_weekly(user_id: int, n: int = 2) -> str:
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT year, week, content FROM weekly_summaries WHERE user_id=? ORDER BY year DESC, week DESC LIMIT ?",
                (user_id, n),
            ).fetchall()
        if not rows:
            return ""
        parts = [f"【{r['year']}年第{r['week']}周】{r['content'][:400]}" for r in reversed(rows)]
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"get_recent_weekly error: {e}")
        return ""


def _get_recent_monthly(user_id: int, n: int = 1) -> str:
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT year, month, content FROM monthly_summaries WHERE user_id=? ORDER BY year DESC, month DESC LIMIT ?",
                (user_id, n),
            ).fetchall()
        if not rows:
            return ""
        parts = [f"【{r['year']}年{r['month']}月】{r['content'][:500]}" for r in reversed(rows)]
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning(f"get_recent_monthly error: {e}")
        return ""
