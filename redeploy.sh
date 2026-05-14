#!/bin/bash
set -e

echo "=== 言己应用重新部署脚本 ==="
echo "开始时间: $(date)"

# 切换到应用目录
cd /home/admin/yyanji

echo "1. 备份数据库..."
DB_BACKUP="/home/admin/yyanji/data/yyanji.db.backup.$(date +%Y%m%d_%H%M%S)"
cp data/yyanji.db "$DB_BACKUP"
echo "数据库已备份到: $DB_BACKUP"

echo "2. 备份代码修改..."
CODE_BACKUP_DIR="/home/admin/yyanji/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$CODE_BACKUP_DIR"
cp -r backend/database.py backend/llm_service.py backend/main.py backend/memory_service.py backend/static/admin.html "$CODE_BACKUP_DIR"/
echo "代码修改已备份到: $CODE_BACKUP_DIR"

echo "3. 停止当前服务..."
pkill -f "uvicorn main:app.*8002" || true
sleep 3

echo "4. 检查Git状态..."
git status

echo "5. 暂存本地修改..."
git stash push -m "Redeploy backup $(date)" || echo "无修改可暂存"

echo "6. 拉取最新代码..."
git pull origin master

echo "7. 恢复重要修改..."
if git stash list | grep -q "Redeploy backup"; then
    git stash pop || echo "恢复修改时出错，手动检查"
fi

# 确保我们的关键修改被应用
echo "8. 应用关键配置修改..."
# 这里可以添加必要的配置更新

echo "9. 启动服务..."
cd backend
DATABASE_URL=sqlite:////home/admin/yyanji/data/yyanji.db \
JWT_SECRET=yyanji-jwt-2026 \
HF_ENDPOINT=https://hf-mirror.com \
nohup /usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8002 > ../data/app.log 2>&1 &

echo "10. 等待服务启动..."
sleep 10

echo "11. 验证服务..."
if curl -s http://127.0.0.1:8002/api/health | grep -q '"ok":true'; then
    echo "✅ 服务启动成功"
else
    echo "❌ 服务启动失败，检查日志: /home/admin/yyanji/data/app.log"
    exit 1
fi

echo "12. 验证数据..."
TOKEN=$(curl -s -X POST "http://127.0.0.1:8002/api/admin/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin2026"}' | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('token', ''))")

if [ -n "$TOKEN" ]; then
    USER_COUNT=$(curl -s "http://127.0.0.1:8002/api/admin/users" \
      -H "Authorization: Bearer $TOKEN" | python3 -c "import json,sys; data=json.load(sys.stdin); print(data.get('total', 0))")
    echo "✅ 数据库连接正常，用户数量: $USER_COUNT"
else
    echo "❌ 管理员登录失败"
fi

echo "=== 重新部署完成 ==="
echo "完成时间: $(date)"
echo "前端地址: https://recording.tc-test.aiygg.cn"
echo "管理后台: https://recording.tc-test.aiygg.cn/admin"
echo "日志文件: /home/admin/yyanji/data/app.log"