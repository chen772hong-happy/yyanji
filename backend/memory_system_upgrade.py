#!/usr/bin/env python3
"""
记忆与性格系统升级脚本
执行数据库迁移和系统初始化
"""
import sqlite3
import sys
import os
from datetime import datetime

def get_db_connection():
    """获取数据库连接"""
    # 从环境变量获取数据库路径
    db_url = os.environ.get("DATABASE_URL", "sqlite:////home/admin/yyanji/data/yyanji.db")
    
    if db_url.startswith("sqlite:////"):
        db_path = db_url.replace("sqlite:////", "/")
    elif db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "./")
    else:
        db_path = "/home/admin/yyanji/data/yyanji.db"
    
    print(f"连接到数据库: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables(conn):
    """创建新表"""
    cursor = conn.cursor()
    
    # 1. 用户性格特征表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_personality_traits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        trait_type TEXT NOT NULL,
        trait_name TEXT NOT NULL,
        score REAL DEFAULT 0.0,
        confidence REAL DEFAULT 0.0,
        evidence TEXT,
        last_updated TEXT NOT NULL,
        version INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id),
        UNIQUE(user_id, trait_type)
    )
    """)
    print("✅ 创建表: user_personality_traits")
    
    # 2. 用户习惯模式表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_habits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        habit_type TEXT NOT NULL,
        pattern_name TEXT NOT NULL,
        frequency_score REAL,
        strength_score REAL,
        first_observed TEXT,
        last_observed TEXT,
        evidence_summary TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    print("✅ 创建表: user_habits")
    
    # 3. 重要事项跟踪表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS important_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        topic TEXT NOT NULL,
        importance_score REAL DEFAULT 0.5,
        first_mentioned TEXT,
        last_mentioned TEXT,
        follow_up_status TEXT DEFAULT 'pending',
        scheduled_follow_up TEXT,
        last_follow_up TEXT,
        context_summary TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    print("✅ 创建表: important_topics")
    
    # 4. 加密配置表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS encryption_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        key_version INTEGER DEFAULT 1,
        encrypted_key TEXT NOT NULL,
        created_at TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    print("✅ 创建表: encryption_config")
    
    # 5. 对话优化配置表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversation_optimization (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        system_prompt TEXT,
        style_preferences TEXT DEFAULT '{}',
        topic_sensitivities TEXT DEFAULT '{}',
        last_optimized TEXT,
        optimization_version INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id),
        UNIQUE(user_id)
    )
    """)
    print("✅ 创建表: conversation_optimization")
    
    conn.commit()

