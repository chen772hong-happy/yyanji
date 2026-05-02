"""
intelligent_summary.py - 智能总结API实现
基于用户历史摘要和聊天记录，从心理学和哲学角度进行深度分析
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from zoneinfo import ZoneInfo

from database import get_db
from llm_service import chat_complete

CST = ZoneInfo('Asia/Shanghai')
logger = logging.getLogger(__name__)

# ======================
# 心理学分析提示词模板
# ======================

PSYCHOLOGY_ANALYSIS_PROMPT = """你是一位专业的心理咨询师和人格分析专家。请基于用户的对话历史和摘要，从心理学角度进行深度分析。

【用户历史数据】
{user_data}

【分析要求】
1. **人格特征分析**（基于大五人格模型）：
   - 开放性（对新经验的接受程度）
   - 尽责性（组织性、责任感）
   - 外向性（社交倾向、能量来源）
   - 宜人性（合作性、同理心）
   - 神经质（情绪稳定性）

2. **情绪模式识别**：
   - 主要情绪基调
   - 情绪调节策略
   - 压力应对方式

3. **认知风格评估**：
   - 思维方式（分析型/直觉型）
   - 决策偏好（理性/感性）
   - 问题解决策略

4. **人际关系模式**：
   - 依恋风格
   - 沟通特点
   - 社交需求

【输出格式】
请以JSON格式返回分析结果：
{{
  "personality_traits": {{
    "openness": {{
      "score": 0.8,
      "description": "描述文字",
      "evidence": ["证据1", "证据2"]
    }},
    "conscientiousness": {{...}},
    "extraversion": {{...}},
    "agreeableness": {{...}},
    "neuroticism": {{...}}
  }},
  "emotional_patterns": {{
    "dominant_mood": "主要情绪",
    "regulation_strategies": ["策略1", "策略2"],
    "stress_coping": "压力应对方式"
  }},
  "cognitive_style": {{
    "thinking_style": "思维方式",
    "decision_making": "决策偏好",
    "problem_solving": "问题解决策略"
  }},
  "interpersonal_patterns": {{
    "attachment_style": "依恋风格",
    "communication_style": "沟通特点",
    "social_needs": "社交需求"
  }},
  "key_insights": ["核心洞察1", "核心洞察2"],
  "growth_suggestions": ["成长建议1", "成长建议2"]
}}"""

# ======================
# 哲学分析提示词模板
# ======================

PHILOSOPHY_ANALYSIS_PROMPT = """你是一位哲学思考引导者。请基于用户的对话历史和摘要，从哲学角度探讨其存在意义和价值观体系。

【用户历史数据】
{user_data}

【分析维度】
1. **存在意义探索**：
   - 生命意义感来源
   - 核心价值追求
   - 自我实现方向

2. **价值观体系**：
   - 核心信念
   - 道德准则
   - 生活哲学

3. **自我认知深度**：
   - 自我理解程度
   - 内在矛盾
   - 成长潜力

4. **与世界的关系**：
   - 人与自然的关系
   - 人与社会的关系
   - 人与自我的关系

【哲学流派参考】
- 存在主义：自由、责任、意义创造
- 斯多葛主义：内在控制、接受不可控
- 儒家思想：仁、义、礼、智、信
- 道家思想：自然、无为、和谐

【输出格式】
请以JSON格式返回分析结果：
{{
  "existential_meaning": {{
    "meaning_sources": ["意义来源1", "意义来源2"],
    "core_values": ["核心价值1", "核心价值2"],
    "self_actualization": "自我实现方向"
  }},
  "value_system": {{
    "core_beliefs": ["核心信念1", "核心信念2"],
    "moral_principles": ["道德准则1", "道德准则2"],
    "life_philosophy": "生活哲学"
  }},
  "self_awareness": {{
    "self_understanding": "自我理解程度",
    "inner_conflicts": ["内在矛盾1", "内在矛盾2"],
    "growth_potential": "成长潜力"
  }},
  "world_relations": {{
    "nature_relation": "与自然的关系",
    "society_relation": "与社会的关系",
    "self_relation": "与自我的关系"
  }},
  "philosophical_insights": ["哲学洞察1", "哲学洞察2"],
  "reflective_questions": ["反思问题1", "反思问题2"]
}}"""

# ======================
# 整体总结提示词模板
# ======================

INTELLIGENT_SUMMARY_PROMPT = """你是一位整合心理学和哲学视角的智能总结助手。请基于以下分析结果，为用户生成一份简洁而深刻的整体总结。

【心理学分析】
{psychology_analysis}

【哲学分析】
{philosophy_analysis}

【总结要求】
1. **核心人格特征**（用1-2句话概括）：
   - 突出最显著的人格特点
   - 结合具体行为表现

2. **成长轨迹总结**：
   - 主要发展脉络
   - 关键转折点
   - 进步与挑战

3. **深度洞察**：
   - 从心理学和哲学交叉视角的独特发现
   - 潜在的内在需求
   - 未充分发展的潜能

4. **个性化建议**：
   - 基于分析的具体行动建议
   - 适合的成长方向
   - 需要关注的领域

