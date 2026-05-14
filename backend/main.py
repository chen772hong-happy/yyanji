"""
main.py — FastAPI 主程序，路由、定时任务
"""
import json
import logging
import os
import random
import string
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

CST = ZoneInfo('Asia/Shanghai')
def _now_cst(): return datetime.now(CST).replace(tzinfo=None)
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from auth import (
    create_token,
    get_current_admin,
    get_current_user,
    hash_password,
    verify_password,
    ACCESS_TOKEN_EXPIRE_DAYS,
    ADMIN_TOKEN_EXPIRE_HOURS,
)
from database import get_db, init_db
from llm_service import chat_stream, chat_complete
from memory_service import (
    backfill_daily_summaries,
    generate_daily_summary,
    generate_weekly_summary,
    generate_monthly_summary,
    generate_yearly_summary,
    run_daily_summaries,
    run_monthly_summaries,
    run_weekly_summaries,
    run_yearly_summaries,
    )
from rag_service import build_system_prompt
from stt_service import transcribe_audio
from backup_service import run_daily_backup, run_monthly_backup
from optimization_service import run_weekly_optimization, run_daily_maintenance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

FREE_MONTHLY_LIMIT = 20


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # 启动补历史摘要（异步）
    import asyncio
    asyncio.create_task(backfill_daily_summaries())

    # APScheduler
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    # 每天凌晨 01:30 日摘要（在1-3点窗口内）
    scheduler.add_job(run_daily_summaries, "cron", hour=1, minute=30)
    # 每周一 02:00 周摘要（在1-3点窗口内）
    scheduler.add_job(run_weekly_summaries, "cron", day_of_week="mon", hour=2, minute=0)
    # 每月2日 02:30 月摘要（在1-3点窗口内）
    scheduler.add_job(run_monthly_summaries, "cron", day=2, hour=2, minute=30)
    # 每年1月2日 02:45 年度回顾（在1-3点窗口内）
    scheduler.add_job(run_yearly_summaries, "cron", month=1, day=2, hour=2, minute=45)
    
    # 数据库备份任务
    # 每天凌晨 02:50 每日备份（摘要任务完成后）
    scheduler.add_job(run_daily_backup, "cron", hour=2, minute=50)
    # 每月1日 02:55 每月备份
    scheduler.add_job(run_monthly_backup, "cron", day=1, hour=2, minute=55)
    
    # 系统优化任务
    # 每天凌晨 03:10 每日维护
    scheduler.add_job(run_daily_maintenance, "cron", hour=3, minute=10)
    # 每周日 03:30 每周优化
    scheduler.add_job(run_weekly_optimization, "cron", day_of_week="sun", hour=3, minute=30)
    
    scheduler.start()
    logger.info("Scheduler started - 所有任务安排在凌晨1-4点之间")
    yield
    scheduler.shutdown()


