"""
增强加密服务 - 用于保护用户摘要和敏感数据
使用Fernet对称加密（基于AES）
"""
import os
import base64
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from database import get_db

logger = logging.getLogger(__name__)


class EncryptionService:
    """加密服务管理器"""
    
    def __init__(self, master_key_env_var="YYANJI_MASTER_KEY"):
        self.master_key_env_var = master_key_env_var
        self.master_key = self._load_or_generate_master_key()
        
    def _load_or_generate_master_key(self) -> bytes:
        """加载或生成主密钥"""
        # 从环境变量获取主密钥
        master_key_base64 = os.environ.get(self.master_key_env_var)
        
        if master_key_base64:
            try:
                # 解码base64格式的密钥
                return base64.urlsafe_b64decode(master_key_base64)
            except Exception as e:
                logger.error(f"Failed to decode master key from env: {e}")
                # 生成新的密钥
                return self._generate_master_key()
        else:
            # 生成新的密钥
            return self._generate_master_key()
    
    def _generate_master_key(self) -> bytes:
        """生成新的主密钥"""
        key = Fernet.generate_key()
        
        # 将密钥保存到环境变量（在真实生产环境中，应使用密钥管理服务）
        key_base64 = base64.urlsafe_b64encode(key).decode()
        logger.warning(f"Generated new master key. To persist, set {self.master_key_env_var}={key_base64}")
        
        return key
    
    def generate_user_key(self, user_id: int) -> bytes:
        """为用户生成派生密钥"""
        # 使用PBKDF2从主密钥派生用户特定密钥
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=str(user_id).encode(),
            iterations=100000,
        )
        user_key = base64.urlsafe_b64encode(kdf.derive(self.master_key))
        return user_key
    
    def encrypt_for_user(self, user_id: int, plaintext: str) -> str:
        """为用户加密文本"""
        try:
            user_key = self.generate_user_key(user_id)
            fernet = Fernet(user_key)
            encrypted = fernet.encrypt(plaintext.encode())
            return f"ENC:{base64.urlsafe_b64encode(encrypted).decode()}"
        except Exception as e:
            logger.error(f"Failed to encrypt for user {user_id}: {e}")
            # 回退到简单加密
            return self._simple_encrypt(plaintext)
    
    def decrypt_for_user(self, user_id: int, encrypted_text: str) -> str:
        """为用户解密文本"""
        if not encrypted_text.startswith("ENC:"):
            # 可能是未加密的文本
            return encrypted_text
        
        try:
            encrypted_text = encrypted_text[4:]  # 移除"ENC:"前缀
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_text)
            user_key = self.generate_user_key(user_id)
            fernet = Fernet(user_key)
            decrypted = fernet.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Failed to decrypt for user {user_id}: {e}")
            # 尝试简单解密
            return self._simple_decrypt(encrypted_text)
    
    def _simple_encrypt(self, plaintext: str) -> str:
        """简单加密（兼容性回退）"""
        encoded = base64.b64encode(plaintext.encode()).decode()
        return f"ENC:{encoded}"
    
    def _simple_decrypt(self, encrypted_text: str) -> str:
        """简单解密（兼容性回退）"""
        if encrypted_text.startswith("ENC:"):
            encoded = encrypted_text[4:]
            return base64.b64decode(encoded).decode()
        return encrypted_text
    
    def store_user_key(self, user_id: int) -> bool:
        """为用户存储加密密钥到数据库"""
        try:
            user_key = self.generate_user_key(user_id)
            key_version = 1
            
            with get_db() as conn:
                # 检查是否已有密钥
                existing = conn.execute(
                    "SELECT id FROM encryption_config WHERE user_id=? AND is_active=1",
                    (user_id,)
                ).fetchone()
                
                if existing:
                    # 停用旧密钥
                    conn.execute(
                        "UPDATE encryption_config SET is_active=0 WHERE user_id=?",
                        (user_id,)
                    )
                    key_version += 1
                
                # 存储新密钥
                conn.execute(
                    """INSERT INTO encryption_config 
                       (user_id, key_version, encrypted_key, created_at, is_active)
                       VALUES (?,?,?,?,?)""",
                    (user_id, key_version, user_key.decode(), 
                     datetime.now().isoformat(), 1)
                )
                conn.commit()
            
            logger.info(f"Stored encryption key for user {user_id} (version {key_version})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store encryption key for user {user_id}: {e}")
            return False
    
    def migrate_user_data(self, user_id: int, table_name: str, text_columns: list):
        """迁移用户数据到加密存储"""
        try:
            with get_db() as conn:
                # 获取需要加密的数据
                columns_str = ", ".join(["id"] + text_columns)
                cursor = conn.execute(
                    f"SELECT {columns_str} FROM {table_name} WHERE user_id=?",
                    (user_id,)
                )
                rows = cursor.fetchall()
                
                if not rows:
                    logger.info(f"No data to encrypt for user {user_id} in table {table_name}")
                    return 0
                
                updated_count = 0
                for row in rows:
                    row_id = row["id"]
                    update_values = {}
                    
                    # 加密每个文本列
                    for col in text_columns:
                        plaintext = row[col]
                        if plaintext and not plaintext.startswith("ENC:"):
                            encrypted = self.encrypt_for_user(user_id, plaintext)
                            update_values[col] = encrypted
                    
                    if update_values:
                        # 构建UPDATE语句
                        set_clause = ", ".join([f"{col}=?" for col in update_values.keys()])
                        query = f"UPDATE {table_name} SET {set_clause} WHERE id=?"
                        params = list(update_values.values()) + [row_id]
                        
                        conn.execute(query, params)
                        updated_count += 1
                
                if updated_count > 0:
                    conn.commit()
                    logger.info(f"Migrated {updated_count} records for user {user_id} in table {table_name}")
                
                return updated_count
                
        except Exception as e:
            logger.error(f"Failed to migrate data for user {user_id} in table {table_name}: {e}")
            return 0


# 全局加密服务实例
encryption_service = EncryptionService()


def encrypt_summary_content(user_id: int, content: str) -> str:
    """加密摘要内容（对外接口）"""
    return encryption_service.encrypt_for_user(user_id, content)


def decrypt_summary_content(user_id: int, encrypted_content: str) -> str:
    """解密摘要内容（对外接口）"""
    return encryption_service.decrypt_for_user(user_id, encrypted_content)


async def initialize_user_encryption(user_id: int):
    """初始化用户的加密设置"""
    try:
        # 存储用户密钥
        encryption_service.store_user_key(user_id)
        
        # 迁移现有数据（摘要表）
        tables_to_encrypt = [
            ("daily_summaries", ["content"]),
            ("weekly_summaries", ["content"]),
            ("monthly_summaries", ["content"]),
            ("yearly_summaries", ["content"]),
            ("user_portraits", ["content"]),
            ("important_topics", ["topic", "context_summary"]),
        ]
        
        total_migrated = 0
        for table_name, columns in tables_to_encrypt:
            migrated = encryption_service.migrate_user_data(user_id, table_name, columns)
            total_migrated += migrated
        
        logger.info(f"Initialized encryption for user {user_id}, migrated {total_migrated} records")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize encryption for user {user_id}: {e}")
        return False


def should_encrypt_field(field_value: str) -> bool:
    """判断字段是否需要加密"""
    if not field_value:
        return False
    
    # 已经加密的不再加密
    if field_value.startswith("ENC:"):
        return False
    
    # 只加密较长的文本（超过50字符）
    if len(field_value) < 50:
        return False
    
    return True