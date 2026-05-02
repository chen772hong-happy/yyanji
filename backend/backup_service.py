"""
备份服务 - 聊天记录和摘要的定期备份
"""
import sqlite3
import json
import os
import shutil
import gzip
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CST = ZoneInfo('Asia/Shanghai')
def _now_cst(): return datetime.now(CST).replace(tzinfo=None)

logger = logging.getLogger(__name__)

class DatabaseBackup:
    """数据库备份管理器"""
    
    def __init__(self, backup_dir="/home/admin/yyanji/backups"):
        self.backup_dir = backup_dir
        os.makedirs(backup_dir, exist_ok=True)
        
        # 获取数据库路径
        db_url = os.environ.get("DATABASE_URL", "sqlite:////home/admin/yyanji/data/yyanji.db")
        if db_url.startswith("sqlite:////"):
            self.db_path = db_url.replace("sqlite:////", "/")
        else:
            self.db_path = "/home/admin/yyanji/data/yyanji.db"
    
    def create_backup(self, backup_type="daily"):
        """创建数据库备份"""
        try:
            timestamp = _now_cst().strftime("%Y%m%d_%H%M%S")
            backup_name = f"yyanji_{backup_type}_{timestamp}.db.gz"
            backup_path = os.path.join(self.backup_dir, backup_name)
            
            # 备份整个数据库文件
            with open(self.db_path, 'rb') as f_in:
                with gzip.open(backup_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # 记录备份元数据
            meta = {
                "timestamp": _now_cst().isoformat(),
                "type": backup_type,
                "database": self.db_path,
                "backup_file": backup_path,
                "size_bytes": os.path.getsize(backup_path),
                "original_size": os.path.getsize(self.db_path)
            }
            
            # 保存元数据
            meta_path = backup_path.replace(".db.gz", ".meta.json")
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            
            logger.info(f"数据库备份创建成功: {backup_path} ({meta['size_bytes']} bytes)")
            
            # 清理旧备份（保留最近30天）
            self.cleanup_old_backups()
            
            return backup_path
            
        except Exception as e:
            logger.error(f"数据库备份失败: {e}")
            return None
    
    def cleanup_old_backups(self, days_to_keep=30):
        """清理旧的备份文件"""
        try:
            cutoff_date = _now_cst() - timedelta(days=days_to_keep)
            
            for filename in os.listdir(self.backup_dir):
                if not (filename.endswith(".db.gz") and filename.startswith("yyanji_")):
                    continue
                    
                filepath = os.path.join(self.backup_dir, filename)
                stat = os.stat(filepath)
                file_date = datetime.fromtimestamp(stat.st_mtime, CST)
                
                if file_date < cutoff_date:
                    # 删除备份文件和元数据文件
                    os.remove(filepath)
                    
                    # 尝试删除对应的元数据文件
                    meta_file = filepath.replace(".db.gz", ".meta.json")
                    if os.path.exists(meta_file):
                        os.remove(meta_file)
                    
                    logger.info(f"清理旧备份: {filename}")
                    
        except Exception as e:
            logger.error(f"清理旧备份失败: {e}")
    
    def create_data_export(self, export_type="full"):
        """创建数据导出（JSON格式，便于恢复）"""
        try:
            timestamp = _now_cst().strftime("%Y%m%d_%H%M%S")
            export_name = f"yyanji_export_{export_type}_{timestamp}.json.gz"
            export_path = os.path.join(self.backup_dir, export_name)
            
            # 连接到数据库
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 获取所有表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            # 导出数据
            export_data = {
                "export_type": export_type,
                "timestamp": _now_cst().isoformat(),
                "database": self.db_path,
                "tables": {}
            }
            
            for table in tables:
                cursor.execute(f"SELECT * FROM {table}")
                rows = cursor.fetchall()
                
                # 转换为字典列表
                table_data = []
                for row in rows:
                    table_data.append(dict(row))
                
                export_data["tables"][table] = table_data
            
            conn.close()
            
            # 压缩并保存
            with gzip.open(export_path, 'wt', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"数据导出创建成功: {export_path}")
            return export_path
            
        except Exception as e:
            logger.error(f"数据导出失败: {e}")
            return None
    
    def get_backup_list(self):
        """获取备份列表"""
        try:
            backups = []
            
            for filename in os.listdir(self.backup_dir):
                if not (filename.endswith(".db.gz") and filename.startswith("yyanji_")):
                    continue
                    
                filepath = os.path.join(self.backup_dir, filename)
                stat = os.stat(filepath)
                
                # 解析备份类型和时间戳
                parts = filename.replace("yyanji_", "").replace(".db.gz", "").split("_")
                if len(parts) >= 2:
                    backup_type = parts[0]
                    timestamp_str = "_".join(parts[1:])
                    
                    try:
                        backup_date = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S").replace(tzinfo=CST)
                    except:
                        backup_date = datetime.fromtimestamp(stat.st_mtime, CST)
                else:
                    backup_type = "unknown"
                    backup_date = datetime.fromtimestamp(stat.st_mtime, CST)
                
                # 检查是否有元数据文件
                meta_file = filepath.replace(".db.gz", ".meta.json")
                metadata = {}
                if os.path.exists(meta_file):
                    with open(meta_file, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                
                backups.append({
                    "filename": filename,
                    "path": filepath,
                    "type": backup_type,
                    "date": backup_date.isoformat(),
                    "size_bytes": stat.st_size,
                    "metadata": metadata
                })
            
            # 按日期排序（最新的在前）
            backups.sort(key=lambda x: x["date"], reverse=True)
            return backups
            
        except Exception as e:
            logger.error(f"获取备份列表失败: {e}")
            return []


# 全局备份管理器实例
backup_manager = DatabaseBackup()


async def run_daily_backup():
    """每日凌晨备份任务"""
    logger.info("开始每日数据库备份...")
    backup_path = backup_manager.create_backup("daily")
    
    # 每周日创建完整导出
    if _now_cst().weekday() == 6:  # 周日
        logger.info("开始每周完整数据导出...")
        export_path = backup_manager.create_data_export("weekly_full")
        
    logger.info("每日备份任务完成")


async def run_monthly_backup():
    """每月初备份任务"""
    logger.info("开始每月数据库备份...")
    backup_path = backup_manager.create_backup("monthly")
    export_path = backup_manager.create_data_export("monthly_full")
    logger.info("每月备份任务完成")