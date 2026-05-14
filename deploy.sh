#!/bin/bash
set -e
echo "=== 言己部署 ==="
cd /opt/yyanji
cp -r /root/.openclaw/workspace/yyanji/backend/* /opt/yyanji/backend/
cp -r /root/.openclaw/workspace/yyanji/frontend/* /opt/yyanji/frontend/
systemctl restart yyanji
nginx -s reload
echo "部署完成: http://recording.tc-test.aiygg.cn"