app = FastAPI(title="言己 API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 挂载前端
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/app", StaticFiles(directory=frontend_dir, html=True), name="frontend")

# 后台管理页
@app.get("/admin")
async def admin_page():
    return FileResponse(os.path.join(static_dir, "admin.html"))

# 前台根路径重定向到前端
@app.get("/")
async def root():
    return FileResponse(os.path.join(frontend_dir, "index.html"))


# ══════════════════════════════════════════════
# Pydantic models
# ══════════════════════════════════════════════

class RegisterReq(BaseModel):
    phone: str
    password: str
    nickname: str
    birth_year: int
    birth_month: int
    invite_code: str
    birth_day: Optional[int] = None
    birth_hour: Optional[str] = None
    gender: Optional[str] = None
    self_desc: Optional[str] = None


class LoginReq(BaseModel):
    phone: str
    password: str


class SendMessageReq(BaseModel):
    content: str


class UpdateMeReq(BaseModel):
    nickname: Optional[str] = None
    self_desc: Optional[str] = None
    personality_tags: Optional[list] = None


class ActivateCodeReq(BaseModel):
    code: str


class AdminLoginReq(BaseModel):
    username: str
    password: str


class GenerateCodesReq(BaseModel):
    count: int = 10
    duration_days: int = 30
    batch_tag: Optional[str] = None
    expires_days: Optional[int] = None


class LLMConfigReq(BaseModel):
    use_for: str = "global"  # 保留字段用于兼容，固定值
    provider: str = "openai_compat"
    model_name: str
    api_key: str
    base_url: Optional[str] = None
    is_active: int = 1
    notes: Optional[str] = None


class STTConfigReq(BaseModel):
    provider: str = "faster-whisper"
    model_name: str = "small"
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_active: int = 1
    notes: Optional[str] = None


class UserStatusReq(BaseModel):
    is_disabled: int


# ══════════════════════════════════════════════
# Auth endpoints
# ══════════════════════════════════════════════

@app.post("/api/auth/register")
async def register(req: RegisterReq):
    with get_db() as conn:
        # 验证使用码
        code_row = conn.execute(
            "SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL",
            (req.invite_code,),
        ).fetchone()
        if not code_row:
            raise HTTPException(400, "使用码无效或已被使用")
        if code_row["expires_at"] and code_row["expires_at"] < _now_cst().isoformat():
            raise HTTPException(400, "使用码已过期")

        # 检查手机号
        if conn.execute("SELECT id FROM users WHERE phone=?", (req.phone,)).fetchone():
            raise HTTPException(400, "手机号已注册")

        now = _now_cst().isoformat()
        # 创建用户
        cur = conn.execute(
            """INSERT INTO users (phone, password_hash, nickname, birth_year, birth_month, birth_day,
               birth_hour, gender, self_desc, created_at, last_active_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (req.phone, hash_password(req.password), req.nickname,
             req.birth_year, req.birth_month, req.birth_day, req.birth_hour,
             req.gender, req.self_desc, now, now),
        )
        user_id = cur.lastrowid

        # 激活订阅
        expire_at = (_now_cst() + timedelta(days=code_row["duration_days"])).isoformat()
        conn.execute(
            "INSERT INTO subscriptions (user_id, plan, expire_at, created_at) VALUES (?,?,?,?)",
            (user_id, "paid", expire_at, now),
        )

        # 标记使用码
        conn.execute(
            "UPDATE invite_codes SET used_by=?, used_at=? WHERE id=?",
            (user_id, now, code_row["id"]),
        )

        # 初始化配额
        year_month = _now_cst().strftime("%Y-%m")
        conn.execute(
            "INSERT OR IGNORE INTO usage_quotas (user_id, year_month, chat_count, reset_at) VALUES (?,?,0,?)",
            (user_id, year_month, now),
        )

    token = create_token({"sub": str(user_id), "type": "user"})
    return {"token": token, "user_id": user_id, "nickname": req.nickname}


@app.post("/api/auth/login")
async def login(req: LoginReq):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE phone=?", (req.phone,)).fetchone()
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(400, "手机号或密码错误")
    if user["is_disabled"]:
        raise HTTPException(403, "账号已被禁用")

    with get_db() as conn:
        conn.execute("UPDATE users SET last_active_at=? WHERE id=?",
                     (_now_cst().isoformat(), user["id"]))

    token = create_token({"sub": str(user["id"]), "type": "user"})
    return {"token": token, "user_id": user["id"], "nickname": user["nickname"]}


@app.get("/api/me")
async def get_me(user=Depends(get_current_user)):
    with get_db() as conn:
        sub = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=?", (user["id"],)
        ).fetchone()
    user_data = {k: user[k] for k in user.keys()}
    user_data["subscription"] = dict(sub) if sub else None
    return user_data


@app.put("/api/me")
async def update_me(req: UpdateMeReq, user=Depends(get_current_user)):
    fields = {}
    if req.nickname is not None:
        fields["nickname"] = req.nickname
    if req.self_desc is not None:
        fields["self_desc"] = req.self_desc
    if req.personality_tags is not None:
        fields["personality_tags"] = json.dumps(req.personality_tags, ensure_ascii=False)
    if not fields:
        return {"ok": True}
    set_clause = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [user["id"]]
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", vals)
    return {"ok": True}


# ══════════════════════════════════════════════
# Conversations
# ══════════════════════════════════════════════

def _get_or_create_today_conv(user_id: int, conn) -> dict:
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT * FROM conversations WHERE user_id=? AND date=?", (user_id, today)
    ).fetchone()
    if row:
        return dict(row)
    now = _now_cst().isoformat()
    cur = conn.execute(
        "INSERT INTO conversations (user_id, date, title, created_at) VALUES (?,?,?,?)",
        (user_id, today, f"{today} 的对话", now),
    )
    return {"id": cur.lastrowid, "user_id": user_id, "date": today, "title": f"{today} 的对话", "created_at": now}


@app.get("/api/conversations/today")
async def get_today_conv(user=Depends(get_current_user)):
    with get_db() as conn:
        conv = _get_or_create_today_conv(user["id"], conn)
        msgs = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id",
            (conv["id"],),
        ).fetchall()
    return {"conversation": conv, "messages": [dict(m) for m in msgs]}


@app.get("/api/conversations/{conv_date}")
async def get_conv_by_date(conv_date: str, user=Depends(get_current_user)):
    with get_db() as conn:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE user_id=? AND date=?",
            (user["id"], conv_date),
        ).fetchone()
        if not conv:
            raise HTTPException(404, "该日期无对话")
        msgs = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY id",
            (conv["id"],),
        ).fetchall()
    return {"conversation": dict(conv), "messages": [dict(m) for m in msgs]}


@app.get("/api/conversations")
async def list_conversation_dates(user=Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date FROM conversations WHERE user_id=? ORDER BY date DESC",
            (user["id"],),
        ).fetchall()
    return {"dates": [r["date"] for r in rows]}


def _check_quota(user_id: int) -> bool:
    """检查免费用量。True = 可以发，False = 超限"""
    with get_db() as conn:
        sub = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=?", (user_id,)
        ).fetchone()
        if sub and sub["expire_at"] and sub["expire_at"] > _now_cst().isoformat():
            return True  # 付费订阅有效

        year_month = _now_cst().strftime("%Y-%m")
        quota = conn.execute(
            "SELECT chat_count FROM usage_quotas WHERE user_id=? AND year_month=?",
            (user_id, year_month),
        ).fetchone()
        count = quota["chat_count"] if quota else 0
        return count < FREE_MONTHLY_LIMIT


def _inc_quota(user_id: int):
    year_month = _now_cst().strftime("%Y-%m")
    now = _now_cst().isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO usage_quotas (user_id, year_month, chat_count, reset_at)
               VALUES (?,?,1,?)
               ON CONFLICT(user_id, year_month) DO UPDATE SET chat_count=chat_count+1""",
            (user_id, year_month, now),
        )


@app.post("/api/conversations/{conv_id}/messages")
async def send_message(conv_id: int, req: SendMessageReq, user=Depends(get_current_user)):
    # 配额检查
    if not _check_quota(user["id"]):
        raise HTTPException(429, f"本月免费对话次数（{FREE_MONTHLY_LIMIT}次）已用完，请兑换使用码")

    with get_db() as conn:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE id=? AND user_id=?",
            (conv_id, user["id"]),
        ).fetchone()
        if not conv:
            raise HTTPException(404, "对话不存在")

        # 历史消息（最近30条）
        hist = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT 30",
            (conv_id,),
        ).fetchall()
        hist = list(reversed(hist))

    # 存用户消息
    now = _now_cst().isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (conversation_id, user_id, role, content, created_at) VALUES (?,?,?,?,?)",
            (conv_id, user["id"], "user", req.content, now),
        )

    # 构建 System Prompt
    system_prompt = build_system_prompt(user, req.content)
    messages = [{"role": "system", "content": system_prompt}]
    for m in hist:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": req.content})

    _inc_quota(user["id"])

    async def generate():
        ai_content = []
        async for chunk in chat_stream(messages, user_id=user["id"]):
            ai_content.append(chunk)
            yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"

        full_content = "".join(ai_content)
        msg_now = _now_cst().isoformat()
        with get_db() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, user_id, role, content, created_at) VALUES (?,?,?,?,?)",
                (conv_id, user["id"], "assistant", full_content, msg_now),
            )
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ══════════════════════════════════════════════
# STT
# ══════════════════════════════════════════════

