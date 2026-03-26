#!/bin/bash
# ============================================================
# 三防指挥系统 - Linux 云服务器一键部署脚本
# 支持: Ubuntu 20.04/22.04, Debian 11/12, CentOS 8/9
# 用法: sudo bash deploy.sh YOUR_DOMAIN
# ============================================================

set -e

DOMAIN="${1:-}"
APP_DIR="/opt/sanfang"
VENV_DIR="$APP_DIR/venv"
LOG_DIR="/var/log/sanfang"
USER="www-data"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ========== 前置检查 ==========
if [ "$EUID" -ne 0 ]; then
    error "请使用 root 权限运行: sudo bash deploy.sh YOUR_DOMAIN"
fi

if [ -z "$DOMAIN" ]; then
    echo ""
    echo "============================================"
    echo "  三防指挥系统 - 服务器部署"
    echo "============================================"
    echo ""
    echo "用法: sudo bash deploy.sh <你的域名>"
    echo ""
    echo "示例: sudo bash deploy.sh sanfang.example.com"
    echo ""
    echo "前置要求:"
    echo "  1. 域名已解析到本服务器IP"
    echo "  2. 域名已完成ICP备案（微信小程序要求）"
    echo "  3. 服务器已开放 80 和 443 端口"
    echo ""
    exit 1
fi

info "开始部署三防指挥系统到 $DOMAIN ..."

# ========== 1. 检测包管理器 ==========
info "[1/8] 检测系统环境..."
if command -v apt-get &>/dev/null; then
    PKG="apt"
    apt-get update -qq
elif command -v yum &>/dev/null; then
    PKG="yum"
elif command -v dnf &>/dev/null; then
    PKG="dnf"
else
    error "不支持的系统，需要 apt/yum/dnf 包管理器"
fi
info "包管理器: $PKG"

# ========== 2. 安装系统依赖 ==========
info "[2/8] 安装系统依赖..."
if [ "$PKG" = "apt" ]; then
    apt-get install -y -qq python3 python3-pip python3-venv nginx certbot python3-certbot-nginx curl
elif [ "$PKG" = "yum" ] || [ "$PKG" = "dnf" ]; then
    $PKG install -y python3 python3-pip nginx certbot python3-certbot-nginx curl
fi

# 确保 www-data 用户存在
if ! id "$USER" &>/dev/null; then
    if id "nginx" &>/dev/null; then
        USER="nginx"
    else
        useradd -r -s /bin/false www-data
    fi
fi
info "服务用户: $USER"

# ========== 3. 创建目录结构 ==========
info "[3/8] 创建应用目录..."
mkdir -p "$APP_DIR"
mkdir -p "$LOG_DIR"

# 复制项目文件（如果是从本地上传的）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/../app.py" ]; then
    info "从本地复制项目文件..."
    cp -r "$SCRIPT_DIR/../"* "$APP_DIR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/../".env "$APP_DIR/" 2>/dev/null || true
fi

# 检查 app.py 是否存在
if [ ! -f "$APP_DIR/app.py" ]; then
    warn "请先将项目文件上传到 $APP_DIR/"
    warn "上传完成后重新运行此脚本"
    echo ""
    echo "上传方法（在本地Windows执行）:"
    echo "  scp -r ./* root@你的服务器IP:/opt/sanfang/"
    echo ""
    exit 1
fi

# ========== 4. Python 虚拟环境 + 依赖 ==========
info "[4/8] 创建Python虚拟环境并安装依赖..."
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
"$VENV_DIR/bin/pip" install gunicorn -q
info "Python 依赖安装完成"

# ========== 5. 生成 .env 配置 ==========
if [ ! -f "$APP_DIR/.env" ]; then
    info "[5/8] 生成环境配置文件..."
    cat > "$APP_DIR/.env" << 'ENVEOF'
# 三防指挥系统 - 生产环境配置
FLASK_ENV=production

# LLM 模式: rule(纯规则,无需API) / hybrid(规则+LLM) / llm(纯LLM)
LLM_MODE=rule

# 大模型配置（使用hybrid/llm模式时需要）
# ENABLE_LLM=true
# DASHSCOPE_API_KEY=your_api_key_here

