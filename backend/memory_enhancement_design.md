# 言己记忆与性格系统增强设计

## 目标
基于用户需求，建立分层的记忆系统和科学的性格分析框架，动态优化对话体验。

## 核心设计原则
1. **分层记忆**：日→周→月→年摘要层层提炼
2. **特征提取**：从摘要中识别性格、习惯、兴趣模式
3. **动态优化**：基于特征个性化对话prompt
4. **隐私保护**：端到端加密存储
5. **成本优化**：智能token管理和摘要压缩

## 数据库架构扩展

### 新增表设计

#### 1. 用户性格特征表 (user_personality_traits)
```sql
CREATE TABLE user_personality_traits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    trait_type TEXT NOT NULL,  -- 'bigfive_openness', 'bigfive_conscientiousness', etc.
    trait_name TEXT NOT NULL,   -- '开放性', '尽责性', etc.
    score REAL DEFAULT 0.0,     -- 0-1标准化分数
    confidence REAL DEFAULT 0.0,-- 置信度
    evidence TEXT,              -- 支持证据（加密）
    last_updated TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(user_id, trait_type)
);
```

#### 2. 用户习惯模式表 (user_habits)
```sql
CREATE TABLE user_habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    habit_type TEXT NOT NULL,   -- '作息', '社交', '兴趣', '情绪'
    pattern_name TEXT NOT NULL,  -- '晨间记录', '晚间反思', etc.
    frequency_score REAL,        -- 频率评分
    strength_score REAL,         -- 强度评分
    first_observed TEXT,         -- 首次观察到
    last_observed TEXT,          -- 最后一次观察到
    evidence_summary TEXT,       -- 证据摘要（加密）
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

#### 3. 重要事项跟踪表 (important_topics)
```sql
CREATE TABLE important_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    topic TEXT NOT NULL,         -- 话题内容（加密）
    importance_score REAL DEFAULT 0.5, -- 重要性评分 0-1
    first_mentioned TEXT,        -- 首次提及时间
    last_mentioned TEXT,         -- 最后提及时间
    follow_up_status TEXT DEFAULT 'pending', -- pending, completed, abandoned
    scheduled_follow_up TEXT,    -- 计划跟进时间
    last_follow_up TEXT,         -- 最后一次跟进时间
    context_summary TEXT,        -- 上下文摘要（加密）
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

#### 4. 加密配置表 (encryption_config)
```sql
CREATE TABLE encryption_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    key_version INTEGER DEFAULT 1,
    encrypted_key TEXT NOT NULL, -- 用户专属加密密钥（使用主密钥加密）
    created_at TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
```

## 分层摘要Prompt优化

### 1. 日摘要增强版
```python
ENHANCED_DAILY_SUMMARY_PROMPT = """基于{nickname}在{date}的对话，请生成日摘要并分析用户特征：

【事件摘要】
1. 关键事件（时间、人物、活动）
2. 情绪变化曲线及触发因素
3. 提到的兴趣点和关注事项

【特征观察】
1. 今日表现出的性格特点（如：开放性、条理性、社交倾向等）
2. 情绪管理方式
3. 沟通风格偏好

【重要标记】
标记需要跟进的重要事项（如有）

最后在JSON中返回：
{{
    "events": ["事件1", "事件2"],
    "emotion_trend": "描述情绪变化",
    "observed_traits": ["特点1", "特点2"],
    "important_topics": ["需要跟进的话题"],
    "topic_tags": ["话题标签"],
    "emotion_score": 0.5
}}

对话内容：
{messages}"""
```