@app.post("/api/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    user=Depends(get_current_user),
):
    from stt_service import get_stt_config
    config = get_stt_config()
    if not config:
        raise HTTPException(status_code=503, detail={"no_asr": True, "error": "STT 服务未配置"})
    data = await audio.read()
    text = await transcribe_audio(data, audio.filename or "audio.webm", user["id"])
    if not text:
        raise HTTPException(status_code=422, detail={"error": "未识别到语音内容，请重试"})
    return {"text": text}


# ══════════════════════════════════════════════
# Summaries
# ══════════════════════════════════════════════

@app.get("/api/summaries/daily")
async def get_daily_summaries(year: int = None, month: int = None, user=Depends(get_current_user)):
    now = _now_cst()
    year = year or now.year
    month = month or now.month
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_summaries WHERE user_id=? AND date LIKE ?
               ORDER BY date DESC""",
            (user["id"], f"{year}-{month:02d}-%"),
        ).fetchall()
    return {"summaries": [dict(r) for r in rows]}


@app.get("/api/summaries/weekly")
async def get_weekly_summaries(year: int = None, user=Depends(get_current_user)):
    year = year or _now_cst().year
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM weekly_summaries WHERE user_id=? AND year=? ORDER BY week DESC",
            (user["id"], year),
        ).fetchall()
    return {"summaries": [dict(r) for r in rows]}


@app.get("/api/summaries/monthly")
async def get_monthly_summaries(year: int = None, user=Depends(get_current_user)):
    year = year or _now_cst().year
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM monthly_summaries WHERE user_id=? AND year=? ORDER BY month DESC",
            (user["id"], year),
        ).fetchall()
    return {"summaries": [dict(r) for r in rows]}


@app.get("/api/summaries/yearly")
async def get_yearly_summaries(user=Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM yearly_summaries WHERE user_id=? ORDER BY year DESC",
            (user["id"],),
        ).fetchall()
    return {"summaries": [dict(r) for r in rows]}


@app.get("/api/summaries/recent")
async def get_recent_summaries(n: int = 10, user=Depends(get_current_user)):
    with get_db() as conn:
        daily = conn.execute(
            "SELECT * FROM daily_summaries WHERE user_id=? ORDER BY date DESC LIMIT ?",
            (user["id"], n),
        ).fetchall()
        weekly = conn.execute(
            "SELECT * FROM weekly_summaries WHERE user_id=? ORDER BY year DESC, week DESC LIMIT 4",
            (user["id"],),
        ).fetchall()
        monthly = conn.execute(
            "SELECT * FROM monthly_summaries WHERE user_id=? ORDER BY year DESC, month DESC LIMIT 3",
            (user["id"],),
        ).fetchall()
    return {
        "daily": [dict(r) for r in daily],
        "weekly": [dict(r) for r in weekly],
        "monthly": [dict(r) for r in monthly],
    }


@app.get("/api/summaries/emotion_trend")
async def get_emotion_trend(days: int = 30, user=Depends(get_current_user)):
    """返回情绪趋势数据（用于折线图）"""
    since = (_now_cst() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute(
            """SELECT date, emotion_score, emotion_tags FROM daily_summaries
               WHERE user_id=? AND date >= ?
               ORDER BY date""",
            (user["id"], since),
        ).fetchall()
    return {"trend": [dict(r) for r in rows]}


@app.get("/api/summaries/current-week")
async def get_current_week_summaries(user=Depends(get_current_user)):
    """获取本周的每天摘要"""
    now = _now_cst()
    # 计算本周的开始（周一）和结束（周日）
    today = now.date()
    week_start = today - timedelta(days=today.weekday())  # 周一
    week_end = week_start + timedelta(days=6)  # 周日
    
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_summaries 
               WHERE user_id=? AND date BETWEEN ? AND ?
               ORDER BY date DESC""",
            (user["id"], week_start.isoformat(), week_end.isoformat()),
        ).fetchall()
    return {"summaries": [dict(r) for r in rows], "week_start": week_start.isoformat(), "week_end": week_end.isoformat()}