# 密钥（建议修改为随机字符串）
SECRET_KEY=change-this-to-a-random-string
ENVEOF
    warn "请编辑 $APP_DIR/.env 配置文件，设置必要参数"
else
    info "[5/8] .env 配置文件已存在，跳过"
fi

# ========== 6. 配置 Nginx ==========
info "[6/8] 配置 Nginx..."
NGINX_CONF="/etc/nginx/sites-available/sanfang"
NGINX_ENABLED="/etc/nginx/sites-enabled/sanfang"

# 如果没有 sites-available 目录（CentOS），使用 conf.d
if [ ! -d "/etc/nginx/sites-available" ]; then
    mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
    # 确保主配置 include sites-enabled
    if ! grep -q "sites-enabled" /etc/nginx/conf.d/../nginx.conf 2>/dev/null; then
        echo "include /etc/nginx/sites-enabled/*;" >> /etc/nginx/nginx.conf
    fi
fi

# 先用 HTTP 配置（Let's Encrypt 需要先验证域名）
cat > "$NGINX_CONF" << NGINXEOF
server {
    listen 80;
    server_name $DOMAIN;

    client_max_body_size 50M;

    location /static/ {
        alias $APP_DIR/static/;
        expires 7d;
    }

    location /favicon.png {
        alias $APP_DIR/favicon.png;
        expires 30d;
    }

    location /favicon.ico {
        alias $APP_DIR/icon.ico;
        expires 30d;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    location /api/ai/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 180s;
    }
}
NGINXEOF

ln -sf "$NGINX_CONF" "$NGINX_ENABLED"
# 移除默认站点
rm -f /etc/nginx/sites-enabled/default 2>/dev/null

nginx -t && systemctl restart nginx
info "Nginx HTTP 配置完成"

# ========== 7. SSL 证书 ==========
info "[7/8] 申请 SSL 证书 (Let's Encrypt)..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@$DOMAIN" --redirect || {
    warn "SSL 证书自动申请失败，可能原因:"
    warn "  1. 域名未解析到本服务器"
    warn "  2. 80端口被防火墙拦截"
    warn ""
    warn "可稍后手动执行: certbot --nginx -d $DOMAIN"
    warn "系统将先以 HTTP 模式运行"
}

# 设置自动续期
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --post-hook 'systemctl reload nginx'") | sort -u | crontab -

# ========== 8. Systemd 服务 ==========
info "[8/8] 配置系统服务..."
cat > /etc/systemd/system/sanfang.service << SVCEOF
[Unit]
Description=三防形势智能研判与指挥辅助系统
After=network.target

[Service]
Type=notify
User=$USER
Group=$USER
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin"
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV_DIR/bin/gunicorn -c $APP_DIR/deploy/gunicorn_config.py app:app
ExecReload=/bin/kill -s HUP \$MAINPID
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SVCEOF

# 设置文件权限
chown -R "$USER:$USER" "$APP_DIR"
chown -R "$USER:$USER" "$LOG_DIR"

# 启动服务
systemctl daemon-reload
systemctl enable sanfang
systemctl start sanfang

# ========== 完成 ==========
echo ""
echo "============================================"
echo "  部署完成!"
echo "============================================"
echo ""
echo "  浏览器访问: https://$DOMAIN"
echo "  系统管理页: https://$DOMAIN/system"
echo ""
echo "  常用命令:"
echo "    查看状态:  systemctl status sanfang"
echo "    查看日志:  journalctl -u sanfang -f"
echo "    重启服务:  systemctl restart sanfang"
echo "    停止服务:  systemctl stop sanfang"
echo ""
echo "  微信小程序配置:"
echo "    服务器域名: https://$DOMAIN"
echo "    在微信公众平台 -> 开发管理 -> 开发设置"
echo "    -> 服务器域名 中添加:"
echo "      request合法域名: https://$DOMAIN"
echo "      uploadFile合法域名: https://$DOMAIN"
echo "      downloadFile合法域名: https://$DOMAIN"
echo ""
echo "  重要: 请编辑 $APP_DIR/.env 文件配置参数"
echo "  修改后执行: systemctl restart sanfang"
echo "============================================"
