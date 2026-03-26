# -*- coding: utf-8 -*-
"""
用户认证模块（纯用户系统，无租户）
- SQLite 存储用户数据
- JWT token 认证
- 角色: admin(管理员), operator(指挥员), viewer(查看者)
"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
import base64
from datetime import datetime
from functools import wraps

from flask import request, jsonify, g

# ==================== 配置 ====================
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sanfang.db')
JWT_SECRET = os.environ.get('JWT_SECRET', secrets.token_hex(32))
TOKEN_EXPIRE = 7 * 24 * 3600  # 7天

ROLES = {
    'admin': 3,      # 管理员 - 管理用户/数据
    'operator': 2,   # 指挥员 - 研判/操作
    'viewer': 1,     # 查看者 - 只读
}

TIERS = {
    'free': 0,       # 免费用户
    'premium': 1,    # 付费用户
}

# 免费用户每日AI研判次数限制
FREE_JUDGE_LIMIT = 3


# ==================== 数据库 ====================
def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            role TEXT DEFAULT 'viewer',
            phone TEXT DEFAULT '',
            status INTEGER DEFAULT 1,
            tier TEXT DEFAULT 'free',
            judge_count INTEGER DEFAULT 0,
            judge_date TEXT DEFAULT '',
            last_login TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS hazards (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            level TEXT DEFAULT '',
            elevation REAL DEFAULT 0,
            location TEXT DEFAULT '',
            lat REAL,
            lng REAL,
            extra TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS judge_history (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            result TEXT NOT NULL,
            save_time TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    _seed_default_data(db)
    # 为已有表添加新字段（兼容旧数据库）
    for col, default in [("tier", "'free'"), ("judge_count", "0"), ("judge_date", "''")]:
        try:
            db.execute("ALTER TABLE users ADD COLUMN %s TEXT DEFAULT %s" % (col, default))
        except Exception:
            pass
    # 确保 admin 用户为 premium
    db.execute("UPDATE users SET tier='premium' WHERE username='admin'")
    db.commit()
    db.close()


def _seed_default_data(db):
    row = db.execute("SELECT COUNT(*) as c FROM users").fetchone()
    if row['c'] > 0:
        return
    _create_user_raw(db, 'admin', 'admin123', '管理员', 'admin')
    _create_user_raw(db, 'operator', '123456', '指挥员', 'operator')
    _create_user_raw(db, 'viewer', '123456', '查看者', 'viewer')


def _create_user_raw(db, username, password, display_name, role):
    user_id = str(uuid.uuid4())[:8]
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    db.execute(
        "INSERT INTO users (id, username, password_hash, salt, display_name, role) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, password_hash, salt, display_name, role)
    )
    return user_id


# ==================== 密码工具 ====================
def _hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000
    ).hex()


def _verify_password(password, salt, password_hash):
    return hmac.compare_digest(_hash_password(password, salt), password_hash)


# ==================== JWT ====================
def _b64url_encode(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(s):
    padding = 4 - len(s) % 4
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


def create_token(user_id, role, username, tier='free'):
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}))
    payload_data = {
        "uid": user_id,
        "role": role,
        "name": username,
        "tier": tier,
        "exp": int(time.time()) + TOKEN_EXPIRE,
        "iat": int(time.time()),
    }
    payload = _b64url_encode(json.dumps(payload_data))
    signature = hmac.new(
        JWT_SECRET.encode(), ("%s.%s" % (header, payload)).encode(), hashlib.sha256
    ).digest()
    sig = _b64url_encode(signature)
    return "%s.%s.%s" % (header, payload, sig)


def verify_token(token):
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header, payload, sig = parts
        expected_sig = _b64url_encode(
            hmac.new(JWT_SECRET.encode(), ("%s.%s" % (header, payload)).encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload_data = json.loads(_b64url_decode(payload))
        if payload_data.get('exp', 0) < time.time():
            return None
        return payload_data
    except Exception:
        return None


# ==================== Flask 中间件 ====================
def auth_required(min_role='viewer'):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            token = None
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
            if not token:
                token = request.args.get('token')
            if not token:
                return jsonify({"error": "未登录", "code": 401}), 401

            payload = verify_token(token)
            if not payload:
                return jsonify({"error": "登录已过期，请重新登录", "code": 401}), 401

            user_role_level = ROLES.get(payload.get('role'), 0)
            required_level = ROLES.get(min_role, 0)
            if user_role_level < required_level:
                return jsonify({"error": "权限不足", "code": 403}), 403

            g.user_id = payload['uid']
            g.user_role = payload['role']
            g.user_name = payload.get('name', '')
            g.user_tier = payload.get('tier', 'free')
            return f(*args, **kwargs)
        return wrapper
    return decorator


def optional_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        if not token:
            token = request.args.get('token')

        if token:
            payload = verify_token(token)
            if payload:
                g.user_id = payload['uid']
                g.user_role = payload['role']
                g.user_name = payload.get('name', '')
                g.user_tier = payload.get('tier', 'free')
                return f(*args, **kwargs)

        g.user_id = None
        g.user_role = None
        g.user_name = None
        g.user_tier = 'free'
        return f(*args, **kwargs)
    return wrapper


def premium_required(f):
    """装饰器：要求用户为 premium 或 admin"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        if not token:
            token = request.args.get('token')
        if not token:
            return jsonify({"error": "未登录", "code": 401}), 401

        payload = verify_token(token)
        if not payload:
            return jsonify({"error": "登录已过期，请重新登录", "code": 401}), 401

        tier = payload.get('tier', 'free')
        role = payload.get('role', 'viewer')
        if tier != 'premium' and role != 'admin':
            return jsonify({"error": "此功能需要升级到专业版", "code": 403, "upgrade": True}), 403

        g.user_id = payload['uid']
        g.user_role = role
        g.user_name = payload.get('name', '')
        g.user_tier = tier
        return f(*args, **kwargs)
    return wrapper


