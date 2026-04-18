"""
memory_service.py — 日/周/月/年摘要生成逻辑 + APScheduler 任务
"""
import json
import logging
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

CST = ZoneInfo('Asia/Shanghai')
def _now_cst(): return datetime.now(CST).replace(tzinfo=None)
from typing import Optional

from database import get_db
from llm_service import chat_complete
from rag_service import index_summary

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 日摘要
# ──────────────────────────────────────────────

DAILY_SUMMARY_PROMPT = """这是 {nickname} 在 {date} 的日记对话，请生成一份简洁的日摘要。

要求：
1. 今天发生了什么（事件，1-2句）
2. 情绪状态（简述）
3. 主要思考或感悟（1-2句）

然后在回复末尾输出一行 JSON（不要加代码块），格式：
{{"emotion_tags": ["标签1","标签2"], "topic_tags": ["话题1","话题2"], "emotion_score": 0.5}}
其中 emotion_score 为 -2 到 2 的小数（-2=极度低落，0=平静，2=非常积极）。

对话内容：
{messages}"""

WEEKLY_SUMMARY_PROMPT = """以下是 {nickname} 在 {week_range} 的日摘要，请提炼一份周摘要。

要求：
1. 本周主题（一句话）
2. 情绪起伏（简述高低点）
3. 反复出现的话题或关注点
4. 成长/变化（如有）

然后在回复末尾输出一行 JSON（不要加代码块），格式：
{{"theme_tags": ["标签1","标签2"]}}

日摘要内容：
{daily_summaries}"""

MONTHLY_SUMMARY_PROMPT = """以下是 {nickname} 在 {year}年{month}月 的周摘要，请提炼一份月摘要。

要求：
1. 本月成长主题
2. 反复出现的模式或关注点
3. 里程碑事件（如有）
4. 给自己的一句话

然后在回复末尾输出一行 JSON（不要加代码块），格式：
{{"milestone_tags": ["里程碑1","里程碑2"]}}

周摘要内容：
{weekly_summaries}"""

YEARLY_SUMMARY_PROMPT = """以下是 {nickname} 在 {year}年 的月摘要，请生成年度回顾。

要求：
1. 年度主题词（2-3个词）
2. 重大转折点
3. 对自己认识的深化
4. 写给来年的一句话

然后在回复末尾输出一行 JSON（不要加代码块），格式：
{{"theme_words": ["主题词1","主题词2"]}}

月摘要内容：
{monthly_summaries}"""

PORTRAIT_UPDATE_PROMPT = """以下是用户 {nickname} 的基本信息和最新画像（如有），结合今天新生成的日摘要，请更新用户画像。

画像应包含：性格特点、近期关注点、情绪模式、成长方向（200字以内）。

基本信息：
{profile}

旧画像（如有）：
{old_portrait}

最新日摘要：
{daily_summary}"""


def _extract_json_tail(text: str) -> dict:
    """从回复末尾提取 JSON 行"""
    import re
    lines = text.strip().splitlines()
    for line in reversed(lines):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                pass
        # 尝试 regex
        m = re.search(r'\{[^{}]+\}', line)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
    return {}


def _clean_summary_text(text: str) -> str:
    """去掉末尾的 JSON 行，返回纯文本摘要"""
    import re
    lines = text.strip().splitlines()
    # 去掉最后一个 JSON 行
    while lines and re.search(r'^\s*\{.*\}\s*$', lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


async def generate_daily_summary(user_id: int, target_date: str) -> bool:
    """为指定用户生成指定日期的日摘要，返回是否成功"""
    with get_db() as conn:
        # 检查是否已有摘要
        exists = conn.execute(
            "SELECT id FROM daily_summaries WHERE user_id=? AND date=?",
            (user_id, target_date),
        ).fetchone()
        if exists:
            return False

        # 获取对话
        conv = conn.execute(
            "SELECT id FROM conversations WHERE user_id=? AND date=?",
            (user_id, target_date),
        ).fetchone()
        if not conv:
            return False

        msgs = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id",
            (conv["id"],),
        ).fetchall()
        if not msgs:
            return False

        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    # 拼接对话文本
    msg_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'AI'}：{m['content']}" for m in msgs
    )
    prompt = DAILY_SUMMARY_PROMPT.format(
        nickname=user["nickname"],
        date=target_date,
        messages=msg_text[:3000],
    )
    resp = await chat_complete(
        [{"role": "user", "content": prompt}],
        use_for="summary",
        user_id=user_id,
    )

    extra = _extract_json_tail(resp)
    content = _clean_summary_text(resp)
    emotion_tags = extra.get("emotion_tags", [])
    topic_tags = extra.get("topic_tags", [])
    emotion_score = float(extra.get("emotion_score", 0))
    emotion_score = max(-2.0, min(2.0, emotion_score))

    now = _now_cst().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO daily_summaries
               (user_id, date, content, emotion_tags, topic_tags, emotion_score, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, target_date, content,
             json.dumps(emotion_tags, ensure_ascii=False),
             json.dumps(topic_tags, ensure_ascii=False),
             emotion_score, now),
        )
        summary_id = cur.lastrowid

    # FTS 索引
    index_summary(
        user_id, "日摘要", summary_id, target_date, content,
        emotion_tags + topic_tags,
    )

    # 尝试更新画像
    await _maybe_update_portrait(user_id, dict(user), content)
    logger.info(f"Daily summary generated: user={user_id} date={target_date}")
    return True