### 2. 周摘要增强版
```python
ENHANCED_WEEKLY_SUMMARY_PROMPT = """基于{nickname}在{week_range}的日摘要，提炼周摘要并分析行为模式：

【周度回顾】
1. 主要事件脉络和关联性
2. 情绪周期规律（何时高涨/低落）
3. 兴趣主题演变

【模式识别】
1. 重复出现的行为模式
2. 习惯养成情况（如记录频率、反思深度）
3. 社交互动特点

【性格特征更新】
基于本周表现，更新对用户性格的理解

最后在JSON中返回：
{{
    "weekly_theme": "本周主题",
    "behavior_patterns": ["模式1", "模式2"],
    "habit_strength": {"习惯1": 0.8, "习惯2": 0.6},
    "personality_insights": ["洞察1", "洞察2"],
    "theme_tags": ["主题标签"]
}}

日摘要内容：
{daily_summaries}"""
```

### 3. 月摘要增强版
```python
ENHANCED_MONTHLY_SUMMARY_PROMPT = """基于{nickname}在{year}年{month}月的周摘要，生成月摘要并深化性格理解：

【月度成长】
1. 重大进展和里程碑
2. 挑战应对方式
3. 成长轨迹

【性格画像】
1. 稳定的性格特征（基于大五人格模型）
2. 价值观体现
3. 核心需求和动机

【个性化建议】
基于用户特点，提出下月优化建议

最后在JSON中返回：
{{
    "milestones": ["里程碑1", "里程碑2"],
    "personality_traits": {{"开放性": 0.7, "尽责性": 0.8, ...}},
    "core_values": ["价值1", "价值2"],
    "growth_suggestions": ["建议1", "建议2"],
    "milestone_tags": ["里程碑标签"]
}}

周摘要内容：
{weekly_summaries}"""
```

## 动态Prompt生成系统

### 1. 性格特征提取算法
```python
class PersonalityAnalyzer:
    def __init__(self):
        self.bigfive_dimensions = [
            "openness", "conscientiousness", "extraversion",
            "agreeableness", "neuroticism"
        ]
    
    def extract_from_summary(self, summary_text):
        """从摘要文本提取性格特征"""
        # 使用规则+LLM分析提取特征
        traits = {}
        for dimension in self.bigfive_dimensions:
            traits[dimension] = self.analyze_dimension(summary_text, dimension)
        return traits
    
    def analyze_dimension(self, text, dimension):
        """分析特定维度"""
        mapping = {
            "openness": ["创意", "好奇心", "想象力", "尝试新事物"],
            "conscientiousness": ["计划性", "条理", "责任感", "自律"],
            "extraversion": ["社交", "活跃", "表达", "外向"],
            "agreeableness": ["合作", "同情", "信任", "友善"],
            "neuroticism": ["焦虑", "情绪波动", "敏感", "压力反应"]
        }
        # 基于关键词出现频率计算分数
        score = 0.0
        for keyword in mapping[dimension]:
            if keyword in text:
                score += 0.1
        return min(1.0, score)
```

### 2. 动态系统Prompt生成
```python
def generate_personalized_system_prompt(user_id):
    """基于用户特征生成个性化系统prompt"""
    with get_db() as conn:
        # 获取用户特征
        traits = conn.execute(
            "SELECT trait_type, score FROM user_personality_traits WHERE user_id=?",
            (user_id,)
        ).fetchall()
        
        # 获取习惯
        habits = conn.execute(
            "SELECT habit_type, pattern_name FROM user_habits WHERE user_id=? ORDER BY strength_score DESC LIMIT 3",
            (user_id,)
        ).fetchall()
        
        # 获取重要事项
        topics = conn.execute(
            "SELECT topic FROM important_topics WHERE user_id=? AND follow_up_status='pending'",
            (user_id,)
        ).fetchall()
    
    # 构建基础prompt
    prompt = "你是一位贴心的AI助手，了解用户的性格和习惯。\n\n"
    
    # 添加性格适配
    trait_dict = dict(traits)
    if trait_dict.get('extraversion', 0) > 0.7:
        prompt += "用户性格外向，喜欢积极互动，可以主动发起话题。\n"
    elif trait_dict.get('extraversion', 0) < 0.3:
        prompt += "用户性格偏内向，偏好深度交流，避免过多寒暄。\n"
    
    if trait_dict.get('conscientiousness', 0) > 0.7:
        prompt += "用户做事有条理，注重计划性，回复时可以结构清晰。\n"
    
    if trait_dict.get('neuroticism', 0) > 0.6:
        prompt += "用户情绪较敏感，注意表达方式，多提供情感支持。\n"
    
    # 添加习惯关注
    if habits:
        prompt += "\n用户的习惯特点：\n"
        for habit_type, pattern_name in habits:
            prompt += f"- {pattern_name}\n"
    
    # 添加重要事项跟进
    if topics:
        prompt += "\n可以适当关心以下话题的进展：\n"
        for topic, in topics[:2]:  # 只关注最重要的2个
            prompt += f"- {topic}\n"
    
    # 添加沟通风格建议
    if trait_dict.get('agreeableness', 0) > 0.7:
        prompt += "\n用户乐于合作，可以多用协商语气。"
    
    return prompt
```

