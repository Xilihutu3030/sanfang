# -*- coding: utf-8 -*-
"""
粤政易对接模块（预留）
基于企业微信私有化部署（政务微信）API
需要从政数局获取: CORP_ID, AGENT_ID, SECRET
"""

import json
import time
import hashlib
import urllib.request
from threading import Lock
from flask import Blueprint, request, jsonify, redirect

yzy = Blueprint('yzy', __name__)

# ==================== 配置项（待填入实际值） ====================
YZY_CONFIG = {
    "corp_id": "",        # 企业ID，从粤政易管理后台获取
    "agent_id": "",       # 应用AgentID
    "secret": "",         # 应用Secret
    "base_url": "https://qyapi.weixin.qq.com",  # API基础地址（政务微信可能有专用域名）
    "redirect_uri": "",   # OAuth回调地址，如 https://你的域名/api/yzy/callback
    "trusted_domain": "", # 可信域名
}

# ==================== Token 缓存 ====================
_token_cache = {"token": "", "expires": 0}
_token_lock = Lock()


def is_configured():
    """检查粤政易是否已配置"""
    return bool(YZY_CONFIG["corp_id"] and YZY_CONFIG["secret"])


def get_access_token():
    """获取 access_token（自动缓存，过期前5分钟刷新）"""
    with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["expires"] - 300:
            return _token_cache["token"]

    if not is_configured():
        return None

    url = (
        f"{YZY_CONFIG['base_url']}/cgi-bin/gettoken"
        f"?corpid={YZY_CONFIG['corp_id']}&corpsecret={YZY_CONFIG['secret']}"
    )
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        if data.get("errcode") == 0:
            with _token_lock:
                _token_cache["token"] = data["access_token"]
                _token_cache["expires"] = time.time() + data.get("expires_in", 7200)
            return data["access_token"]
        else:
            print(f"[YZY] get_access_token failed: {data}")
            return None
    except Exception as e:
        print(f"[YZY] get_access_token error: {e}")
        return None


# ==================== 1. OAuth 单点登录 ====================

@yzy.route('/api/yzy/login')
def yzy_oauth_entry():
    """
    粤政易OAuth入口 - 用户从粤政易工作台点击应用时跳转到此
    自动重定向到粤政易授权页面
    """
    if not is_configured():
        return jsonify({"error": "粤政易尚未配置，请联系管理员设置CORP_ID和SECRET"}), 503

    redirect_uri = YZY_CONFIG["redirect_uri"] or request.host_url.rstrip('/') + '/api/yzy/callback'
    oauth_url = (
        f"{YZY_CONFIG['base_url'].replace('qyapi', 'open')}/connect/oauth2/authorize"
        f"?appid={YZY_CONFIG['corp_id']}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=snsapi_base"
        f"&state=yzy#wechat_redirect"
    )
    return redirect(oauth_url)


@yzy.route('/api/yzy/callback')
def yzy_oauth_callback():
    """
    OAuth回调 - 粤政易授权后携带code跳转回来
    用code换取用户身份，自动匹配系统用户并签发JWT
    """
    code = request.args.get('code', '')
    if not code:
        return jsonify({"error": "缺少授权code"}), 400

    token = get_access_token()
    if not token:
        return jsonify({"error": "获取access_token失败"}), 500

    # 用code换取用户userid
    url = f"{YZY_CONFIG['base_url']}/cgi-bin/user/getuserinfo?access_token={token}&code={code}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
    except Exception as e:
        return jsonify({"error": f"获取用户信息失败: {e}"}), 500

    if data.get("errcode", 0) != 0:
        return jsonify({"error": f"授权失败: {data.get('errmsg', '')}"}), 400

    userid = data.get("UserId") or data.get("userid", "")
    if not userid:
        return jsonify({"error": "未获取到用户ID"}), 400

    # 获取用户详细信息
    user_info = _get_user_detail(token, userid)

    # 匹配系统用户并签发token（实际使用时对接auth模块）
    from auth import get_db
    import jwt
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=?", (userid,)).fetchone()

    if not user:
        # 自动创建用户（首次从粤政易登录）
        import uuid
        uid = str(uuid.uuid4())[:8]
        display_name = user_info.get("name", userid)
        phone = user_info.get("mobile", "")
        db.execute(
            "INSERT INTO users (id, username, password_hash, salt, display_name, role, phone) "
            "VALUES (?, ?, '', '', ?, 'operator', ?)",
            (uid, userid, display_name, phone)
        )
        db.commit()
        user = db.execute("SELECT * FROM users WHERE username=?", (userid,)).fetchone()

    db.close()

    # 签发JWT
    payload = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
        "source": "yzy",
        "exp": time.time() + 86400 * 7
    }
    token_jwt = jwt.encode(payload, "sanfang_secret_key_2024", algorithm="HS256")

    # 重定向到系统主页，携带token
    return redirect(f"/system?token={token_jwt}&source=yzy")


def _get_user_detail(token, userid):
    """获取粤政易用户详细信息"""
    url = f"{YZY_CONFIG['base_url']}/cgi-bin/user/get?access_token={token}&userid={userid}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        return json.loads(resp.read())
    except Exception:
        return {"userid": userid}