@app.get("/api/summaries/current-month-weekly")
async def get_current_month_weekly_summaries(user=Depends(get_current_user)):
    """获取本月的每周摘要"""
    now = _now_cst()
    current_year = now.year
    current_month = now.month
    
    with get_db() as conn:
        # 获取当前年份的所有周摘要，然后筛选出属于当前月的
        rows = conn.execute(
            "SELECT * FROM weekly_summaries WHERE user_id=? AND year=? ORDER BY week DESC",
            (user["id"], current_year),
        ).fetchall()
    
    # 过滤出属于当前月的周摘要
    import datetime as dt
    import calendar
    
    # 获取当前月的日期范围
    _, last_day = calendar.monthrange(current_year, current_month)
    month_start = date(current_year, current_month, 1)
    month_end = date(current_year, current_month, last_day)
    
    monthly_weeklies = []
    for row in rows:
        # 计算该周的开始日期（ISO周，周一开始）
        week_start = dt.date.fromisocalendar(current_year, row["week"], 1)
        week_end = week_start + timedelta(days=6)
        
        # 检查该周是否与当前月有重叠
        if week_start <= month_end and week_end >= month_start:
            row_dict = dict(row)
            row_dict["week_start"] = week_start.isoformat()
            row_dict["week_end"] = week_end.isoformat()
            monthly_weeklies.append(row_dict)
    
    return {"summaries": monthly_weeklies, "month": current_month, "year": current_year}