async def generate_weekly_summary(user_id: int, year: int, week: int) -> bool:
    """生成周摘要"""
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM weekly_summaries WHERE user_id=? AND year=? AND week=?",
            (user_id, year, week),
        ).fetchone()
        if exists:
            return False

        # 取该周所有日摘要
        # 周一到周日
        import datetime as dt
        week_start = dt.date.fromisocalendar(year, week, 1)
        week_end = week_start + timedelta(days=6)
        rows = conn.execute(
            """SELECT date, content FROM daily_summaries
               WHERE user_id=? AND date>=? AND date<=?
               ORDER BY date""",
            (user_id, str(week_start), str(week_end)),
        ).fetchall()
        if not rows:
            return False

        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    week_range = f"{week_start} 至 {week_end}"
    daily_text = "\n\n".join(f"【{r['date']}】{r['content']}" for r in rows)
    prompt = WEEKLY_SUMMARY_PROMPT.format(
        nickname=user["nickname"],
        week_range=week_range,
        daily_summaries=daily_text[:4000],
    )
    resp = await chat_complete(
        [{"role": "user", "content": prompt}],
        use_for="summary",
        user_id=user_id,
    )

    extra = _extract_json_tail(resp)
    content = _clean_summary_text(resp)
    theme_tags = extra.get("theme_tags", [])
    now = _now_cst().isoformat()

    with get_db() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO weekly_summaries
               (user_id, year, week, content, theme_tags, created_at)
               VALUES (?,?,?,?,?,?)""",
            (user_id, year, week, content,
             json.dumps(theme_tags, ensure_ascii=False), now),
        )
        summary_id = cur.lastrowid

    index_summary(user_id, "周摘要", summary_id, week_range, content, theme_tags)
    logger.info(f"Weekly summary generated: user={user_id} {year}W{week:02d}")
    return True


async def generate_monthly_summary(user_id: int, year: int, month: int) -> bool:
    """生成月摘要"""
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM monthly_summaries WHERE user_id=? AND year=? AND month=?",
            (user_id, year, month),
        ).fetchone()
        if exists:
            return False

        rows = conn.execute(
            """SELECT year, week, content FROM weekly_summaries
               WHERE user_id=? AND year=?
               ORDER BY week""",
            (user_id, year),
        ).fetchall()
        # 过滤属于该月的周（粗略：含该月的周）
        # 简单策略：取当月日期范围内的周
        import calendar
        _, last_day = calendar.monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)

        import datetime as dt
        filtered = []
        for r in rows:
            ws = dt.date.fromisocalendar(year, r["week"], 1)
            we = ws + timedelta(days=6)
            if ws <= month_end and we >= month_start:
                filtered.append(r)

        if not filtered:
            return False

        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    weekly_text = "\n\n".join(f"【第{r['week']}周】{r['content']}" for r in filtered)
    prompt = MONTHLY_SUMMARY_PROMPT.format(
        nickname=user["nickname"],
        year=year,
        month=month,
        weekly_summaries=weekly_text[:4000],
    )
    resp = await chat_complete(
        [{"role": "user", "content": prompt}],
        use_for="summary",
        user_id=user_id,
    )

    extra = _extract_json_tail(resp)
    content = _clean_summary_text(resp)
    milestone_tags = extra.get("milestone_tags", [])
    now = _now_cst().isoformat()

    with get_db() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO monthly_summaries
               (user_id, year, month, content, milestone_tags, created_at)
               VALUES (?,?,?,?,?,?)""",
            (user_id, year, month, content,
             json.dumps(milestone_tags, ensure_ascii=False), now),
        )
        summary_id = cur.lastrowid

    index_summary(user_id, "月摘要", summary_id, f"{year}年{month}月", content, milestone_tags)
    logger.info(f"Monthly summary generated: user={user_id} {year}-{month:02d}")
    return True