def migrate_existing_data(conn):
    """迁移现有数据"""
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    
    # 从现有摘要中提取初始特征
    print("\n🚀 迁移现有数据...")
    
    # 获取所有用户
    cursor.execute("SELECT id, nickname FROM users")
    users = cursor.fetchall()
    
    for user in users:
        user_id = user['id']
        nickname = user['nickname']
        
        print(f"  处理用户: {nickname} (ID: {user_id})")
        
        # 检查是否有每日摘要
        cursor.execute("""
            SELECT content, emotion_tags, topic_tags, emotion_score 
            FROM daily_summaries 
            WHERE user_id=? 
            ORDER BY date DESC LIMIT 10
        """, (user_id,))
        daily_summaries = cursor.fetchall()
        
        if not daily_summaries:
            print(f"    ⚠️ 无摘要数据，跳过")
            continue
        
        # 简单的特征初始化
        traits_initialized = False
        
        # 从摘要中提取常见特征
        all_content = ' '.join([row['content'] for row in daily_summaries])
        
        # 分析基本特征
        traits_to_insert = [
            ('bigfive_openness', '开放性', 0.5, 0.3),
            ('bigfive_conscientiousness', '尽责性', 0.5, 0.3),
            ('bigfive_extraversion', '外向性', 0.5, 0.3),
            ('bigfive_agreeableness', '宜人性', 0.5, 0.3),
            ('bigfive_neuroticism', '神经质', 0.3, 0.3),
        ]
        
        # 基于内容调整特征
        content_lower = all_content.lower()
        
        # 关键词分析
        creativity_keywords = ['创意', '新奇', '探索', '想象']
        organization_keywords = ['计划', '整理', '完成', '目标']
        social_keywords = ['朋友', '社交', '聊天', '分享']
        emotion_keywords = ['情绪', '心情', '感受', '情感']
        
        trait_adjustments = {
            'bigfive_openness': sum(1 for kw in creativity_keywords if kw in content_lower) * 0.05,
            'bigfive_conscientiousness': sum(1 for kw in organization_keywords if kw in content_lower) * 0.05,
            'bigfive_extraversion': sum(1 for kw in social_keywords if kw in content_lower) * 0.05,
        }
        
        # 插入特征
        for trait_type, trait_name, base_score, confidence in traits_to_insert:
            score = base_score + trait_adjustments.get(trait_type, 0)
            score = max(0.0, min(1.0, score))
            
            cursor.execute("""
                INSERT OR REPLACE INTO user_personality_traits 
                (user_id, trait_type, trait_name, score, confidence, evidence, last_updated)
                VALUES (?,?,?,?,?,?,?)
            """, (user_id, trait_type, trait_name, score, confidence, 
                  f"从{len(daily_summaries)}条摘要中分析", now))
        
        traits_initialized = True
        
        # 初始化对话优化配置
        cursor.execute("""
            INSERT OR REPLACE INTO conversation_optimization 
            (user_id, system_prompt, last_optimized, optimization_version)
            VALUES (?,?,?,1)
        """, (user_id, f"你正在与{nickname}对话，请根据用户特点提供个性化回应。", now))
        
        print(f"    ✅ 初始化特征和优化配置")
    
    conn.commit()
    print(f"✅ 数据迁移完成，处理了 {len(users)} 个用户")

def backup_database(conn):
    """备份数据库"""
    import shutil
    from datetime import datetime
    
    # 获取数据库路径
    db_url = os.environ.get("DATABASE_URL", "sqlite:////home/admin/yyanji/data/yyanji.db")
    if db_url.startswith("sqlite:////"):
        db_path = db_url.replace("sqlite:////", "/")
    else:
        db_path = "/home/admin/yyanji/data/yyanji.db"
    
    # 创建备份
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup.{timestamp}"
    
    shutil.copy2(db_path, backup_path)
    print(f"✅ 数据库备份已创建: {backup_path}")
    
    return backup_path

def main():
    """主函数"""
    print("=" * 60)
    print("言己记忆与性格系统升级")
    print("=" * 60)
    
    try:
        # 备份数据库
        conn = get_db_connection()
        backup_path = backup_database(conn)
        
        # 创建新表
        print("\n📊 创建新表结构...")
        create_tables(conn)
        
        # 迁移数据
        print("\n🔄 迁移现有数据...")
        migrate_existing_data(conn)
        
        # 验证升级
        print("\n🔍 验证升级结果...")
        cursor = conn.cursor()
        
        # 检查表创建
        tables = ['user_personality_traits', 'user_habits', 'important_topics', 
                  'encryption_config', 'conversation_optimization']
        
        for table in tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if cursor.fetchone():
                print(f"  ✅ {table} 表存在")
            else:
                print(f"  ❌ {table} 表缺失")
        
        # 检查数据迁移
        cursor.execute("SELECT COUNT(*) FROM user_personality_traits")
        trait_count = cursor.fetchone()[0]
        print(f"  ✅ 用户特征记录: {trait_count} 条")
        
        cursor.execute("SELECT COUNT(*) FROM conversation_optimization")
        opt_count = cursor.fetchone()[0]
        print(f"  ✅ 优化配置记录: {opt_count} 条")
        
        print("\n" + "=" * 60)
        print("✅ 升级完成!")
        print(f"📁 备份位置: {backup_path}")
        print("💡 接下来需要:")
        print("  1. 更新 memory_service.py 中的摘要prompt")
        print("  2. 实现动态prompt生成系统")
        print("  3. 集成到现有对话流程")
        print("=" * 60)
        
        conn.close()
        
    except Exception as e:
        print(f"❌ 升级失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()