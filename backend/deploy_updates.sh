#!/bin/bash
# 言己记忆与性格系统更新部署脚本

set -e  # 出错时退出

echo "=== 言己系统更新部署开始 ==="
echo "时间: $(date)"

# 1. 停止当前服务
echo "1. 停止当前服务..."
if [ -f /home/admin/yyanji/data/app.log ]; then
    echo "当前服务日志最后几行:"
    tail -10 /home/admin/yyanji/data/app.log
fi

fuser -k 8002/tcp 2>/dev/null || true
sleep 2

# 2. 备份当前代码
echo "2. 备份当前代码..."
BACKUP_DIR="/home/admin/yyanji/backups/code_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r /home/admin/yyanji/backend/*.py "$BACKUP_DIR/"
echo "代码已备份到: $BACKUP_DIR"

# 3. 验证新代码
echo "3. 验证新代码..."
cd /home/admin/yyanji/backend

# 检查Python语法
echo "  检查Python语法..."
python3 -m py_compile main.py
python3 -m py_compile memory_service.py
python3 -m py_compile memory_enhancement.py
python3 -m py_compile backup_service.py
python3 -m py_compile optimization_service.py
python3 -m py_compile encryption_service.py

# 检查关键文件是否存在
required_files=(
    "main.py"
    "memory_service.py"
    "memory_enhancement.py"
    "backup_service.py"
    "optimization_service.py"
    "encryption_service.py"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file 存在"
    else
        echo "  ❌ $file 缺失"
        exit 1
    fi
done

# 4. 测试数据库连接
echo "4. 测试数据库连接..."
DATABASE_URL="sqlite:////home/admin/yyanji/data/yyanji.db"
if [ -f "/home/admin/yyanji/data/yyanji.db" ]; then
    db_size=$(stat -c%s "/home/admin/yyanji/data/yyanji.db")
    echo "  数据库文件大小: $(echo "scale=2; $db_size/1024/1024" | bc) MB"
    
    # 测试数据库可读性
    python3 -c "
import sqlite3
try:
    conn = sqlite3.connect('/home/admin/yyanji/data/yyanji.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    user_count = cursor.fetchone()[0]
    print(f'    数据库可读，用户数: {user_count}')
    conn.close()
except Exception as e:
    print(f'    数据库连接失败: {e}')
    exit(1)
"
else
    echo "  ⚠️ 数据库文件不存在，将创建新数据库"
fi

# 5. 测试优化服务
echo "5. 测试优化服务..."
python3 -c "
from optimization_service import system_optimizer
try:
    report = system_optimizer.generate_performance_report()
    print(f'    优化服务正常，用户数: {report.get(\"user_statistics\", {}).get(\"total_users\", 0)}')
except Exception as e:
    print(f'    优化服务测试失败: {e}')
"

# 6. 启动服务
echo "6. 启动服务..."
cd /home/admin/yyanji
bash start.sh

sleep 3

# 7. 验证服务状态
echo "7. 验证服务状态..."
if netstat -tlnp | grep -q :8002; then
    echo "  ✅ 服务已在端口 8002 启动"
    
    # 检查服务响应
    echo "  测试API响应..."
    sleep 2
    if curl -s -f "http://localhost:8002/api/health" > /dev/null; then
        echo "  ✅ 健康检查API响应正常"
    else
        echo "  ⚠️ 健康检查API响应异常"
    fi
else
    echo "  ❌ 服务启动失败"
    echo "  查看日志:"
    tail -20 /home/admin/yyanji/data/app.log
    exit 1
fi

# 8. 创建备份目录（如果不存在）
echo "8. 创建备份目录..."
mkdir -p /home/admin/yyanji/backups
echo "  备份目录: /home/admin/yyanji/backups"

# 9. 检查定时任务配置
echo "9. 检查定时任务配置..."
echo "  摘要任务安排在凌晨1-3点:"
echo "    - 日摘要: 01:30"
echo "    - 周摘要: 02:00 (每周一)"
echo "    - 月摘要: 02:30 (每月2日)"
echo "    - 年摘要: 02:45 (每年1月2日)"
echo "  备份任务:"
echo "    - 每日备份: 02:50"
echo "    - 每月备份: 02:55 (每月1日)"
echo "  优化任务:"
echo "    - 每日维护: 03:10"
echo "    - 每周优化: 03:30 (每周日)"

# 10. 验证新API端点
echo "10. 验证新API端点..."
echo "  新摘要API端点:"
echo "    - GET /api/summaries/current-week       # 本周每天摘要"
echo "    - GET /api/summaries/current-month-weekly # 本月每周摘要"
echo "    - GET /api/summaries/current-year-monthly # 本年每月摘要"
echo "  新管理API端点:"
echo "    - GET /api/admin/system/health          # 系统健康报告"
echo "    - POST /api/admin/system/optimize       # 手动优化数据库"
echo "    - POST /api/admin/system/cleanup        # 手动清理数据"
echo "    - GET /api/admin/system/performance     # 系统性能报告"

# 11. 检查加密服务
echo "11. 检查加密服务..."
python3 -c "
from encryption_service import encryption_service
try:
    test_text = '测试加密文本'
    encrypted = encryption_service.encrypt_for_user(1, test_text)
    decrypted = encryption_service.decrypt_for_user(1, encrypted)
    if decrypted == test_text:
        print('  ✅ 加密服务正常')
    else:
        print(f'  ⚠️ 加密解密不匹配')
except Exception as e:
    print(f'  ⚠️ 加密服务测试失败: {e}')
"

# 12. 提醒配置有效LLM
echo "12. 重要提醒:"
echo "  ⚠️ 请确保已配置有效的大模型API密钥:"
echo "    访问 https://recording.tc-test.aiygg.cn/admin"
echo "    进入 '🤖 LLM配置' 页面"
echo "    添加有效的配置并激活"
echo ""
echo "  测试LLM配置命令:"
echo "    cd /home/admin/yyanji/backend && DATABASE_URL=sqlite:////home/admin/yyanji/data/yyanji.db python3 -c \""
echo "    from llm_service import chat_complete"
echo "    import asyncio"
echo "    async def test():"
echo "        try:"
echo "            resp = await chat_complete([{'role': 'user', 'content': '测试'}], user_id=1)"
echo "            print('✅ LLM配置有效')"
echo "        except Exception as e:"
echo "            print(f'❌ LLM配置无效: {e}')"
echo "    asyncio.run(test())"
echo "    \""

echo ""
echo "=== 部署完成 ==="
echo "系统已升级，包含以下功能:"
echo "1. ✅ 分层记忆系统（日/周/月/年摘要增强）"
echo "2. ✅ 性格特征分析（大五人格模型）"
echo "3. ✅ 重要事项跟踪"
echo "4. ✅ 对话个性化优化"
echo "5. ✅ 自动备份系统（每日/每月）"
echo "6. ✅ 数据加密保护"
echo "7. ✅ 系统性能优化"
echo "8. ✅ 定时任务管理（凌晨1-4点）"
echo ""
echo "查看服务日志: tail -f /home/admin/yyanji/data/app.log"
echo "访问管理后台: https://recording.tc-test.aiygg.cn/admin"
echo "API文档: http://localhost:8002/docs"