# ==================== 2. 消息推送（预警通知） ====================

def send_alert_message(user_ids, title, content, url="", msg_type="textcard"):
    """
    向粤政易用户推送预警消息
    user_ids: 用户ID列表或 "@all"
    title: 消息标题
    content: 消息内容（支持HTML标签的部分子集）
    url: 点击消息跳转的链接
    """
    token = get_access_token()
    if not token:
        return {"error": "access_token获取失败，请检查粤政易配置"}

    if isinstance(user_ids, list):
        to_user = "|".join(user_ids)
    else:
        to_user = str(user_ids)

    if msg_type == "textcard":
        payload = {
            "touser": to_user,
            "msgtype": "textcard",
            "agentid": int(YZY_CONFIG["agent_id"] or 0),
            "textcard": {
                "title": title,
                "description": f"<div class=\"normal\">{content}</div>",
                "url": url or YZY_CONFIG.get("redirect_uri", "").replace("/api/yzy/callback", "/system"),
                "btntxt": "查看详情"
            }
        }
    else:
        payload = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": int(YZY_CONFIG["agent_id"] or 0),
            "text": {"content": f"[{title}]\n{content}"}
        }

    api_url = f"{YZY_CONFIG['base_url']}/cgi-bin/message/send?access_token={token}"
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        return result
    except Exception as e:
        return {"error": str(e)}


def send_emergency_broadcast(title, content, level="orange"):
    """
    全员广播紧急预警
    level: blue/yellow/orange/red 对应不同紧急程度
    """
    return send_alert_message("@all", f"[{level.upper()}] {title}", content)


# ==================== 3. JS-SDK 签名 ====================

@yzy.route('/api/yzy/js-config')
def yzy_js_config():
    """
    为前端生成JS-SDK配置签名
    前端调用政务微信JS-SDK时需要先获取签名
    """
    if not is_configured():
        return jsonify({"error": "粤政易未配置"}), 503

    url = request.args.get('url', '')
    if not url:
        return jsonify({"error": "缺少url参数"}), 400

    jsapi_ticket = _get_jsapi_ticket()
    if not jsapi_ticket:
        return jsonify({"error": "获取jsapi_ticket失败"}), 500

    import random
    import string
    noncestr = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    timestamp = str(int(time.time()))

    sign_str = f"jsapi_ticket={jsapi_ticket}&noncestr={noncestr}&timestamp={timestamp}&url={url}"
    signature = hashlib.sha1(sign_str.encode()).hexdigest()

    return jsonify({
        "corpId": YZY_CONFIG["corp_id"],
        "agentId": YZY_CONFIG["agent_id"],
        "timestamp": timestamp,
        "nonceStr": noncestr,
        "signature": signature
    })


_jsapi_cache = {"ticket": "", "expires": 0}

def _get_jsapi_ticket():
    """获取jsapi_ticket"""
    if _jsapi_cache["ticket"] and time.time() < _jsapi_cache["expires"] - 300:
        return _jsapi_cache["ticket"]

    token = get_access_token()
    if not token:
        return None

    url = f"{YZY_CONFIG['base_url']}/cgi-bin/get_jsapi_ticket?access_token={token}"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
        if data.get("errcode") == 0:
            _jsapi_cache["ticket"] = data["ticket"]
            _jsapi_cache["expires"] = time.time() + data.get("expires_in", 7200)
            return data["ticket"]
    except Exception as e:
        print(f"[YZY] jsapi_ticket error: {e}")
    return None


# ==================== 4. 状态检查接口 ====================

@yzy.route('/api/yzy/status')
def yzy_status():
    """检查粤政易对接状态"""
    configured = is_configured()
    result = {
        "configured": configured,
        "corp_id": YZY_CONFIG["corp_id"][:6] + "***" if YZY_CONFIG["corp_id"] else "",
        "agent_id": YZY_CONFIG["agent_id"] or "",
        "has_secret": bool(YZY_CONFIG["secret"]),
        "base_url": YZY_CONFIG["base_url"],
        "redirect_uri": YZY_CONFIG["redirect_uri"] or "(auto)",
    }
    if configured:
        token = get_access_token()
        result["token_valid"] = bool(token)
    else:
        result["token_valid"] = False
        result["message"] = "请在 yuezhengyi.py 中配置 corp_id, agent_id, secret"
    return jsonify(result)


# ==================== 5. 预警推送路由 ====================

@yzy.route('/api/yzy/push', methods=['POST'])
def yzy_push_message():
    """
    手动触发粤政易消息推送
    body: { "users": ["user1"] 或 "@all", "title": "...", "content": "..." }
    """
    if not is_configured():
        return jsonify({"error": "粤政易未配置"}), 503

    data = request.json or {}
    users = data.get("users", "@all")
    title = data.get("title", "三防预警通知")
    content = data.get("content", "")

    if not content:
        return jsonify({"error": "消息内容不能为空"}), 400

    result = send_alert_message(users, title, content)
    return jsonify(result)