@app.get("/api/summaries/current-year-monthly")
async def get_current_year_monthly_summaries(user=Depends(get_current_user)):
    """获取本年度的每月摘要"""
    current_year = _now_cst().year
    
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM monthly_summaries WHERE user_id=? AND year=? ORDER BY month DESC",
            (user["id"], current_year),
        ).fetchall()
    return {"summaries": [dict(r) for r in rows], "year": current_year}


# ══════════════════════════════════════════════
# 商业化
# ══════════════════════════════════════════════

@app.get("/api/me/subscription")
async def get_subscription(user=Depends(get_current_user)):
    now = _now_cst()
    year_month = now.strftime("%Y-%m")
    with get_db() as conn:
        sub = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=?", (user["id"],)
        ).fetchone()
        quota = conn.execute(
            "SELECT chat_count FROM usage_quotas WHERE user_id=? AND year_month=?",
            (user["id"], year_month),
        ).fetchone()
    return {
        "subscription": dict(sub) if sub else None,
        "chat_count_this_month": quota["chat_count"] if quota else 0,
        "free_limit": FREE_MONTHLY_LIMIT,
    }


@app.post("/api/me/activate")
async def activate_code(req: ActivateCodeReq, user=Depends(get_current_user)):
    with get_db() as conn:
        code_row = conn.execute(
            "SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL",
            (req.code,),
        ).fetchone()
        if not code_row:
            raise HTTPException(400, "使用码无效或已被使用")
        if code_row["expires_at"] and code_row["expires_at"] < _now_cst().isoformat():
            raise HTTPException(400, "使用码已过期")

        now = _now_cst()
        # 叠加天数
        sub = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=?", (user["id"],)
        ).fetchone()
        if sub and sub["expire_at"] and sub["expire_at"] > now.isoformat():
            base = datetime.fromisoformat(sub["expire_at"])
        else:
            base = now
        new_expire = (base + timedelta(days=code_row["duration_days"])).isoformat()

        conn.execute(
            """INSERT INTO subscriptions (user_id, plan, expire_at, created_at)
               VALUES (?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET plan='paid', expire_at=?""",
            (user["id"], "paid", new_expire, now.isoformat(), new_expire),
        )
        conn.execute(
            "UPDATE invite_codes SET used_by=?, used_at=? WHERE id=?",
            (user["id"], now.isoformat(), code_row["id"]),
        )
    return {"ok": True, "expire_at": new_expire, "days_added": code_row["duration_days"]}


# ══════════════════════════════════════════════
# Admin
# ══════════════════════════════════════════════

@app.post("/api/admin/login")
async def admin_login(req: AdminLoginReq):
    with get_db() as conn:
        admin = conn.execute(
            "SELECT * FROM admin_users WHERE username=?", (req.username,)
        ).fetchone()
    if not admin or not verify_password(req.password, admin["password_hash"]):
        raise HTTPException(400, "账号或密码错误")
    token = create_token(
        {"sub": str(admin["id"]), "type": "admin"},
        timedelta(hours=ADMIN_TOKEN_EXPIRE_HOURS),
    )
    return {"token": token}


