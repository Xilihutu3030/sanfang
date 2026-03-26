# -*- coding: utf-8 -*-
"""
三防系统 - 高级功能模块
情景推演 / 任务派单 / 预警推送 / 协同指挥 / 历史对比 / 水位监测 / 自定义风险点
"""

import json
import math
import os
import queue
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from threading import Lock
from typing import Dict, List

from flask import Blueprint, request, jsonify, g, Response

from auth import get_db, auth_required, optional_auth, premium_required

premium = Blueprint('premium', __name__)


# ==================== 数据库表初始化 ====================

def init_premium_tables():
    """创建高级功能所需的数据库表"""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            judge_id TEXT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'pending',
            assigned_to TEXT DEFAULT '',
            assigned_name TEXT DEFAULT '',
            assigned_phone TEXT DEFAULT '',
            location TEXT DEFAULT '',
            lat REAL,
            lng REAL,
            due_time TEXT,
            completed_time TEXT,
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS alert_rules (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            condition_type TEXT NOT NULL,
            threshold REAL NOT NULL,
            notify_phones TEXT DEFAULT '',
            notify_webhook TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            last_triggered TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS alert_log (
            id TEXT PRIMARY KEY,
            rule_id TEXT,
            rule_name TEXT,
            trigger_value REAL,
            message TEXT,
            notified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS custom_hazards (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            level TEXT DEFAULT '',
            elevation REAL DEFAULT 0,
            description TEXT DEFAULT '',
            location TEXT DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            history_flood INTEGER DEFAULT 0,
            extra TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS water_stations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'river',
            lat REAL,
            lng REAL,
            warning_level REAL DEFAULT 0,
            danger_level REAL DEFAULT 0,
            current_level REAL DEFAULT 0,
            last_update TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS water_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            water_level REAL NOT NULL,
            flow_rate REAL,
            recorded_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS collab_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id TEXT,
            user_name TEXT,
            data TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS duty_staff (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            role TEXT DEFAULT '',
            group_name TEXT DEFAULT '',
            area TEXT DEFAULT '',
            on_duty INTEGER DEFAULT 1,
            yzy_userid TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            action TEXT NOT NULL,
            operator TEXT DEFAULT '',
            content TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    # 为已有的 alert_rules 表添加 notify_type 列（兼容旧库）
    try:
        db.execute("ALTER TABLE alert_rules ADD COLUMN notify_type TEXT DEFAULT 'toast'")
    except Exception:
        pass  # 列已存在
    # 为 tasks 表添加 feedback / accepted_at 列
    for col, default in [("feedback", "''"), ("accepted_at", "''"), ("notify_status", "'pending'")]:
        try:
            db.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT DEFAULT {default}")
        except Exception:
            pass
    _seed_water_stations(db)
    _seed_duty_staff(db)
    db.commit()
    db.close()


def _seed_water_stations(db):
    """初始化水位监测站数据"""
    count = db.execute("SELECT COUNT(*) as c FROM water_stations").fetchone()['c']
    if count > 0:
        return
    stations = [
        ("ws001", "猎德涌水文站", "river", 23.110, 113.328, 2.5, 3.5, 1.8),
        ("ws002", "沙河涌棠下站", "river", 23.135, 113.365, 3.0, 4.0, 2.1),
        ("ws003", "东濠涌越秀站", "river", 23.130, 113.275, 2.0, 3.0, 1.5),
        ("ws004", "白云湖水库", "reservoir", 23.220, 113.210, 15.0, 18.0, 12.3),
        ("ws005", "珠江黄埔潮位站", "tide", 23.095, 113.420, 1.8, 2.5, 0.9),
    ]
    for s in stations:
        db.execute(
            "INSERT INTO water_stations (id, name, type, lat, lng, warning_level, danger_level, current_level, last_update) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))",
            s
        )


def _seed_duty_staff(db):
    """初始化值班人员数据"""
    count = db.execute("SELECT COUNT(*) as c FROM duty_staff").fetchone()['c']
    if count > 0:
        return
    staff = [
        ("S001", "张伟", "13800138001", "巡查组长", "防汛一组", "天河区", 1),
        ("S002", "李强", "13800138002", "巡查员",   "防汛一组", "天河区", 1),
        ("S003", "王芳", "13800138003", "巡查组长", "防汛二组", "越秀区", 1),
        ("S004", "陈刚", "13800138004", "巡查员",   "防汛二组", "越秀区", 1),
        ("S005", "刘洋", "13800138005", "值班主任", "指挥中心", "全区域", 1),
        ("S006", "赵敏", "13800138006", "应急队长", "应急救援组", "全区域", 1),
        ("S007", "黄磊", "13800138007", "巡查员",   "防汛三组", "白云区", 1),
        ("S008", "周涛", "13800138008", "交通管控", "交警支队",  "全区域", 1),
    ]
    for s in staff:
        db.execute(
            "INSERT INTO duty_staff (id, name, phone, role, group_name, area, on_duty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", s
        )


# ==================== 值班人员管理 ====================

@premium.route('/api/staff', methods=['GET'])
def api_list_staff():
    """获取值班人员列表"""
    on_duty = request.args.get('on_duty', '')
    group = request.args.get('group', '')
    db = get_db()
    query = "SELECT * FROM duty_staff WHERE 1=1"
    params = []
    if on_duty:
        query += " AND on_duty=?"
        params.append(int(on_duty))
    if group:
        query += " AND group_name=?"
        params.append(group)
    query += " ORDER BY group_name, role DESC"
    rows = db.execute(query, params).fetchall()
    db.close()
    staff = [dict(r) for r in rows]
    groups = {}
    for s in staff:
        g = s.get('group_name', '未分组')
        if g not in groups:
            groups[g] = []
        groups[g].append(s)
    return jsonify({"staff": staff, "groups": groups, "total": len(staff)})


@premium.route('/api/staff', methods=['POST'])
def api_add_staff():
    """添加值班人员"""
    data = request.json or {}
    if not data.get('name'):
        return jsonify({"error": "姓名不能为空"}), 400
    sid = "S" + str(uuid.uuid4())[:6].upper()
    db = get_db()
    db.execute(
        "INSERT INTO duty_staff (id, name, phone, role, group_name, area, on_duty) VALUES (?,?,?,?,?,?,?)",
        (sid, data['name'], data.get('phone', ''), data.get('role', '巡查员'),
         data.get('group_name', ''), data.get('area', ''), 1)
    )
    db.commit()
    db.close()
    return jsonify({"message": "添加成功", "id": sid})


@premium.route('/api/staff/<sid>', methods=['DELETE'])
def api_delete_staff(sid):
    db = get_db()
    db.execute("DELETE FROM duty_staff WHERE id=?", (sid,))
    db.commit()
    db.close()
    return jsonify({"message": "删除成功"})


# ==================== 任务指派与通知 ====================

@premium.route('/api/tasks/<task_id>/assign', methods=['POST'])
@premium_required
def api_assign_task(task_id):
    """
    指派任务到具体人员
    body: { staff_id, staff_name, staff_phone }
    """
    data = request.json or {}
    staff_id = data.get('staff_id', '')
    staff_name = data.get('staff_name', '')
    staff_phone = data.get('staff_phone', '')

    if not staff_name:
        return jsonify({"error": "请选择指派人员"}), 400

    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        db.close()
        return jsonify({"error": "任务不存在"}), 404

    db.execute(
        "UPDATE tasks SET assigned_to=?, assigned_name=?, assigned_phone=?, "
        "status='in_progress', notify_status='sending', updated_at=datetime('now','localtime') WHERE id=?",
        (staff_id, staff_name, staff_phone, task_id)
    )
    # 记录操作日志
    db.execute(
        "INSERT INTO task_logs (task_id, action, operator, content) VALUES (?,?,?,?)",
        (task_id, 'assign', data.get('operator', ''), f"指派给 {staff_name}({staff_phone})")
    )
    db.commit()
    db.close()

    # 推送通知
    notify_result = _notify_task_assigned(task_id, dict(task), staff_name, staff_phone)

    _broadcast_event('task_assigned', {
        "task_id": task_id, "title": task['title'],
        "assigned_to": staff_name, "phone": staff_phone
    })
    return jsonify({
        "message": f"已指派给 {staff_name}",
        "notify": notify_result
    })


@premium.route('/api/tasks/<task_id>/feedback', methods=['POST'])
def api_task_feedback(task_id):
    """
    任务反馈（执行人上报进度/完成）
    body: { status: "in_progress"|"completed", feedback: "..." }
    """
    data = request.json or {}
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        db.close()
        return jsonify({"error": "任务不存在"}), 404

    new_status = data.get('status', task['status'])
    feedback = data.get('feedback', '')

    updates = ["feedback=?", "status=?", "updated_at=datetime('now','localtime')"]
    params = [feedback, new_status]

    if new_status == 'completed':
        updates.append("completed_time=datetime('now','localtime')")

    params.append(task_id)
    db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", params)

    action = 'complete' if new_status == 'completed' else 'feedback'
    db.execute(
        "INSERT INTO task_logs (task_id, action, operator, content) VALUES (?,?,?,?)",
        (task_id, action, task['assigned_name'], feedback or new_status)
    )
    db.commit()
    db.close()

    _broadcast_event('task_feedback', {
        "task_id": task_id, "title": task['title'],
        "status": new_status, "from": task['assigned_name']
    })
    return jsonify({"message": "反馈已提交"})


@premium.route('/api/tasks/<task_id>/logs', methods=['GET'])
def api_task_logs(task_id):
    """获取任务操作日志"""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM task_logs WHERE task_id=? ORDER BY created_at", (task_id,)
    ).fetchall()
    db.close()
    return jsonify({"logs": [dict(r) for r in rows]})


def _notify_task_assigned(task_id, task, staff_name, staff_phone):
    """发送任务通知"""
    result = {"sms": "skip", "yzy": "skip", "system": "ok"}

    title = task.get('title', '')
    desc = task.get('description', '')
    priority_labels = {'urgent': '紧急', 'high': '重要', 'normal': '普通'}
    pri = priority_labels.get(task.get('priority', ''), '普通')
    msg = f"[{pri}] {title}\n{desc}\n任务编号: {task_id}"

    # 1. 系统内SSE通知（总是发送）
    _broadcast_event('task', {
        "task_id": task_id, "title": title,
        "message": f"{staff_name} 收到新任务: {title}",
        "priority": task.get('priority', 'normal')
    })

    # 2. 粤政易推送（如果已配置）
    try:
        from yuezhengyi import is_configured, send_alert_message
        if is_configured():
            yzy_result = send_alert_message(
                [staff_name],  # 实际应传yzy_userid
                f"[三防任务] {title}",
                f"优先级: {pri}\n{desc}"
            )
            result["yzy"] = "sent" if yzy_result.get("errcode") == 0 else "failed"
    except Exception:
        pass

    # 3. 短信通知预留（需对接短信网关）
    if staff_phone:
        result["sms"] = "pending"  # TODO: 对接短信网关API

    return result

@premium.route('/api/simulate', methods=['POST'])
def api_simulate():
    """
    情景推演：输入假设雨量，模拟风险变化
    body: { rain_1h, rain_24h, warning_level, center, hazards, terrain }
    可一次模拟多个等级: { scenarios: [{rain_24h: 50}, {rain_24h: 100}] }
    """
    from ai_judge import ai_comprehensive_judge

    data = request.json or {}

    # 多情景批量模拟
    scenarios = data.get('scenarios')
    if scenarios:
        results = []
        base_terrain = data.get('terrain', {"最低高程": 25, "平均高程": 40})
        base_hazards = data.get('hazards', [])
        for sc in scenarios[:6]:  # 最多6个情景
            weather = {
                "rain_24h": sc.get("rain_24h", 0),
                "rain_1h": sc.get("rain_1h", 0),
                "warning_level": sc.get("warning_level", 0),
                "forecast": sc.get("forecast", ""),
                "forecast_rain_6h": sc.get("forecast_rain_6h", 0),
            }
            result = ai_comprehensive_judge(weather, base_terrain, base_hazards)
            results.append({
                "scenario": sc,
                "label": sc.get("label", ""),
                "result": result,
                "risk_level": result["1_综合风险等级"]["等级"],
                "risk_score": result["1_综合风险等级"]["得分"],
                "response_level": result["1_综合风险等级"]["响应等级"],
            })
        return jsonify({"results": results})

    # 单情景模拟
    weather = {
        "rain_24h": data.get("rain_24h", 50),
        "rain_1h": data.get("rain_1h", 10),
        "warning_level": data.get("warning_level", 0),
        "forecast": data.get("forecast", ""),
        "forecast_rain_6h": data.get("forecast_rain_6h", 0),
    }
    terrain = data.get("terrain", {"最低高程": 25, "平均高程": 40})
    hazards = data.get("hazards", [])

    result = ai_comprehensive_judge(weather, terrain, hazards)
    return jsonify({"result": result})


# ==================== 2. 任务派单 ====================

@premium.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    """获取任务列表"""
    status = request.args.get('status', '')
    db = get_db()
    if status:
        rows = db.execute(
            "SELECT * FROM tasks WHERE status=? ORDER BY "
            "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
            "created_at DESC", (status,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM tasks ORDER BY "
            "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, "
            "created_at DESC LIMIT 100"
        ).fetchall()
    db.close()

    tasks = [dict(r) for r in rows]
    stats = {
        "total": len(tasks),
        "pending": len([t for t in tasks if t['status'] == 'pending']),
        "in_progress": len([t for t in tasks if t['status'] == 'in_progress']),
        "completed": len([t for t in tasks if t['status'] == 'completed']),
    }
    return jsonify({"tasks": tasks, "stats": stats})


@premium.route('/api/tasks', methods=['POST'])
@premium_required
def api_create_task():
    """创建任务"""
    data = request.json or {}
    if not data.get('title'):
        return jsonify({"error": "任务标题不能为空"}), 400

    task_id = "T" + str(uuid.uuid4())[:6].upper()
    db = get_db()
    db.execute(
        "INSERT INTO tasks (id, judge_id, type, title, description, priority, "
        "assigned_to, assigned_name, assigned_phone, location, lat, lng, due_time, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, data.get('judge_id', ''), data.get('type', '巡查'),
         data['title'], data.get('description', ''), data.get('priority', 'normal'),
         data.get('assigned_to', ''), data.get('assigned_name', ''),
         data.get('assigned_phone', ''), data.get('location', ''),
         data.get('lat'), data.get('lng'), data.get('due_time', ''),
         data.get('created_by', ''))
    )
    db.commit()
    db.close()

    _broadcast_event('task_created', {"task_id": task_id, "title": data['title']})
    return jsonify({"message": "任务创建成功", "task_id": task_id})


@premium.route('/api/tasks/batch', methods=['POST'])
def api_create_tasks_batch():
    """从研判结果批量生成任务"""
    data = request.json or {}
    judge_result = data.get('judge_result', {})
    tasks_data = data.get('tasks', [])

    if not tasks_data and judge_result:
        # 从研判结果自动生成任务
        tasks_data = _generate_tasks_from_judge(judge_result)

    db = get_db()
    created = []
    for t in tasks_data:
        task_id = "T" + str(uuid.uuid4())[:6].upper()
        db.execute(
            "INSERT INTO tasks (id, judge_id, type, title, description, priority, "
            "location, lat, lng, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, t.get('judge_id', ''), t.get('type', '巡查'),
             t['title'], t.get('description', ''), t.get('priority', 'normal'),
             t.get('location', ''), t.get('lat'), t.get('lng'), t.get('created_by', ''))
        )
        created.append(task_id)
    db.commit()
    db.close()

    _broadcast_event('tasks_batch_created', {"count": len(created)})
    return jsonify({"message": f"已生成{len(created)}个任务", "task_ids": created})


@premium.route('/api/tasks/<task_id>', methods=['PUT'])
def api_update_task(task_id):
    """更新任务状态"""
    data = request.json or {}
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        db.close()
        return jsonify({"error": "任务不存在"}), 404

    updates = []
    params = []
    for field in ['status', 'assigned_to', 'assigned_name', 'assigned_phone', 'priority', 'description']:
        if field in data:
            updates.append(f"{field}=?")
            params.append(data[field])

    if data.get('status') == 'completed':
        updates.append("completed_time=?")
        params.append(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    if updates:
        updates.append("updated_at=datetime('now','localtime')")
        params.append(task_id)
        db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", params)
        db.commit()

    db.close()
    _broadcast_event('task_updated', {"task_id": task_id, "status": data.get('status', '')})
    return jsonify({"message": "更新成功"})


def _generate_tasks_from_judge(judge_result):
    """从研判结果智能生成任务"""
    tasks = []
    risk = judge_result.get("1_综合风险等级", {})
    score = int(str(risk.get("得分", "0")).split("/")[0])
    top5 = judge_result.get("3_Top5危险点位", [])
    suggestions = judge_result.get("5_指挥建议", [])

    # 从Top5生成巡查/封控任务
    for p in top5:
        action = p.get("处置建议", "巡查")
        priority = "urgent" if p.get("风险分", 0) >= 80 else ("high" if p.get("风险分", 0) >= 50 else "normal")
        task_type = "封控" if "封闭" in action or "封控" in action else ("转移" if "转移" in action else "巡查")
        tasks.append({
            "type": task_type,
            "title": f"{p['名称']} - {task_type}",
            "description": action,
            "priority": priority,
            "location": p.get("位置", ""),
        })

    # 高风险时额外生成指挥任务
    if score >= 70:
        tasks.append({
            "type": "指挥",
            "title": "启动应急响应",
            "description": risk.get("响应等级", "I级响应"),
            "priority": "urgent",
        })
        tasks.append({
            "type": "通知",
            "title": "发布避险通知",
            "description": "通过短信、广播、大喇叭等渠道通知居民",
            "priority": "urgent",
        })

    return tasks


# ==================== 3. 预警自动推送 ====================

@premium.route('/api/alerts/rules', methods=['GET'])
def api_list_alert_rules():
    """获取预警规则列表"""
    db = get_db()
    rows = db.execute("SELECT * FROM alert_rules ORDER BY created_at DESC").fetchall()
    db.close()
    return jsonify({"rules": [dict(r) for r in rows]})


@premium.route('/api/alerts/rules', methods=['POST'])
def api_create_alert_rule():
    """创建预警规则"""
    data = request.json or {}
    if not data.get('condition_type'):
        return jsonify({"error": "缺少监测指标"}), 400

    cond_labels = {'rain_24h': '24h雨量', 'rain_1h': '1h雨量', 'warning_level': '预警等级', 'risk_score': '风险评分'}
    name = data.get('name', cond_labels.get(data['condition_type'], data['condition_type']) + '>=' + str(data.get('threshold', 0)))

    rule_id = "AR" + str(uuid.uuid4())[:6].upper()
    notify_type = data.get('notify_type', 'toast')
    db = get_db()
    db.execute(
        "INSERT INTO alert_rules (id, name, condition_type, threshold, notify_type, notify_phones, notify_webhook, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (rule_id, name, data['condition_type'], data.get('threshold', 0),
         notify_type, data.get('notify_phones', ''), data.get('notify_webhook', ''),
         1 if data.get('enabled', True) else 0)
    )
    db.commit()
    db.close()
    return jsonify({"message": "规则创建成功", "rule_id": rule_id})


@premium.route('/api/alerts/rules/<rule_id>', methods=['DELETE'])
def api_delete_alert_rule(rule_id):
    db = get_db()
    db.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
    db.commit()
    db.close()
    return jsonify({"message": "删除成功"})


@premium.route('/api/alerts/log', methods=['GET'])
def api_alert_log():
    """获取预警日志"""
    db = get_db()
    rows = db.execute("SELECT * FROM alert_log ORDER BY created_at DESC LIMIT 50").fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


def check_alert_rules(weather_data):
    """检查所有预警规则，触发满足条件的"""
    db = get_db()
    rules = db.execute("SELECT * FROM alert_rules WHERE enabled=1").fetchall()

    triggered = []
    for rule in rules:
        ct = rule['condition_type']
        threshold = rule['threshold']
        current_value = None

        if ct == 'rain_24h':
            current_value = weather_data.get('rain_24h', 0)
        elif ct == 'rain_1h':
            current_value = weather_data.get('rain_1h', 0)
        elif ct == 'warning_level':
            current_value = weather_data.get('warning_level', 0)
        elif ct == 'risk_score':
            current_value = weather_data.get('risk_score', 0)

        if current_value is not None and current_value >= threshold:
            # 检查是否1小时内已触发过
            last = rule['last_triggered']
            if last:
                try:
                    last_dt = datetime.strptime(last, '%Y-%m-%d %H:%M:%S')
                    if (datetime.now() - last_dt).total_seconds() < 3600:
                        continue
                except Exception:
                    pass

            alert_id = "AL" + str(uuid.uuid4())[:6].upper()
            msg = f"[{rule['name']}] {ct} 达到 {current_value}，超过阈值 {threshold}"
            db.execute(
                "INSERT INTO alert_log (id, rule_id, rule_name, trigger_value, message) VALUES (?, ?, ?, ?, ?)",
                (alert_id, rule['id'], rule['name'], current_value, msg)
            )
            db.execute(
                "UPDATE alert_rules SET last_triggered=datetime('now','localtime') WHERE id=?",
                (rule['id'],)
            )
            triggered.append({"rule": rule['name'], "value": current_value, "message": msg})

            # Webhook 推送
            webhook = rule['notify_webhook']
            if webhook:
                _send_webhook(webhook, msg)

    if triggered:
        db.commit()
        _broadcast_event('alert_triggered', {"alerts": triggered})

    db.close()
    return triggered


def _send_webhook(url, message):
    """发送 webhook 通知（支持企业微信/钉钉/飞书）"""
    try:
        import requests
        payload = {
            "msgtype": "text",
            "text": {"content": f"[三防预警] {message}"}
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[webhook] send failed: {e}")


# ==================== 4. 多用户协同指挥（SSE）====================

_sse_clients = []
_sse_lock = Lock()


def _broadcast_event(event_type, data, user_name="system"):
    """广播事件给所有 SSE 客户端"""
    event_data = json.dumps({
        "type": event_type,
        "data": data,
        "user": user_name,
        "time": datetime.now().strftime('%H:%M:%S')
    }, ensure_ascii=False)

    # 记录到数据库
    try:
        db = get_db()
        db.execute(
            "INSERT INTO collab_events (event_type, user_name, data) VALUES (?, ?, ?)",
            (event_type, user_name, json.dumps(data, ensure_ascii=False))
        )
        # 只保留最近200条
        db.execute("DELETE FROM collab_events WHERE id NOT IN (SELECT id FROM collab_events ORDER BY id DESC LIMIT 200)")
        db.commit()
        db.close()
    except Exception:
        pass

    with _sse_lock:
        dead = []
        for client_q in _sse_clients:
            try:
                client_q.put_nowait(event_data)
            except Exception:
                dead.append(client_q)
        for d in dead:
            _sse_clients.remove(d)


@premium.route('/api/collab/events', methods=['GET'])
def api_sse_stream():
    """SSE 实时事件流"""
    def stream():
        q = queue.Queue(maxsize=50)
        with _sse_lock:
            _sse_clients.append(q)
        try:
            yield "data: {\"type\":\"connected\"}\n\n"
            while True:
                try:
                    data = q.get(timeout=30)
                    yield f"data: {data}\n\n"
                except queue.Empty:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)

    return Response(stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@premium.route('/api/collab/broadcast', methods=['POST'])
def api_broadcast():
    """手动广播消息（标注、指令等）"""
    data = request.json or {}
    _broadcast_event(
        data.get('type', 'message'),
        data.get('data', {}),
        data.get('user', 'unknown')
    )
    return jsonify({"message": "已广播"})


@premium.route('/api/collab/recent', methods=['GET'])
def api_recent_events():
    """获取最近的协同事件"""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM collab_events ORDER BY id DESC LIMIT 30"
    ).fetchall()
    db.close()
    return jsonify([dict(r) for r in rows])


# ==================== 5. 历史灾情对比 ====================

@premium.route('/api/history/compare', methods=['GET', 'POST'])
def api_history_compare():
    """历史灾情对比"""
    if request.method == 'POST':
        data = request.json or {}
    else:
        data = {}
    current_rain = float(request.args.get('rain_24h', 0)) if request.method == 'GET' else data.get('rain_24h', 0)
    current_score = float(request.args.get('risk_score', 0)) if request.method == 'GET' else data.get('risk_score', 0)

    db = get_db()
    rows = db.execute(
        "SELECT * FROM judge_history ORDER BY save_time DESC LIMIT 100"
    ).fetchall()
    db.close()

    similar = []
    for r in rows:
        try:
            result = json.loads(r['result'])
            hist_rain = 0
            hist_score = 0
            # 尝试从结果中提取雨量和分数
            factors = result.get('1_综合风险等级', {}).get('风险因子', [])
            score_str = result.get('1_综合风险等级', {}).get('得分', '0')
            hist_score = int(str(score_str).split('/')[0])

            for f in factors:
                if 'mm' in f:
                    try:
                        import re
                        nums = re.findall(r'[\d.]+', f)
                        if nums:
                            hist_rain = float(nums[0])
                    except Exception:
                        pass

            # 相似度：雨量差距 < 30mm 或 分数差距 < 20
            rain_diff = abs(current_rain - hist_rain)
            score_diff = abs(current_score - hist_score)

            if rain_diff < 30 or score_diff < 20:
                similar.append({
                    "time": r['save_time'],
                    "rain_24h": hist_rain,
                    "risk_score": hist_score,
                    "risk_level": result.get('1_综合风险等级', {}).get('等级', '?'),
                    "top5": result.get('3_Top5危险点位', []),
                    "suggestions_count": len(result.get('5_指挥建议', [])),
                    "rain_diff": rain_diff,
                    "similarity": max(0, 100 - int(rain_diff + score_diff)),
                })
        except Exception:
            continue

    similar.sort(key=lambda x: x['similarity'], reverse=True)
    return jsonify({"records": similar[:5], "total_history": len(rows)})


# ==================== 6. 水位监测 ====================

@premium.route('/api/water/stations', methods=['GET'])
def api_water_stations():
    """获取水位监测站列表"""
    db = get_db()
    rows = db.execute("SELECT * FROM water_stations ORDER BY name").fetchall()
    db.close()

    stations = []
    for r in rows:
        d = dict(r)
        current = d['current_level']
        warning = d['warning_level']
        danger = d['danger_level']
        if current >= danger:
            d['alert_status'] = 'danger'
        elif current >= warning:
            d['alert_status'] = 'warning'
        elif current >= warning * 0.8:
            d['alert_status'] = 'watch'
        else:
            d['alert_status'] = 'normal'
        stations.append(d)

    return jsonify({"stations": stations})


@premium.route('/api/water/stations/<station_id>/readings', methods=['GET'])
def api_water_readings(station_id):
    """获取水位历史数据（最近24小时）"""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM water_readings WHERE station_id=? ORDER BY recorded_at DESC LIMIT 48",
        (station_id,)
    ).fetchall()

    # 如果没有历史数据，生成模拟数据
    if not rows:
        station = db.execute("SELECT * FROM water_stations WHERE id=?", (station_id,)).fetchone()
        if station:
            _generate_mock_readings(db, station_id, station['current_level'])
            db.commit()
            rows = db.execute(
                "SELECT * FROM water_readings WHERE station_id=? ORDER BY recorded_at DESC LIMIT 48",
                (station_id,)
            ).fetchall()

    db.close()
    return jsonify([dict(r) for r in reversed(list(rows))])


@premium.route('/api/water/stations/<station_id>', methods=['PUT'])
def api_update_water_station(station_id):
    """更新水位（模拟传感器上报）"""
    data = request.json or {}
    level = data.get('water_level')
    if level is None:
        return jsonify({"error": "缺少water_level"}), 400

    db = get_db()
    db.execute(
        "UPDATE water_stations SET current_level=?, last_update=datetime('now','localtime') WHERE id=?",
        (level, station_id)
    )
    db.execute(
        "INSERT INTO water_readings (station_id, water_level, flow_rate) VALUES (?, ?, ?)",
        (station_id, level, data.get('flow_rate'))
    )
    db.commit()
    db.close()

    # 检查是否超警
    _check_water_alert(station_id, level)
    return jsonify({"message": "更新成功"})


def _generate_mock_readings(db, station_id, base_level):
    """生成模拟的24小时水位数据"""
    import random
    now = datetime.now()
    for i in range(48):
        t = now - timedelta(minutes=30 * (47 - i))
        # 模拟日间波动
        hour = t.hour
        tide_factor = math.sin((hour - 6) * math.pi / 12) * 0.3
        noise = random.uniform(-0.15, 0.15)
        level = base_level + tide_factor + noise
        db.execute(
            "INSERT INTO water_readings (station_id, water_level, recorded_at) VALUES (?, ?, ?)",
            (station_id, round(level, 2), t.strftime('%Y-%m-%d %H:%M:%S'))
        )


def _check_water_alert(station_id, level):
    """检查水位是否超警"""
    db = get_db()
    station = db.execute("SELECT * FROM water_stations WHERE id=?", (station_id,)).fetchone()
    db.close()
    if station and level >= station['warning_level']:
        status = "超危险水位" if level >= station['danger_level'] else "超警戒水位"
        _broadcast_event('water_alert', {
            "station": station['name'],
            "level": level,
            "status": status
        })


# ==================== 7. 自定义风险点管理 ====================

@premium.route('/api/custom-hazards', methods=['GET'])
def api_list_custom_hazards():
    """获取自定义风险点"""
    db = get_db()
    rows = db.execute("SELECT * FROM custom_hazards ORDER BY created_at DESC").fetchall()
    db.close()
    return jsonify({"hazards": [dict(r) for r in rows]})


@premium.route('/api/custom-hazards', methods=['POST'])
def api_create_custom_hazard():
    """添加自定义风险点"""
    data = request.json or {}
    if not data.get('name') or data.get('lat') is None or data.get('lng') is None:
        return jsonify({"error": "名称和坐标为必填"}), 400

    hid = "CH" + str(uuid.uuid4())[:6].upper()
    db = get_db()
    db.execute(
        "INSERT INTO custom_hazards (id, name, type, level, elevation, description, location, lat, lng, history_flood) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (hid, data['name'], data.get('type', '易涝点'), data.get('level', '一般'),
         data.get('elevation', 0), data.get('description', ''), data.get('location', ''),
         data['lat'], data['lng'], 1 if data.get('history_flood') else 0)
    )
    db.commit()
    db.close()
    _broadcast_event('hazard_created', {"id": hid, "name": data['name']})
    return jsonify({"message": "添加成功", "id": hid})


@premium.route('/api/custom-hazards/<hid>', methods=['PUT'])
def api_update_custom_hazard(hid):
    """更新风险点"""
    data = request.json or {}
    db = get_db()
    fields = ['name', 'type', 'level', 'elevation', 'description', 'location', 'lat', 'lng', 'history_flood']
    updates = []
    params = []
    for f in fields:
        if f in data:
            updates.append(f"{f}=?")
            params.append(data[f])
    if updates:
        updates.append("updated_at=datetime('now','localtime')")
        params.append(hid)
        db.execute(f"UPDATE custom_hazards SET {', '.join(updates)} WHERE id=?", params)
        db.commit()
    db.close()
    return jsonify({"message": "更新成功"})


@premium.route('/api/custom-hazards/<hid>', methods=['DELETE'])
def api_delete_custom_hazard(hid):
    """删除风险点"""
    db = get_db()
    db.execute("DELETE FROM custom_hazards WHERE id=?", (hid,))
    db.commit()
    db.close()
    return jsonify({"message": "删除成功"})