【输出格式】
请返回以下格式的JSON：
{{
  "core_personality": "核心人格特征描述（1-2句话）",
  "growth_journey": "成长轨迹总结",
  "deep_insights": ["深度洞察1", "深度洞察2"],
  "personalized_advice": ["个性化建议1", "个性化建议2"],
  "summary_text": "完整的总结文本（300-500字）"
}}"""

# ======================
# 数据收集函数
# ======================

def collect_user_data(user_id: int, days_back: int = 90) -> Dict[str, Any]:
    """收集用户的历史数据用于分析（简化版本）"""
    with get_db() as conn:
        # 用户基本信息
        user = conn.execute(
            "SELECT id, nickname, phone, birth_year, birth_month, birth_day, gender, self_desc FROM users WHERE id=?",
            (user_id,)
        ).fetchone()
        
        # 最近N天的日摘要
        cutoff_date = (datetime.now(CST) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        daily_summaries = conn.execute(
            """SELECT date, content, emotion_tags, topic_tags, emotion_score 
               FROM daily_summaries 
               WHERE user_id=? AND date >= ? 
               ORDER BY date DESC""",
            (user_id, cutoff_date)
        ).fetchall()
        
        # 周/月/年摘要
        weekly_summaries = conn.execute(
            "SELECT year, week, content FROM weekly_summaries WHERE user_id=? ORDER BY year DESC, week DESC LIMIT 12",
            (user_id,)
        ).fetchall()
        
        monthly_summaries = conn.execute(
            "SELECT year, month, content FROM monthly_summaries WHERE user_id=? ORDER BY year DESC, month DESC LIMIT 6",
            (user_id,)
        ).fetchall()
        
        yearly_summaries = conn.execute(
            "SELECT year, content FROM yearly_summaries WHERE user_id=? ORDER BY year DESC LIMIT 3",
            (user_id,)
        ).fetchall()
        
        # 用户画像（简化）
        portraits = conn.execute(
            "SELECT id, content FROM user_portraits WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        ).fetchall()
        
        # 重要话题（简化）
        important_topics = conn.execute(
            "SELECT topic, importance_score as importance FROM important_topics WHERE user_id=? ORDER BY importance_score DESC LIMIT 5",
            (user_id,)
        ).fetchall()
        
        # 最近对话样本（简化）
        recent_conversations = conn.execute(
            """SELECT c.date, m.role, m.content 
               FROM conversations c 
               JOIN messages m ON c.id = m.conversation_id 
               WHERE c.user_id=? 
               ORDER BY m.id DESC 
               LIMIT 20""",
            (user_id,)
        ).fetchall()
    
    # 构建数据字典
    user_data = {
        "user_info": dict(user) if user else {},
        "statistics": {
            "daily_summaries_count": len(daily_summaries),
            "weekly_summaries_count": len(weekly_summaries),
            "monthly_summaries_count": len(monthly_summaries),
            "yearly_summaries_count": len(yearly_summaries),
            "analysis_period_days": days_back
        },
        "daily_summaries": [dict(s) for s in daily_summaries],
        "weekly_summaries": [dict(s) for s in weekly_summaries],
        "monthly_summaries": [dict(s) for s in monthly_summaries],
        "yearly_summaries": [dict(s) for s in yearly_summaries],
        "portraits": [dict(p) for p in portraits],
        "important_topics": [dict(t) for t in important_topics],
        "recent_conversations_sample": [dict(c) for c in recent_conversations]
    }
    
    return user_data

def format_user_data_for_prompt(user_data: Dict[str, Any]) -> str:
    """将用户数据格式化为适合LLM处理的文本"""
    parts = []
    
    # 用户基本信息
    user_info = user_data.get("user_info", {})
    if user_info:
        parts.append(f"【用户基本信息】")
        parts.append(f"- 昵称：{user_info.get('nickname', '未知')}")
        if user_info.get('birth_year'):
            parts.append(f"- 出生：{user_info.get('birth_year')}年{user_info.get('birth_month', '')}月{user_info.get('birth_day', '')}日")
        if user_info.get('self_desc'):
            parts.append(f"- 自我描述：{user_info.get('self_desc')}")
    
    # 统计信息
    stats = user_data.get("statistics", {})
    parts.append(f"\n【数据统计】")
    parts.append(f"- 分析周期：最近{stats.get('analysis_period_days', 90)}天")
    parts.append(f"- 日摘要数量：{stats.get('daily_summaries_count', 0)}")
    parts.append(f"- 周摘要数量：{stats.get('weekly_summaries_count', 0)}")
    parts.append(f"- 月摘要数量：{stats.get('monthly_summaries_count', 0)}")
    parts.append(f"- 年摘要数量：{stats.get('yearly_summaries_count', 0)}")
    
    # 日摘要样本（最近7天）
    daily_samples = user_data.get("daily_summaries", [])[:7]
    if daily_samples:
        parts.append(f"\n【近期日摘要样本】")
        for summary in daily_samples:
            date = summary.get('date', '')
            content = (summary.get('content', '')[:100] + '...') if len(summary.get('content', '')) > 100 else summary.get('content', '')
            emotion_score = summary.get('emotion_score', 0)
            parts.append(f"- {date}（情绪分：{emotion_score:.1f}）：{content}")
    
    # 周/月摘要样本
    weekly_samples = user_data.get("weekly_summaries", [])[:3]
    if weekly_samples:
        parts.append(f"\n【周摘要样本】")
        for summary in weekly_samples:
            year = summary.get('year', '')
            week = summary.get('week', '')
            content = (summary.get('content', '')[:80] + '...') if len(summary.get('content', '')) > 80 else summary.get('content', '')
            parts.append(f"- {year}年第{week}周：{content}")
    
    # 用户画像特征
    portraits = user_data.get("portraits", [])
    if portraits:
        parts.append(f"\n【用户画像特征】")
        for portrait in portraits:
            trait_type = portrait.get('trait_type', '')
            trait_value = portrait.get('trait_value', '')
            confidence = portrait.get('confidence', 0)
            if trait_type and trait_value:
                parts.append(f"- {trait_type}：{trait_value}（置信度：{confidence:.1f}）")
    
    # 重要话题
    topics = user_data.get("important_topics", [])[:5]
    if topics:
        parts.append(f"\n【重要话题】")
        for topic in topics:
            topic_text = topic.get('topic', '')
            importance = topic.get('importance', 0)
            parts.append(f"- {topic_text}（重要性：{importance}/10）")
    
    # 对话风格样本
    conv_samples = user_data.get("recent_conversations_sample", [])[:5]
    if conv_samples:
        parts.append(f"\n【对话风格样本】")
        for conv in conv_samples:
            role = "用户" if conv.get('role') == 'user' else "AI"
            content = (conv.get('content', '')[:60] + '...') if len(conv.get('content', '')) > 60 else conv.get('content', '')
            parts.append(f"- {role}：{content}")
    
    return "\n".join(parts)

# ======================
# 主分析函数
# ======================

async def generate_intelligent_summary(user_id: int) -> Dict[str, Any]:
    """生成智能总结"""
    logger.info(f"开始生成智能总结，用户ID：{user_id}")
    
    # 1. 收集用户数据
    user_data = collect_user_data(user_id)
    formatted_data = format_user_data_for_prompt(user_data)
    
    if not formatted_data or user_data["statistics"]["daily_summaries_count"] < 3:
        return {
            "error": "insufficient_data",
            "message": "数据不足，请至少积累3天以上的对话记录",
            "minimum_required": 3,
            "current_count": user_data["statistics"]["daily_summaries_count"]
        }
    
    try:
        # 2. 心理学分析
        psychology_prompt = PSYCHOLOGY_ANALYSIS_PROMPT.format(user_data=formatted_data)
        psychology_response = await chat_complete(
            [{"role": "user", "content": psychology_prompt}],
            user_id=user_id,
            use_for="summary"  # 使用summary专用的LLM配置
        )
        
        # 3. 哲学分析
        philosophy_prompt = PHILOSOPHY_ANALYSIS_PROMPT.format(user_data=formatted_data)
        philosophy_response = await chat_complete(
            [{"role": "user", "content": philosophy_prompt}],
            user_id=user_id,
            use_for="summary"
        )
        
        # 4. 整体总结
        summary_prompt = INTELLIGENT_SUMMARY_PROMPT.format(
            psychology_analysis=psychology_response,
            philosophy_analysis=philosophy_response
        )
        summary_response = await chat_complete(
            [{"role": "user", "content": summary_prompt}],
            user_id=user_id,
            use_for="summary"
        )
        
        # 5. 解析JSON响应
        def parse_json_response(text: str) -> Dict[str, Any]:
            """从LLM响应中提取JSON"""
            import re
            # 尝试找到JSON部分
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            # 如果找不到有效的JSON，返回原始文本
            return {"raw_text": text}
        
        psychology_result = parse_json_response(psychology_response)
        philosophy_result = parse_json_response(philosophy_response)
        summary_result = parse_json_response(summary_response)
        
        # 6. 构建最终结果
        result = {
            "success": True,
            "generated_at": datetime.now(CST).isoformat(),
            "data_statistics": user_data["statistics"],
            "psychology_analysis": psychology_result,
            "philosophy_analysis": philosophy_result,
            "intelligent_summary": summary_result,
            "user_data_preview": {
                "nickname": user_data["user_info"].get("nickname", "用户"),
                "analysis_period": f"最近{user_data['statistics']['analysis_period_days']}天",
                "summary_count": user_data["statistics"]["daily_summaries_count"]
            }
        }
        
        logger.info(f"智能总结生成成功，用户ID：{user_id}")
        return result
        
    except Exception as e:
        logger.error(f"智能总结生成失败，用户ID：{user_id}，错误：{str(e)}")
        import traceback
        logger.error(f"详细堆栈：{traceback.format_exc()}")
        return {
            "success": False,
            "error": str(e),
            "message": f"分析过程中出现错误：{str(e)[:100]}",
            "user_data_statistics": user_data.get("statistics", {}) if 'user_data' in locals() else {}
        }