### 3. 重要事项跟踪系统
```python
class TopicTracker:
    def __init__(self):
        self.importance_keywords = [
            "重要", "关键", "必须", "一定要", "决定",
            "改变", "转折", "里程碑", "目标", "计划"
        ]
    
    def extract_important_topics(self, conversation, user_id):
        """从对话中提取重要话题"""
        important_topics = []
        
        # 简单规则提取
        for sentence in conversation.split('。'):
            for keyword in self.importance_keywords:
                if keyword in sentence:
                    important_topics.append(sentence.strip())
                    break
        
        # 使用LLM进一步分析重要性
        if important_topics:
            prompt = f"""请评估以下话题的重要性（0-1分）：
{chr(10).join(important_topics)}

返回JSON格式：[{{"topic": "话题", "importance": 0.8}}]"""
            
            try:
                analysis = chat_complete([{"role": "user", "content": prompt}])
                topics_with_scores = json.loads(analysis)
                
                # 保存重要性>0.6的话题
                for item in topics_with_scores:
                    if item["importance"] > 0.6:
                        self.save_important_topic(user_id, item["topic"], item["importance"])
            except:
                # 失败时使用简单规则
                for topic in important_topics:
                    self.save_important_topic(user_id, topic, 0.7)
    
    def save_important_topic(self, user_id, topic, importance):
        """保存重要话题到数据库"""
        now = _now_cst().isoformat()
        with get_db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO important_topics 
                (user_id, topic, importance_score, first_mentioned, last_mentioned, context_summary)
                VALUES (?,?,?,?,?,?)
            """, (user_id, self.encrypt(topic), importance, now, now, ""))
```

## 加密存储方案

### 1. 密钥管理
```python
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

class EncryptionManager:
    def __init__(self, master_key_secret):
        self.master_key = self.derive_master_key(master_key_secret)
    
    def derive_master_key(self, secret):
        """从密码派生主密钥"""
        salt = b"yyanji_fixed_salt"  # 实际应用中应该随机生成并安全存储
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    
    def generate_user_key(self, user_id):
        """生成用户专属密钥"""
        user_specific_salt = str(user_id).encode()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=user_specific_salt,
            iterations=100000,
        )
        user_key = base64.urlsafe_b64encode(kdf.derive(self.master_key))
        
        # 使用主密钥加密用户密钥并存储
        encrypted_user_key = Fernet(self.master_key).encrypt(user_key)
        
        with get_db() as conn:
            conn.execute("""
                INSERT INTO encryption_config (user_id, encrypted_key, created_at)
                VALUES (?,?,?)
            """, (user_id, encrypted_user_key.decode(), _now_cst().isoformat()))
        
        return user_key
    
    def get_user_key(self, user_id):
        """获取用户密钥"""
        with get_db() as conn:
            row = conn.execute(
                "SELECT encrypted_key FROM encryption_config WHERE user_id=? AND is_active=1",
                (user_id,)
            ).fetchone()
        
        if not row:
            return self.generate_user_key(user_id)
        
        # 使用主密钥解密用户密钥
        encrypted_key = row[0].encode()
        user_key = Fernet(self.master_key).decrypt(encrypted_key)
        return user_key
    
    def encrypt_for_user(self, user_id, plaintext):
        """为用户加密数据"""
        user_key = self.get_user_key(user_id)
        cipher = Fernet(user_key)
        return cipher.encrypt(plaintext.encode()).decode()
    
    def decrypt_for_user(self, user_id, ciphertext):
        """为用户解密数据"""
        user_key = self.get_user_key(user_id)
        cipher = Fernet(user_key)
        return cipher.decrypt(ciphertext.encode()).decode()
```

