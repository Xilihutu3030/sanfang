#!/bin/bash
# 三防指挥系统 - 更新部署脚本
# 用于代码更新后重新部署（不重新安装系统依赖）

set -e
APP_DIR="/opt/sanfang"
VENV_DIR="$APP_DIR/venv"

echo "=== 三防指挥系统 - 更新部署 ==="

# 1. 备份数据库
if [ -f "$APP_DIR/sanfang.db" ]; then
    cp "$APP_DIR/sanfang.db" "$APP_DIR/sanfang.db.bak.$(date +%Y%m%d%H%M)"
    echo "[OK] 数据库已备份"
fi

# 2. 复制新代码（保留 .env 和数据库）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/../app.py" ]; then
    # 排除不需要覆盖的文件
    rsync -av --exclude='.env' --exclude='sanfang.db' --exclude='*.db.bak.*' \
          --exclude='judge_history.json' --exclude='__pycache__' \
          --exclude='venv' --exclude='*.log' \
          "$SCRIPT_DIR/../" "$APP_DIR/"
    echo "[OK] 代码已更新"
fi

# 3. 更新依赖
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
echo "[OK] 依赖已更新"

# 4. 重启服务
systemctl restart sanfang
echo "[OK] 服务已重启"

# 5. 检查状态
sleep 2
if systemctl is-active --quiet sanfang; then
    echo ""
    echo "=== 更新成功! 服务运行正常 ==="
else
    echo ""
    echo "=== 警告: 服务启动异常，请检查日志 ==="
    echo "  journalctl -u sanfang -n 30"
fi