async def generate_yearly_summary(user_id: int, year: int) -> bool:
    """生成年度回顾"""
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM yearly_summaries WHERE user_id=? AND year=?",
            (user_id, year),
        ).fetchone()
        if exists:
            return False

        rows = conn.execute(
            """SELECT year, month, content FROM monthly_summaries
               WHERE user_id=? AND year=?
               ORDER BY month""",
            (user_id, year),
        ).fetchall()
        if not rows:
            return False

        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    monthly_text = "\n\n".join(f"【{r['year']}年{r['month']}月】{r['content']}" for r in rows)
    prompt = YEARLY_SUMMARY_PROMPT.format(
        nickname=user["nickname"],
        year=year,
        monthly_summaries=monthly_text[:5000],
    )
    resp = await chat_complete(
        [{"role": "user", "content": prompt}],
        use_for="summary",
        user_id=user_id,
    )

    extra = _extract_json_tail(resp)
    content = _clean_summary_text(resp)
    theme_words = extra.get("theme_words", [])
    now = _now_cst().isoformat()

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO yearly_summaries
               (user_id, year, content, theme_words, created_at)
               VALUES (?,?,?,?,?)""",
            (user_id, year, content,
             json.dumps(theme_words, ensure_ascii=False), now),
        )

    logger.info(f"Yearly summary generated: user={user_id} {year}")
    return True


async def _maybe_update_portrait(user_id: int, user: dict, daily_summary: str):
    """每5天更新一次画像"""
    try:
        with get_db() as conn:
            latest = conn.execute(
                "SELECT * FROM user_portraits WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()

            # 检查是否距上次更新 >= 5 天
            if latest:
                last_time = datetime.fromisoformat(latest["created_at"])
                if (_now_cst() - last_time).days < 5:
                    return
            old_portrait = latest["content"] if latest else ""
            version = (latest["version"] + 1) if latest else 1

        profile = f"昵称：{user.get('nickname')}，出生年份：{user.get('birth_year')}，性别：{user.get('gender') or '未填写'}，描述：{user.get('self_desc') or '未填写'}"
        prompt = PORTRAIT_UPDATE_PROMPT.format(
            nickname=user.get("nickname"),
            profile=profile,
            old_portrait=old_portrait[:500],
            daily_summary=daily_summary[:800],
        )
        content = await chat_complete(
            [{"role": "user", "content": prompt}],
            use_for="portrait",
            user_id=user_id,
        )
        now = _now_cst().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO user_portraits (user_id, content, version, created_at) VALUES (?,?,?,?)",
                (user_id, content.strip(), version, now),
            )
        logger.info(f"Portrait updated: user={user_id} v{version}")
    except Exception as e:
        logger.warning(f"Portrait update failed: {e}")


# ──────────────────────────────────────────────
# APScheduler 任务
# ──────────────────────────────────────────────

async def run_daily_summaries():
    """每天凌晨2点：为所有有昨日对话的用户生成日摘要"""
    yesterday = (_now_cst() - timedelta(days=1)).strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM conversations WHERE date=?",
            (yesterday,),
        ).fetchall()
    for r in rows:
        try:
            await generate_daily_summary(r["user_id"], yesterday)
        except Exception as e:
            logger.error(f"Daily summary error user={r['user_id']}: {e}")


async def run_weekly_summaries():
    """每周一凌晨2:30：生成上周周摘要"""
    import datetime as dt
    today = dt.date.today()
    last_week = today - timedelta(days=7)
    iso = last_week.isocalendar()
    year, week = iso[0], iso[1]

    with get_db() as conn:
        users = conn.execute("SELECT id FROM users WHERE is_disabled=0").fetchall()
    for u in users:
        try:
            await generate_weekly_summary(u["id"], year, week)
        except Exception as e:
            logger.error(f"Weekly summary error user={u['id']}: {e}")


async def run_monthly_summaries():
    """每月2日凌晨3点：生成上月月摘要"""
    today = _now_cst()
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    with get_db() as conn:
        users = conn.execute("SELECT id FROM users WHERE is_disabled=0").fetchall()
    for u in users:
        try:
            await generate_monthly_summary(u["id"], year, month)
        except Exception as e:
            logger.error(f"Monthly summary error user={u['id']}: {e}")


async def run_yearly_summaries():
    """每年1月2日凌晨4点：生成上年年度回顾"""
    year = _now_cst().year - 1
    with get_db() as conn:
        users = conn.execute("SELECT id FROM users WHERE is_disabled=0").fetchall()
    for u in users:
        try:
            await generate_yearly_summary(u["id"], year)
        except Exception as e:
            logger.error(f"Yearly summary error user={u['id']}: {e}")


async def backfill_daily_summaries():
    """启动时：补生成过去7天缺失的日摘要"""
    today = _now_cst().date()
    for i in range(1, 8):
        target = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        with get_db() as conn:
            rows = conn.execute(
                """SELECT DISTINCT c.user_id FROM conversations c
                   LEFT JOIN daily_summaries ds ON ds.user_id=c.user_id AND ds.date=c.date
                   WHERE c.date=? AND ds.id IS NULL""",
                (target,),
            ).fetchall()
        for r in rows:
            try:
                await generate_daily_summary(r["user_id"], target)
            except Exception as e:
                logger.error(f"Backfill daily summary error user={r['user_id']} date={target}: {e}")
