#!/bin/bash
fuser -k 8001/tcp 2>/dev/null
sleep 1
cd /home/admin/yyanji/backend
DATABASE_URL=sqlite:////home/admin/yyanji/data/yyanji.db \
JWT_SECRET=yyanji-jwt-2026 \
HF_ENDPOINT=https://hf-mirror.com \
nohup /usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8001 \
  >> /home/admin/yyanji/data/app.log 2>&1 &
echo "Started yyanji on 8001, PID: $!"