@app.get("/api/admin/users")
async def admin_list_users(page: int = 1, size: int = 20, admin=Depends(get_current_admin)):
    offset = (page - 1) * size
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        rows = conn.execute(
            """SELECT u.id, u.phone, u.nickname, u.created_at, u.last_active_at, u.is_disabled,
               s.plan, s.expire_at
               FROM users u
               LEFT JOIN subscriptions s ON s.user_id=u.id
               ORDER BY u.id DESC LIMIT ? OFFSET ?""",
            (size, offset),
        ).fetchall()
    return {"total": total, "users": [dict(r) for r in rows]}


@app.get("/api/admin/users/{user_id}")
async def admin_get_user(user_id: int, admin=Depends(get_current_admin)):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        conv_count = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        msg_count = conn.execute(
            "SELECT COUNT(*) as c FROM messages WHERE user_id=?", (user_id,)
        ).fetchone()["c"]
        year_month = _now_cst().strftime("%Y-%m")
        quota = conn.execute(
            "SELECT chat_count FROM usage_quotas WHERE user_id=? AND year_month=?",
            (user_id, year_month),
        ).fetchone()
        sub = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=?", (user_id,)
        ).fetchone()
    return {
        "user": dict(user),
        "conv_count": conv_count,
        "msg_count": msg_count,
        "chat_count_this_month": quota["chat_count"] if quota else 0,
        "subscription": dict(sub) if sub else None,
    }


@app.put("/api/admin/users/{user_id}/status")
async def admin_set_user_status(user_id: int, req: UserStatusReq, admin=Depends(get_current_admin)):
    with get_db() as conn:
        conn.execute("UPDATE users SET is_disabled=? WHERE id=?", (req.is_disabled, user_id))
    return {"ok": True}


# ── 使用码 ──────────────────────────────────

@app.get("/api/admin/invite-codes")
async def admin_list_codes(page: int = 1, size: int = 50, admin=Depends(get_current_admin)):
    offset = (page - 1) * size
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM invite_codes").fetchone()["c"]
        rows = conn.execute(
            "SELECT * FROM invite_codes ORDER BY id DESC LIMIT ? OFFSET ?",
            (size, offset),
        ).fetchall()
    return {"total": total, "codes": [dict(r) for r in rows]}


@app.post("/api/admin/invite-codes/generate")
async def admin_generate_codes(req: GenerateCodesReq, admin=Depends(get_current_admin)):
    now = _now_cst().isoformat()
    expires_at = None
    if req.expires_days:
        expires_at = (_now_cst() + timedelta(days=req.expires_days)).isoformat()

    codes = []
    with get_db() as conn:
        for _ in range(req.count):
            code = "YJ" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            conn.execute(
                """INSERT INTO invite_codes (code, duration_days, batch_tag, created_at, expires_at)
                   VALUES (?,?,?,?,?)""",
                (code, req.duration_days, req.batch_tag, now, expires_at),
            )
            codes.append(code)
    return {"codes": codes, "count": len(codes)}


@app.delete("/api/admin/invite-codes/{code_id}")
async def admin_delete_code(code_id: int, admin=Depends(get_current_admin)):
    with get_db() as conn:
        conn.execute("DELETE FROM invite_codes WHERE id=?", (code_id,))
    return {"ok": True}


# ── LLM 配置 ──────────────────────────────

@app.get("/api/admin/llm-configs")
async def admin_list_llm(admin=Depends(get_current_admin)):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM llm_configs ORDER BY id").fetchall()
    return {"configs": [dict(r) for r in rows]}


