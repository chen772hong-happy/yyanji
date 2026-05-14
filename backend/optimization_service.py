"""
优化服务 - 系统性能优化、健康检查、数据清理
"""
import sqlite3
import os
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any
from database import get_db

logger = logging.getLogger(__name__)


class SystemOptimizer:
    """系统优化器"""
    
    def __init__(self):
        # 获取数据库路径
        db_url = os.environ.get("DATABASE_URL", "sqlite:////home/admin/yyanji/data/yyanji.db")
        if db_url.startswith("sqlite:////"):
            self.db_path = db_url.replace("sqlite:////", "/")
        else:
            self.db_path = "/home/admin/yyanji/data/yyanji.db"
    
    def check_system_health(self) -> Dict[str, Any]:
        """检查系统健康状况"""
        health_report = {
            "timestamp": datetime.now().isoformat(),
            "database": {},
            "tables": {},
            "performance": {},
            "issues": []
        }
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 检查数据库文件大小
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            health_report["database"]["size_mb"] = round(db_size / (1024 * 1024), 2)
            
            # 检查所有表的状态
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            for table in tables:
                table_name = table[0]
                
                # 获取表行数
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    row_count = cursor.fetchone()[0]
                    
                    # 获取表大小估算
                    cursor.execute(f"SELECT SUM(pgsize) FROM dbstat WHERE name=?", (table_name,))
                    table_size = cursor.fetchone()[0] or 0
                    
                    health_report["tables"][table_name] = {
                        "row_count": row_count,
                        "size_kb": round(table_size / 1024, 2) if table_size else 0
                    }
                    
                    # 检查大表
                    if row_count > 10000:
                        health_report["issues"].append(f"表 {table_name} 数据量较大: {row_count} 行")
                    
                except Exception as e:
                    health_report["tables"][table_name] = {"error": str(e)}
            
            # 检查性能相关表
            critical_tables = ["messages", "daily_summaries", "llm_call_logs"]
            for table in critical_tables:
                if table in health_report["tables"]:
                    row_count = health_report["tables"][table].get("row_count", 0)
                    if row_count > 50000:
                        health_report["issues"].append(f"关键表 {table} 数据量过大: {row_count} 行，建议归档")
            
            # 检查索引
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = cursor.fetchall()
            health_report["database"]["index_count"] = len(indexes)
            
            # 检查是否有缺失的索引
            tables_needing_indexes = []
            large_tables_without_indexes = ["messages", "llm_call_logs"]
            for table in large_tables_without_indexes:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,))
                if not cursor.fetchall():
                    tables_needing_indexes.append(table)
            
            if tables_needing_indexes:
                health_report["issues"].append(f"以下表可能需要索引: {', '.join(tables_needing_indexes)}")
            
            conn.close()
            
        except Exception as e:
            health_report["issues"].append(f"健康检查失败: {e}")
            logger.error(f"System health check failed: {e}")
        
        return health_report
    
    def optimize_database(self) -> Dict[str, Any]:
        """优化数据库性能"""
        optimization_report = {
            "timestamp": datetime.now().isoformat(),
            "actions_taken": [],
            "performance_improvements": []
        }
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 1. VACUUM - 重建数据库文件，回收空间
            start_time = time.time()
            conn.execute("VACUUM")
            vacuum_time = time.time() - start_time
            optimization_report["actions_taken"].append("执行 VACUUM 回收空间")
            optimization_report["performance_improvements"].append(f"VACUUM 耗时: {vacuum_time:.2f}秒")
            
            # 2. ANALYZE - 更新统计信息
            start_time = time.time()
            conn.execute("ANALYZE")
            analyze_time = time.time() - start_time
            optimization_report["actions_taken"].append("执行 ANALYZE 更新统计信息")
            optimization_report["performance_improvements"].append(f"ANALYZE 耗时: {analyze_time:.2f}秒")
            
            # 3. 创建缺失的索引
            indexes_to_create = [
                ("idx_messages_user_id", "messages(user_id)"),
                ("idx_messages_conversation_id", "messages(conversation_id)"),
                ("idx_llm_call_logs_user_id", "llm_call_logs(user_id)"),
                ("idx_llm_call_logs_created_at", "llm_call_logs(created_at)"),
                ("idx_daily_summaries_user_date", "daily_summaries(user_id, date)"),
                ("idx_weekly_summaries_user_year_week", "weekly_summaries(user_id, year, week)"),
                ("idx_monthly_summaries_user_year_month", "monthly_summaries(user_id, year, month)"),
            ]
            
            created_indexes = []
            for index_name, index_sql in indexes_to_create:
                try:
                    # 检查索引是否已存在
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,))
                    if not cursor.fetchone():
                        cursor.execute(f"CREATE INDEX {index_name} ON {index_sql}")
                        created_indexes.append(index_name)
                except Exception as e:
                    logger.warning(f"Failed to create index {index_name}: {e}")
            
            if created_indexes:
                optimization_report["actions_taken"].append(f"创建索引: {', '.join(created_indexes)}")
                optimization_report["performance_improvements"].append(f"新增 {len(created_indexes)} 个索引")
            
            conn.commit()
            conn.close()
            
            # 4. 检查文件大小变化
            new_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            optimization_report["database_size_mb"] = round(new_size / (1024 * 1024), 2)
            
            logger.info(f"Database optimization completed: {len(optimization_report['actions_taken'])} actions taken")
            
        except Exception as e:
            optimization_report["actions_taken"].append(f"优化失败: {e}")
            logger.error(f"Database optimization failed: {e}")
        
        return optimization_report
    
    def cleanup_old_data(self, days_to_keep: int = 365) -> Dict[str, Any]:
        """清理旧数据"""
        cleanup_report = {
            "timestamp": datetime.now().isoformat(),
            "tables_cleaned": {},
            "total_records_deleted": 0
        }
        
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
            
            with get_db() as conn:
                cursor = conn.cursor()
                
                # 1. 清理旧的LLM调用日志（保留30天）
                llm_cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                cursor.execute("DELETE FROM llm_call_logs WHERE created_at < ?", (llm_cutoff,))
                llm_deleted = cursor.rowcount
                cleanup_report["tables_cleaned"]["llm_call_logs"] = llm_deleted
                cleanup_report["total_records_deleted"] += llm_deleted
                
                # 2. 清理旧的STT调用日志（保留30天）
                cursor.execute("DELETE FROM stt_call_logs WHERE created_at < ?", (llm_cutoff,))
                stt_deleted = cursor.rowcount
                cleanup_report["tables_cleaned"]["stt_call_logs"] = stt_deleted
                cleanup_report["total_records_deleted"] += stt_deleted
                
                # 3. 归档旧消息（超过1年）
                messages_cutoff = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
                
                # 先检查哪些对话已经完全过期
                cursor.execute("""
                    SELECT c.id FROM conversations c
                    WHERE c.date < ? 
                    AND NOT EXISTS (
                        SELECT 1 FROM messages m 
                        WHERE m.conversation_id = c.id 
                        AND m.created_at >= ?
                    )
                """, (messages_cutoff, llm_cutoff))
                
                old_conversations = cursor.fetchall()
                conv_deleted = 0
                
                for conv in old_conversations:
                    conv_id = conv[0]
                    # 删除对话相关的消息
                    cursor.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
                    # 删除对话
                    cursor.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
                    conv_deleted += 1
                
                cleanup_report["tables_cleaned"]["old_conversations"] = conv_deleted
                cleanup_report["total_records_deleted"] += conv_deleted
                
                conn.commit()
            
            logger.info(f"Data cleanup completed: {cleanup_report['total_records_deleted']} records deleted")
            
        except Exception as e:
            cleanup_report["error"] = str(e)
            logger.error(f"Data cleanup failed: {e}")
        
        return cleanup_report
    
    def generate_performance_report(self) -> Dict[str, Any]:
        """生成性能报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "database": {},
            "user_statistics": {},
            "llm_usage": {}
        }
        
        try:
            with get_db() as conn:
                cursor = conn.cursor()
                
                # 用户统计
                cursor.execute("SELECT COUNT(*) FROM users")
                report["user_statistics"]["total_users"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM users WHERE is_disabled=0")
                report["user_statistics"]["active_users"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM users WHERE last_active_at >= date('now', '-7 days')")
                report["user_statistics"]["recently_active_users"] = cursor.fetchone()[0]
                
                # 对话统计
                cursor.execute("SELECT COUNT(*) FROM conversations")
                report["user_statistics"]["total_conversations"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM conversations WHERE date = date('now')")
                report["user_statistics"]["today_conversations"] = cursor.fetchone()[0]
                
                # 消息统计
                cursor.execute("SELECT COUNT(*) FROM messages")
                report["user_statistics"]["total_messages"] = cursor.fetchone()[0]
                
                # 摘要统计
                cursor.execute("SELECT COUNT(*) FROM daily_summaries")
                report["user_statistics"]["daily_summaries"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM weekly_summaries")
                report["user_statistics"]["weekly_summaries"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM monthly_summaries")
                report["user_statistics"]["monthly_summaries"] = cursor.fetchone()[0]
                
                # LLM使用统计
                cursor.execute("SELECT SUM(input_tokens), SUM(output_tokens) FROM llm_call_logs")
                tokens = cursor.fetchone()
                report["llm_usage"]["total_input_tokens"] = tokens[0] or 0
                report["llm_usage"]["total_output_tokens"] = tokens[1] or 0
                
                cursor.execute("SELECT COUNT(*) FROM llm_call_logs WHERE created_at >= date('now', '-30 days')")
                report["llm_usage"]["recent_calls_30d"] = cursor.fetchone()[0]
                
                # 数据库性能指标
                cursor.execute("PRAGMA page_count")
                report["database"]["page_count"] = cursor.fetchone()[0]
                
                cursor.execute("PRAGMA page_size")
                report["database"]["page_size"] = cursor.fetchone()[0]
                
                report["database"]["total_size_kb"] = (
                    report["database"]["page_count"] * report["database"]["page_size"] / 1024
                )
            
        except Exception as e:
            report["error"] = str(e)
            logger.error(f"Performance report generation failed: {e}")
        
        return report


# 全局优化器实例
system_optimizer = SystemOptimizer()


async def run_weekly_optimization():
    """每周执行一次系统优化"""
    logger.info("开始每周系统优化...")
    
    # 1. 健康检查
    health_report = system_optimizer.check_system_health()
    logger.info(f"系统健康检查完成，发现问题: {len(health_report.get('issues', []))}")
    
    # 如果有问题，记录到日志
    if health_report.get("issues"):
        for issue in health_report["issues"]:
            logger.warning(f"系统健康问题: {issue}")
    
    # 2. 数据库优化
    optimization_report = system_optimizer.optimize_database()
    logger.info(f"数据库优化完成，执行操作: {len(optimization_report.get('actions_taken', []))}")
    
    # 3. 数据清理
    cleanup_report = system_optimizer.cleanup_old_data(days_to_keep=365)
    logger.info(f"数据清理完成，删除记录: {cleanup_report.get('total_records_deleted', 0)}")
    
    # 4. 生成性能报告
    performance_report = system_optimizer.generate_performance_report()
    logger.info(f"性能报告生成完成，用户数: {performance_report.get('user_statistics', {}).get('total_users', 0)}")
    
    logger.info("每周系统优化完成")


async def run_daily_maintenance():
    """每日维护任务"""
    logger.info("开始每日维护...")
    
    # 快速健康检查
    health_report = system_optimizer.check_system_health()
    
    # 只处理紧急问题
    urgent_issues = [issue for issue in health_report.get("issues", []) 
                     if "过大" in issue or "失败" in issue]
    
    if urgent_issues:
        logger.warning(f"发现紧急问题: {urgent_issues}")
        # 在真实系统中，这里可以发送告警邮件或通知
    
    # 检查数据库文件大小
    db_size_mb = health_report.get("database", {}).get("size_mb", 0)
    if db_size_mb > 100:  # 超过100MB
        logger.warning(f"数据库文件过大: {db_size_mb}MB，建议优化")
    
    logger.info("每日维护完成")


if __name__ == "__main__":
    # 测试代码
    import asyncio
    from datetime import datetime
    
    print(f"优化服务测试 - {datetime.now().isoformat()}")
    
    # 测试健康检查
    print("\n=== 系统健康检查 ===")
    health = system_optimizer.check_system_health()
    print(f"数据库大小: {health.get('database', {}).get('size_mb', 0)}MB")
    print(f"表数量: {len(health.get('tables', {}))}")
    print(f"发现问题: {len(health.get('issues', []))}")
    
    # 测试性能报告
    print("\n=== 性能报告 ===")
    report = system_optimizer.generate_performance_report()
    print(f"用户总数: {report.get('user_statistics', {}).get('total_users', 0)}")
    print(f"活跃用户: {report.get('user_statistics', {}).get('active_users', 0)}")
    print(f"总消息数: {report.get('user_statistics', {}).get('total_messages', 0)}")
    
    # 测试优化
    print("\n=== 数据库优化 ===")
    opt_report = system_optimizer.optimize_database()
    print(f"执行操作: {opt_report.get('actions_taken', [])}")
    
    print("\n测试完成")