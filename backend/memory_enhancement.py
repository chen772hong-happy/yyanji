"""
记忆与性格增强模块
独立模块，可以导入到 memory_service.py 中
"""
import json
import logging
from datetime import datetime
from database import get_db

logger = logging.getLogger(__name__)

def _now_cst():
    from zoneinfo import ZoneInfo
    CST = ZoneInfo('Asia/Shanghai')
    return datetime.now(CST).replace(tzinfo=None)


class PersonalityAnalyzer:
    """性格特征分析器"""
    
    def __init__(self):
        self.bigfive_dimensions = [
            ("bigfive_openness", "开放性"),
            ("bigfive_conscientiousness", "尽责性"),
            ("bigfive_extraversion", "外向性"),
            ("bigfive_agreeableness", "宜人性"),
            ("bigfive_neuroticism", "神经质")
        ]
        
        # 关键词映射
        self.keyword_mapping = {
            "bigfive_openness": ["创意", "新奇", "探索", "想象", "艺术", "哲学", "开放"],
            "bigfive_conscientiousness": ["计划", "整理", "完成", "目标", "责任", "自律", "条理"],
            "bigfive_extraversion": ["社交", "活跃", "表达", "外向", "朋友", "聚会", "聊天"],
            "bigfive_agreeableness": ["合作", "同情", "信任", "友善", "帮助", "理解", "妥协"],
            "bigfive_neuroticism": ["焦虑", "情绪波动", "敏感", "压力", "担忧", "紧张", "不安"]
        }
    
    def extract_traits_from_summary(self, summary_text):
        """从摘要文本提取性格特征"""
        traits = {}
        
        text_lower = summary_text.lower()
        
        for trait_id, trait_name in self.bigfive_dimensions:
            score = 0.5  # 默认值
            
            # 基于关键词出现频率计算分数
            keywords = self.keyword_mapping.get(trait_id, [])
            keyword_count = sum(1 for kw in keywords if kw in text_lower)
            
            if keyword_count > 0:
                score = min(0.5 + (keyword_count * 0.1), 1.0)
            
            # 特殊处理：神经质分数反向计算
            if trait_id == "bigfive_neuroticism":
                # 神经质是负面特质，我们希望越低越好
                # 但需要正确识别它的存在
                score = min(0.3 + (keyword_count * 0.15), 1.0)
            
            traits[trait_id] = {
                "name": trait_name,
                "score": round(score, 2),
                "confidence": min(0.3 + (keyword_count * 0.1), 0.8)
            }
        
        return traits
    
    def update_user_traits(self, user_id, summary_data, summary_type="daily"):
        """更新用户性格特征"""
        try:
            content = summary_data.get("content", "")
            json_data = summary_data.get("json", {})
            
            # 从摘要内容提取特征
            traits = self.extract_traits_from_summary(content)
            
            # 从JSON数据中获取观察到的特征
            observed_traits = json_data.get("observed_traits", [])
            personality_insights = json_data.get("personality_insights", [])
            personality_traits = json_data.get("personality_traits", {})
            
            now = _now_cst().isoformat()
            
            with get_db() as conn:
                # 更新或插入特征
                for trait_id, trait_info in traits.items():
                    evidence_parts = []
                    
                    if observed_traits:
                        evidence_parts.append(f"观察到: {', '.join(observed_traits[:2])}")
                    if personality_insights:
                        evidence_parts.append(f"洞察: {', '.join(personality_insights[:2])}")
                    
                    # 如果JSON中有明确的性格特质分数，使用它们
                    trait_name = trait_info["name"]
                    if trait_name in personality_traits:
                        score = personality_traits[trait_name]
                        confidence = 0.7
                    else:
                        score = trait_info["score"]
                        confidence = trait_info["confidence"]
                    
                    evidence = ", ".join(evidence_parts) if evidence_parts else f"从{summary_type}摘要分析"
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO user_personality_traits 
                        (user_id, trait_type, trait_name, score, confidence, evidence, last_updated, version)
                        VALUES (?,?,?,?,?,?,?, 
                            COALESCE((SELECT version FROM user_personality_traits 
                                     WHERE user_id=? AND trait_type=?) + 1, 1))
                    """, (user_id, trait_id, trait_name, score, confidence, evidence, now,
                          user_id, trait_id))
                
                logger.info(f"Updated personality traits for user {user_id} from {summary_type} summary")
                
        except Exception as e:
            logger.error(f"Failed to update user traits for {user_id}: {e}")


class ImportantTopicTracker:
    """重要事项跟踪器"""
    
    def __init__(self):
        self.importance_keywords = [
            "重要", "关键", "必须", "一定要", "决定",
            "改变", "转折", "里程碑", "目标", "计划",
            "目标", "梦想", "愿望", "担心", "焦虑",
            "问题", "困难", "挑战", "突破", "成就"
        ]
    
    def extract_from_summary(self, user_id, summary_content, summary_json):
        """从摘要中提取重要话题"""
        try:
            important_topics = []
            
            # 从JSON中获取明确标记的重要话题
            json_topics = summary_json.get("important_topics", [])
            if json_topics:
                important_topics.extend(json_topics)
            
            # 从内容中基于关键词提取
            content = summary_content
            sentences = content.replace('。', '。\n').split('\n')
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                    
                # 检查是否包含重要性关键词
                has_importance = any(keyword in sentence for keyword in self.importance_keywords)
                
                # 检查是否包含情感强烈的词汇
                emotional_words = ["开心", "难过", "激动", "失望", "希望", "害怕"]
                has_emotion = any(word in sentence for word in emotional_words)
                
                if has_importance or has_emotion:
                    # 简化句子，提取核心内容
                    if len(sentence) > 50:
                        # 尝试提取关键部分
                        for keyword in self.importance_keywords:
                            if keyword in sentence:
                                idx = sentence.find(keyword)
                                start = max(0, idx - 20)
                                end = min(len(sentence), idx + 30)
                                important_topics.append(sentence[start:end].strip())
                                break
                        else:
                            important_topics.append(sentence[:50] + "...")
                    else:
                        important_topics.append(sentence)
            
            # 去重
            important_topics = list(set(important_topics))
            
            # 保存到数据库
            if important_topics:
                self.save_topics(user_id, important_topics, summary_json)
                
            return important_topics
            
        except Exception as e:
            logger.error(f"Failed to extract important topics for user {user_id}: {e}")
            return []
    
    def save_topics(self, user_id, topics, context_json):
        """保存重要话题到数据库"""
        try:
            now = _now_cst().isoformat()
            emotion_score = context_json.get("emotion_score", 0)
            
            with get_db() as conn:
                for topic in topics[:5]:  # 最多保存5个最重要的话题
                    # 计算重要性分数
                    importance_score = 0.5
                    
                    # 基于情感强度调整
                    if abs(emotion_score) > 1.0:
                        importance_score += 0.2
                    elif abs(emotion_score) > 0.5:
                        importance_score += 0.1
                    
                    # 基于关键词调整
                    for keyword in self.importance_keywords[:5]:  # 前5个是最重要的关键词
                        if keyword in topic:
                            importance_score += 0.1
                    
                    importance_score = min(importance_score, 1.0)
                    
                    # 检查是否已存在类似话题
                    existing = conn.execute("""
                        SELECT id, importance_score FROM important_topics 
                        WHERE user_id=? AND topic LIKE ?
                        ORDER BY last_mentioned DESC LIMIT 1
                    """, (user_id, f"%{topic[:20]}%")).fetchone()
                    
                    if existing:
                        # 更新现有话题
                        new_score = max(existing["importance_score"], importance_score)
                        conn.execute("""
                            UPDATE important_topics SET
                                importance_score = ?,
                                last_mentioned = ?,
                                follow_up_status = 'pending'
                            WHERE id = ?
                        """, (new_score, now, existing["id"]))
                    else:
                        # 插入新话题
                        conn.execute("""
                            INSERT INTO important_topics 
                            (user_id, topic, importance_score, first_mentioned, last_mentioned, 
                             follow_up_status, context_summary)
                            VALUES (?,?,?,?,?,?,?)
                        """, (user_id, topic, importance_score, now, now, 
                              "pending", json.dumps(context_json, ensure_ascii=False)))
                
                conn.commit()
                logger.info(f"Saved {len(topics[:5])} important topics for user {user_id}")
                
        except Exception as e:
            logger.error(f"Failed to save important topics for user {user_id}: {e}")


class ConversationOptimizer:
    """对话优化器"""
    
    def generate_personalized_prompt(self, user_id):
        """生成个性化系统提示"""
        try:
            with get_db() as conn:
                # 获取用户信息
                user_row = conn.execute(
                    "SELECT id, nickname FROM users WHERE id=?",
                    (user_id,)
                ).fetchone()
                
                if not user_row:
                    return "你是一位贴心的AI助手。"
                
                nickname = user_row["nickname"]
                
                # 获取性格特征
                traits = conn.execute("""
                    SELECT trait_name, score FROM user_personality_traits 
                    WHERE user_id=? ORDER BY confidence DESC LIMIT 5
                """, (user_id,)).fetchall()
                
                # 获取重要话题
                topics = conn.execute("""
                    SELECT topic FROM important_topics 
                    WHERE user_id=? AND follow_up_status='pending'
                    ORDER BY importance_score DESC LIMIT 3
                """, (user_id,)).fetchall()
                
                # 构建基础提示
                prompt_parts = [f"你正在与{nickname}对话，请根据用户特点提供个性化回应。\n\n"]
                
                # 添加性格适配
                if traits:
                    prompt_parts.append("【用户特点】")
                    for trait_name, score in traits:
                        if score > 0.7:
                            prompt_parts.append(f"- {trait_name}明显")
                        elif score > 0.5:
                            prompt_parts.append(f"- 有一定{trait_name}")
                    prompt_parts.append("")
                
                # 添加重要话题提醒
                if topics:
                    prompt_parts.append("【可关心的话题】")
                    for topic_row in topics:
                        topic = topic_row["topic"]
                        if len(topic) > 50:
                            topic = topic[:47] + "..."
                        prompt_parts.append(f"- {topic}")
                    prompt_parts.append("")
                
                # 添加通用建议
                prompt_parts.append("【回应建议】")
                prompt_parts.append("1. 根据用户特点调整语气和深度")
                prompt_parts.append("2. 适时关心提到的重要话题进展")
                prompt_parts.append("3. 注意情绪变化，提供情感支持")
                
                prompt = "\n".join(prompt_parts)
                
                # 更新优化配置
                now = _now_cst().isoformat()
                conn.execute("""
                    UPDATE conversation_optimization SET
                        system_prompt = ?,
                        last_optimized = ?,
                        optimization_version = optimization_version + 1
                    WHERE user_id = ?
                """, (prompt, now, user_id))
                
                return prompt
                
        except Exception as e:
            logger.error(f"Failed to generate personalized prompt for user {user_id}: {e}")
            return "你是一位贴心的AI助手。"


# 全局实例
personality_analyzer = PersonalityAnalyzer()
topic_tracker = ImportantTopicTracker()
conversation_optimizer = ConversationOptimizer()


def process_enhanced_summary(user_id, summary_content, summary_json, summary_type="daily"):
    """处理增强摘要：更新特征、跟踪话题、优化对话"""
    try:
        # 1. 更新性格特征
        personality_analyzer.update_user_traits(
            user_id, 
            {"content": summary_content, "json": summary_json},
            summary_type
        )
        
        # 2. 提取重要话题
        topic_tracker.extract_from_summary(user_id, summary_content, summary_json)
        
        # 3. 更新对话优化
        conversation_optimizer.generate_personalized_prompt(user_id)
        
        logger.info(f"Processed enhanced summary for user {user_id} (type: {summary_type})")
        
    except Exception as e:
        logger.error(f"Failed to process enhanced summary for user {user_id}: {e}")


# 加密工具函数
def simple_encrypt(text):
    """简单加密（实际生产环境应使用更强的加密）"""
    import base64
    encoded = base64.b64encode(text.encode()).decode()
    return f"ENC:{encoded}"


def simple_decrypt(encrypted_text):
    """简单解密"""
    if encrypted_text.startswith("ENC:"):
        import base64
        encoded = encrypted_text[4:]
        return base64.b64decode(encoded).decode()
    return encrypted_text