@app.post("/api/admin/llm-configs")
async def admin_create_llm(req: LLMConfigReq, admin=Depends(get_current_admin)):
    now = _now_cst().isoformat()
    with get_db() as conn:
        # 如果激活新配置，先停用所有其他配置
        if req.is_active == 1:
            conn.execute("UPDATE llm_configs SET is_active=0 WHERE is_active=1")
        
        cur = conn.execute(
            """INSERT INTO llm_configs (use_for, provider, model_name, api_key, base_url, is_active, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (req.use_for, req.provider, req.model_name, req.api_key,
             req.base_url, req.is_active, req.notes, now, now),
        )
    return {"id": cur.lastrowid}


@app.put("/api/admin/llm-configs/{config_id}")
async def admin_update_llm(config_id: int, req: LLMConfigReq, admin=Depends(get_current_admin)):
    now = _now_cst().isoformat()
    with get_db() as conn:
        # 如果激活此配置，先停用所有其他配置
        if req.is_active == 1:
            conn.execute("UPDATE llm_configs SET is_active=0 WHERE is_active=1 AND id != ?", (config_id,))
        
        conn.execute(
            """UPDATE llm_configs SET use_for=?, provider=?, model_name=?, api_key=?,
               base_url=?, is_active=?, notes=?, updated_at=?
               WHERE id=?""",
            (req.use_for, req.provider, req.model_name, req.api_key,
             req.base_url, req.is_active, req.notes, now, config_id),
        )
    return {"ok": True}


@app.delete("/api/admin/llm-configs/{config_id}")
async def admin_delete_llm(config_id: int, admin=Depends(get_current_admin)):
    with get_db() as conn:
        conn.execute("DELETE FROM llm_configs WHERE id=?", (config_id,))
    return {"ok": True}


# ── STT 配置 ──────────────────────────────

@app.get("/api/admin/stt-configs")
async def admin_list_stt(admin=Depends(get_current_admin)):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM stt_configs ORDER BY id").fetchall()
    return {"configs": [dict(r) for r in rows]}


@app.post("/api/admin/stt-configs")
async def admin_create_stt(req: STTConfigReq, admin=Depends(get_current_admin)):
    now = _now_cst().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO stt_configs (provider, model_name, api_key, base_url, is_active, notes, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (req.provider, req.model_name, req.api_key, req.base_url, req.is_active, req.notes, now),
        )
    return {"id": cur.lastrowid}


@app.put("/api/admin/stt-configs/{config_id}")
async def admin_update_stt(config_id: int, req: STTConfigReq, admin=Depends(get_current_admin)):
    with get_db() as conn:
        conn.execute(
            """UPDATE stt_configs SET provider=?, model_name=?, api_key=?, base_url=?,
               is_active=?, notes=? WHERE id=?""",
            (req.provider, req.model_name, req.api_key, req.base_url,
             req.is_active, req.notes, config_id),
        )
    return {"ok": True}


# ── 统计 ──────────────────────────────────

@app.get("/api/admin/stats")
async def admin_stats(admin=Depends(get_current_admin)):
    today = date.today().isoformat()
    year_month = _now_cst().strftime("%Y-%m")
    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        active_today = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE last_active_at >= ?", (today,)
        ).fetchone()["c"]
        conv_today = conn.execute(
            "SELECT COUNT(*) as c FROM conversations WHERE date=?", (today,)
        ).fetchone()["c"]
        total_tokens = conn.execute(
            "SELECT COALESCE(SUM(input_tokens+output_tokens),0) as t FROM llm_call_logs"
        ).fetchone()["t"]
        tokens_today = conn.execute(
            "SELECT COALESCE(SUM(input_tokens+output_tokens),0) as t FROM llm_call_logs WHERE created_at >= ?",
            (today,),
        ).fetchone()["t"]
        stt_today = conn.execute(
            "SELECT COALESCE(SUM(duration_seconds),0) as t FROM stt_call_logs WHERE created_at >= ?",
            (today,),
        ).fetchone()["t"]
        # 按模型统计（不分用途）
        model_stats = conn.execute(
            """SELECT model_name,
               SUM(input_tokens) as input_t, SUM(output_tokens) as output_t, COUNT(*) as calls
               FROM llm_call_logs GROUP BY model_name"""
        ).fetchall()
    return {
        "total_users": total_users,
        "active_today": active_today,
        "conv_today": conv_today,
        "total_tokens": total_tokens,
        "tokens_today": tokens_today,
        "stt_seconds_today": round(stt_today, 1),
        "model_stats": [dict(r) for r in model_stats],
    }


# ── 系统优化管理 ────────────────────────────

@app.get("/api/admin/system/health")
async def admin_system_health(admin=Depends(get_current_admin)):
    """获取系统健康报告"""
    from optimization_service import system_optimizer
    health_report = system_optimizer.check_system_health()
    return health_report


@app.post("/api/admin/system/optimize")
async def admin_optimize_database(admin=Depends(get_current_admin)):
    """手动触发数据库优化"""
    from optimization_service import system_optimizer
    optimization_report = system_optimizer.optimize_database()
    return {
        "success": True,
        "report": optimization_report
    }


@app.post("/api/admin/system/cleanup")
async def admin_cleanup_data(
    days_to_keep: int = 365,
    admin=Depends(get_current_admin)
):
    """手动触发数据清理"""
    from optimization_service import system_optimizer
    cleanup_report = system_optimizer.cleanup_old_data(days_to_keep=days_to_keep)
    return {
        "success": True,
        "report": cleanup_report
    }


@app.get("/api/admin/system/performance")
async def admin_system_performance(admin=Depends(get_current_admin)):
    """获取系统性能报告"""
    from optimization_service import system_optimizer
    performance_report = system_optimizer.generate_performance_report()
    return performance_report


# ── 摘要质检 ──────────────────────────────

@app.get("/api/admin/summaries/review")
async def admin_review_summaries(page: int = 1, size: int = 20, admin=Depends(get_current_admin)):
    offset = (page - 1) * size
    with get_db() as conn:
        rows = conn.execute(
            """SELECT ds.*, u.nickname FROM daily_summaries ds
               JOIN users u ON u.id=ds.user_id
               ORDER BY ds.created_at DESC LIMIT ? OFFSET ?""",
            (size, offset),
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as c FROM daily_summaries").fetchone()["c"]
    return {"total": total, "summaries": [dict(r) for r in rows]}


@app.post("/api/admin/summaries/regenerate")
async def admin_regenerate_summary(
    user_id: int,
    summary_type: str = "daily",
    date_str: str = None,
    admin=Depends(get_current_admin),
):
    if summary_type == "daily":
        if not date_str:
            raise HTTPException(400, "需要提供 date_str")
        # 先删除旧摘要
        with get_db() as conn:
            conn.execute(
                "DELETE FROM daily_summaries WHERE user_id=? AND date=?",
                (user_id, date_str),
            )
        ok = await generate_daily_summary(user_id, date_str)
        return {"ok": ok}
    raise HTTPException(400, "暂不支持该类型的手动重生成")
@app.post("/api/summaries/intelligent")
async def generate_intelligent_summary_endpoint(
    user=Depends(get_current_user),
):
    """生成智能总结（心理学+哲学分析）"""
    from intelligent_summary import generate_intelligent_summary
    result = await generate_intelligent_summary(user["id"])
    
    if "error" in result and result["error"] == "insufficient_data":
        raise HTTPException(
            status_code=400,
            detail={
                "error": "insufficient_data",
                "message": result["message"],
                "minimum_required": result.get("minimum_required", 3),
                "current_count": result.get("current_count", 0)
            }
        )
    
    if not result.get("success", False):
        raise HTTPException(
            status_code=500,
            detail={
                "error": "analysis_failed",
                "message": result.get("message", "分析失败")
            }
        )
    
    return result


@app.get("/api/summaries/intelligent/status")
async def get_intelligent_summary_status(
    user=Depends(get_current_user),
):
    """检查智能总结生成状态和数据充足性"""
    from intelligent_summary import collect_user_data
    
    user_data = collect_user_data(user["id"])
    stats = user_data["statistics"]
    
    return {
        "data_sufficient": stats["daily_summaries_count"] >= 3,
        "daily_summaries_count": stats["daily_summaries_count"],
        "minimum_required": 3,
        "analysis_period_days": stats["analysis_period_days"],
        "has_weekly_summaries": stats["weekly_summaries_count"] > 0,
        "has_monthly_summaries": stats["monthly_summaries_count"] > 0,
        "has_yearly_summaries": stats["yearly_summaries_count"] > 0
    }



@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    fe = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(fe):
        return FileResponse(fe, headers={"Cache-Control": "no-cache"})
    return {"service": "言己 API", "version": "1.0.0"}

@app.get("/manifest.json")
async def manifest():
    from fastapi.responses import FileResponse
    p = os.path.join(os.path.dirname(__file__), "static", "manifest.json")
    return FileResponse(p, media_type="application/manifest+json")

@app.get("/api/health")
async def health():
    return {"ok": True}