### 2. 摘要加密包装器
```python
def encrypt_summary_content(user_id, content):
    """加密摘要内容"""
    # 在实际部署中，这里会调用EncryptionManager
    # 为了简化，先使用base64编码
    import base64
    encoded = base64.b64encode(content.encode()).decode()
    return f"ENC:{encoded}"

def decrypt_summary_content(user_id, encrypted_content):
    """解密摘要内容"""
    if encrypted_content.startswith("ENC:"):
        import base64
        encoded = encrypted_content[4:]
        return base64.b64decode(encoded).decode()
    return encrypted_content
```

## Token优化策略

### 1. 摘要压缩算法
```python
def compress_summary(summary, target_tokens=200):
    """压缩摘要到目标token数"""
    # 简单的压缩策略：
    # 1. 移除冗余描述
    # 2. 提取关键信息
    # 3. 使用简洁表达
    
    # 实际实现中可以使用LLM进行智能压缩
    prompt = f"""请将以下摘要压缩到约{target_tokens}个token，保留核心信息：

{summary}

压缩后："""
    
    try:
        compressed = chat_complete([{"role": "user", "content": prompt}])
        return compressed
    except:
        # 失败时使用简单截断
        words = summary.split()
        if len(words) > target_tokens:
            return ' '.join(words[:target_tokens]) + "..."
        return summary
```

### 2. 分层存储优化
```python
class TieredMemoryStorage:
    """分层记忆存储"""
    def __init__(self):
        self.tiers = {
            'raw': '原始对话',      # 完整存储，定期归档
            'daily': '日摘要',       # 详细摘要
            'weekly': '周摘要',      # 提炼摘要
            'monthly': '月摘要',     # 特征摘要
            'traits': '性格特征'     # 结构化特征
        }
    
    def store_conversation(self, user_id, conversation):
        """存储对话，智能选择存储层级"""
        # 分析对话重要性
        importance = self.analyze_importance(conversation)
        
        if importance > 0.8:
            # 重要对话：存储原始+摘要
            self.store_raw(user_id, conversation)
            summary = self.generate_summary(conversation)
            self.store_daily(user_id, summary)
        elif importance > 0.5:
            # 中等重要性：只存储摘要
            summary = self.generate_summary(conversation)
            self.store_daily(user_id, summary)
        else:
            # 低重要性：只更新特征
            self.update_traits_from_conversation(user_id, conversation)
```

## 实施路线图

### 第一阶段：基础增强（1周）
1. 优化现有摘要prompt，增加特征提取
2. 创建用户特征表结构
3. 实现基础加密存储

### 第二阶段：智能分析（2周）
1. 实现性格特征提取算法
2. 建立重要事项跟踪系统
3. 实现动态prompt生成

### 第三阶段：系统集成（1周）
1. 集成到现有对话流程
2. 添加token优化机制
3. 实现备份和恢复功能

### 第四阶段：深度优化（持续）
1. 心理学模型深度集成
2. 预测性关怀功能
3. 个性化推荐系统

## 监控与评估

### 关键指标
1. **摘要质量**：特征提取准确率
2. **个性化效果**：用户满意度提升
3. **成本控制**：平均token消耗
4. **隐私安全**：加密覆盖率

### A/B测试方案
对部分用户启用增强系统，比较：
- 对话质量评分
- 用户活跃度
- 功能使用深度

---

通过这个系统，言己将从一个简单的对话记录工具，转变为一个深度理解用户、提供个性化关怀的智能伴侣。