# ==================== 认证 API ====================
def register_auth_routes(app):

    @app.route('/api/auth/login', methods=['POST'])
    def auth_login():
        data = request.json or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({"error": "请输入用户名和密码"}), 400

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND status=1", (username,)
        ).fetchone()

        if not user:
            db.close()
            return jsonify({"error": "用户名或密码错误"}), 401

        if not _verify_password(password, user['salt'], user['password_hash']):
            db.close()
            return jsonify({"error": "用户名或密码错误"}), 401

        db.execute(
            "UPDATE users SET last_login=? WHERE id=?",
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user['id'])
        )
        db.commit()
        db.close()

        token = create_token(user['id'], user['role'], username, user['tier'] if 'tier' in user.keys() else 'free')
        return jsonify({
            "token": token,
            "user": {
                "id": user['id'],
                "username": user['username'],
                "display_name": user['display_name'],
                "role": user['role'],
                "tier": user['tier'] if 'tier' in user.keys() else 'free',
            }
        })

    @app.route('/api/auth/me', methods=['GET'])
    @auth_required()
    def auth_me():
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
        db.close()
        if not user:
            return jsonify({"error": "用户不存在"}), 404
        return jsonify({
            "user": {
                "id": user['id'],
                "username": user['username'],
                "display_name": user['display_name'],
                "role": user['role'],
                "tier": user['tier'] if 'tier' in user.keys() else 'free',
                "phone": user['phone'],
                "last_login": user['last_login'],
            }
        })

    @app.route('/api/auth/password', methods=['POST'])
    @auth_required()
    def auth_change_password():
        data = request.json or {}
        old_pwd = data.get('old_password', '')
        new_pwd = data.get('new_password', '')
        if not old_pwd or not new_pwd:
            return jsonify({"error": "请输入旧密码和新密码"}), 400
        if len(new_pwd) < 6:
            return jsonify({"error": "新密码至少6位"}), 400

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
        if not user or not _verify_password(old_pwd, user['salt'], user['password_hash']):
            db.close()
            return jsonify({"error": "旧密码错误"}), 401

        new_salt = secrets.token_hex(16)
        new_hash = _hash_password(new_pwd, new_salt)
        db.execute(
            "UPDATE users SET password_hash=?, salt=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_hash, new_salt, g.user_id)
        )
        db.commit()
        db.close()
        return jsonify({"message": "密码修改成功"})

    # ==================== 免费注册 ====================
    @app.route('/api/auth/register', methods=['POST'])
    def auth_register():
        data = request.json or {}
        username = data.get('username', '').strip()
        password = data.get('password', '')
        display_name = data.get('display_name', '').strip() or username

        if not username or not password:
            return jsonify({"error": "请输入用户名和密码"}), 400
        if len(username) < 2 or len(username) > 20:
            return jsonify({"error": "用户名长度2-20位"}), 400
        if len(password) < 6:
            return jsonify({"error": "密码至少6位"}), 400

        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if existing:
            db.close()
            return jsonify({"error": "用户名已存在"}), 400

        user_id = str(uuid.uuid4())[:8]
        salt = secrets.token_hex(16)
        password_hash = _hash_password(password, salt)
        db.execute(
            "INSERT INTO users (id, username, password_hash, salt, display_name, role, tier) "
            "VALUES (?, ?, ?, ?, ?, 'viewer', 'free')",
            (user_id, username, password_hash, salt, display_name)
        )
        db.commit()
        db.close()

        token = create_token(user_id, 'viewer', username, 'free')
        return jsonify({
            "message": "注册成功",
            "token": token,
            "user": {
                "id": user_id,
                "username": username,
                "display_name": display_name,
                "role": "viewer",
                "tier": "free",
            }
        })

    # ==================== 研判配额查询与消耗 ====================
    @app.route('/api/auth/judge-quota', methods=['GET'])
    @auth_required()
    def auth_judge_quota():
        """查询当前用户的研判剩余次数"""
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
        db.close()
        if not user:
            return jsonify({"error": "用户不存在"}), 404

        tier = user['tier'] if 'tier' in user.keys() else 'free'
        if tier == 'premium' or user['role'] == 'admin':
            return jsonify({"tier": tier, "limit": -1, "used": 0, "remaining": -1})

        today = datetime.now().strftime('%Y-%m-%d')
        judge_date = user['judge_date'] if 'judge_date' in user.keys() else ''
        used = int(user['judge_count']) if 'judge_count' in user.keys() and judge_date == today else 0
        return jsonify({
            "tier": tier,
            "limit": FREE_JUDGE_LIMIT,
            "used": used,
            "remaining": max(0, FREE_JUDGE_LIMIT - used),
        })

    @app.route('/api/auth/judge-quota', methods=['POST'])
    @auth_required()
    def auth_consume_judge():
        """消耗一次研判配额，返回是否允许"""
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE id=?", (g.user_id,)).fetchone()
        if not user:
            db.close()
            return jsonify({"error": "用户不存在"}), 404

        tier = user['tier'] if 'tier' in user.keys() else 'free'
        if tier == 'premium' or user['role'] == 'admin':
            db.close()
            return jsonify({"allowed": True, "remaining": -1})

        today = datetime.now().strftime('%Y-%m-%d')
        judge_date = user['judge_date'] if 'judge_date' in user.keys() else ''
        used = int(user['judge_count']) if 'judge_count' in user.keys() and judge_date == today else 0

        if used >= FREE_JUDGE_LIMIT:
            db.close()
            return jsonify({"allowed": False, "remaining": 0, "error": "今日免费研判次数已用完，请升级专业版"}), 403

        db.execute(
            "UPDATE users SET judge_count=?, judge_date=?, updated_at=datetime('now','localtime') WHERE id=?",
            (used + 1, today, g.user_id)
        )
        db.commit()
        db.close()
        return jsonify({"allowed": True, "remaining": FREE_JUDGE_LIMIT - used - 1})

    # ==================== 用户管理（仅 admin） ====================
    @app.route('/api/admin/users', methods=['GET'])
    @auth_required('admin')
    def admin_list_users():
        db = get_db()
        rows = db.execute(
            "SELECT id, username, display_name, role, phone, status, last_login, created_at "
            "FROM users ORDER BY created_at DESC"
        ).fetchall()
        db.close()
        return jsonify([dict(r) for r in rows])

    @app.route('/api/admin/users', methods=['POST'])
    @auth_required('admin')
    def admin_create_user():
        data = request.json or {}
        username = data.get('username', '').strip()
        password = data.get('password', '123456')
        display_name = data.get('display_name', username)
        role = data.get('role', 'viewer')

        if not username:
            return jsonify({"error": "用户名不能为空"}), 400
        if len(password) < 6:
            return jsonify({"error": "密码至少6位"}), 400

        db = get_db()
        try:
            uid = _create_user_raw(db, username, password, display_name, role)
            db.commit()
        except sqlite3.IntegrityError:
            db.close()
            return jsonify({"error": "用户名已存在"}), 400
        db.close()
        return jsonify({"message": "用户创建成功", "user_id": uid})

    @app.route('/api/admin/users/<user_id>', methods=['DELETE'])
    @auth_required('admin')
    def admin_delete_user(user_id):
        db = get_db()
        db.execute("UPDATE users SET status=0 WHERE id=?", (user_id,))
        db.commit()
        db.close()
        return jsonify({"message": "用户已禁用"})

    @app.route('/api/admin/users/<user_id>/reset-password', methods=['POST'])
    @auth_required('admin')
    def admin_reset_password(user_id):
        data = request.json or {}
        new_pwd = data.get('password', '123456')
        new_salt = secrets.token_hex(16)
        new_hash = _hash_password(new_pwd, new_salt)
        db = get_db()
        db.execute(
            "UPDATE users SET password_hash=?, salt=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_hash, new_salt, user_id)
        )
        db.commit()
        db.close()
        return jsonify({"message": "密码已重置"})
