# -*- coding: utf-8 -*-
"""
三防系统 - 高级功能模块
情景推演 / 任务派单 / 预警推送 / 协同指挥 / 历史对比 / 水位监测 / 自定义风险点 / 灾情上报
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
            assigned_wechat TEXT DEFAULT '',
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

        CREATE TABLE IF NOT EXISTS cameras (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'traffic',
            city TEXT DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            stream_url TEXT NOT NULL,
            protocol TEXT DEFAULT 'hls',
            source TEXT DEFAULT '',
            description TEXT DEFAULT '',
            thumbnail_url TEXT DEFAULT '',
            status TEXT DEFAULT 'online',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS disaster_reports (
            id TEXT PRIMARY KEY,
            user_id TEXT DEFAULT '',
            user_name TEXT DEFAULT '匿名市民',
            type TEXT DEFAULT 'flood',
            severity TEXT DEFAULT 'medium',
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            location TEXT DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            media TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            verified INTEGER DEFAULT 0,
            upvotes INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
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
    _seed_cameras(db)
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


def _seed_cameras(db):
    """初始化全国视频监控演示数据（含真实公开视频流）"""
    count = db.execute("SELECT COUNT(*) as c FROM cameras").fetchone()['c']
    if count > 0:
        return
    # ============ 真实公开HLS视频流 ============
    # 全国景区直播（中国电信天翼云监控 gcalic / gccncc / gctxyc CDN）
    scenic_streams = [
        "https://gcalic.v.myalicdn.com/gc/wgw05_1/index.m3u8?contentid=2820180516001",          # 0  全国风景总览
        "https://gcalic.v.myalicdn.com/gc/yxhcnh_1/index.m3u8?contentid=2820180516001",         # 1  黟县宏村南湖
        "https://gcalic.v.myalicdn.com/gc/yxxdpf_1/index.m3u8?contentid=2820180516001",         # 2  黟县西递牌坊
        "https://gcalic.v.myalicdn.com/gc/yxxdbst_1/index.m3u8?contentid=2820180516001",        # 3  黟县西递半山亭
        "https://gccncc.v.wscdns.com/gc/yxlcyt_1/index.m3u8?contentid=2820180516001",          # 4  黟县卢村远眺
        "https://gccncc.v.wscdns.com/gc/wygjt2_1/index.m3u8?contentid=2820180516001",          # 5  滕王阁
        "https://gcalic.v.myalicdn.com/gc/hswlf_1/index.m3u8?contentid=2820180516001",          # 6  黄山卧云峰
        "https://gccncc.v.wscdns.com/gc/hsmbsh_1/index.m3u8?contentid=2820180516001",          # 7  黄山梦笔生花
        "https://gcalic.v.myalicdn.com/gc/hspyt_1/index.m3u8?contentid=2820180516001",          # 8  黄山排云亭
        "https://gcalic.v.myalicdn.com/gc/hsxhdxg_1/index.m3u8?contentid=2820180516001",        # 9  黄山西海大峡谷
        "https://gccncc.v.wscdns.com/gc/hsgmd_1/index.m3u8?contentid=2820180516001",           # 10 黄山光明顶
        "https://gccncc.v.wscdns.com/gc/hsyg_1/index.m3u8?contentid=2820180516001",            # 11 黄山信兴道
        "https://gcalic.v.myalicdn.com/gc/hsptgz_1/index.m3u8?contentid=2820180516001",         # 12 黄山平天矼
        "https://gccncc.v.wscdns.com/gc/hsptgy_1/index.m3u8?contentid=2820180516001",          # 13 黄山飞来石
        "https://gcalic.v.myalicdn.com/gc/ytshsx_1/index.m3u8?contentid=2820180516001",         # 14 云台山红石硖
        "https://gcalic.v.myalicdn.com/gc/taishan02_1/index.m3u8?contentid=2820180516001",      # 15 泰山迎客松
        "https://gcalic.v.myalicdn.com/gc/taishan04_1/index.m3u8?contentid=2820180516001",      # 16 泰山拱北石
        "https://gcalic.v.myalicdn.com/gc/taishan06_1/index.m3u8?contentid=2820180516001",      # 17 泰山玉皇顶
        "https://gccncc.v.wscdns.com/gc/taishan07_1/index.m3u8?contentid=2820180516001",       # 18 泰山天街
        "https://gcalic.v.myalicdn.com/gc/taishan05_1/index.m3u8?contentid=2820180516001",      # 19 千佛山
        "https://gcalic.v.myalicdn.com/gc/wysynf_1/index.m3u8?contentid=2820180516001",         # 20 武夷山玉女峰
        "https://gccncc.v.wscdns.com/gc/zjjmht_1/index.m3u8?contentid=2820180516001",          # 21 张家界迷魂台
        "https://gcalic.v.myalicdn.com/gc/zjjafdxfs_1/index.m3u8?contentid=2820180516001",      # 22 张家界阿凡达悬浮山
        "https://gccncc.v.wscdns.com/gc/fhgcdgm_1/index.m3u8?contentid=2820180516001",         # 23 凤凰古城
        "https://gccncc.v.wscdns.com/gc/fhgcdnhs_1/index.m3u8?contentid=2820180516001",        # 24 凤凰古城南华山
        "https://gcalic.v.myalicdn.com/gc/emswfs_1/index.m3u8?contentid=2820180516001",         # 25 峨眉山万佛顶
        "https://gcalic.v.myalicdn.com/gc/emspxps_1/index.m3u8?contentid=2820180516001",        # 26 两江四岸
        "https://gccncc.v.wscdns.com/gc/lsdfgfl_1/index.m3u8?contentid=2820180516001",         # 27 长风商务区
        "https://gcalic.v.myalicdn.com/gc/hsxksqj_1/index.m3u8?contentid=2820180516001",        # 28 悬空寺全景
        "https://gcalic.v.myalicdn.com/gc/hsxkssqdzrqj_1/index.m3u8?contentid=2820180516001",   # 29 张家界大峡谷
        "https://gcalic.v.myalicdn.com/gc/hsxkscj_1/index.m3u8?contentid=2820180516001",        # 30 车八岭
        "https://gccncc.v.wscdns.com/gc/tyhjrys_1/index.m3u8?contentid=2820180516001",         # 31 大坝镇
        "https://gcalic.v.myalicdn.com/gc/mdjxxdsb_1/index.m3u8?contentid=2820180516001",       # 32 火星基地
        "https://gccncc.v.wscdns.com/gc/mdjxxmhjygjt_1/index.m3u8?contentid=2820180516001",    # 33 横店影视城
        "https://gccncc.v.wscdns.com/gc/ljgcdsc_1/index.m3u8?contentid=2820180516001",         # 34 胡杨林
        "https://gccncc.v.wscdns.com/gc/ztx_1/index.m3u8?contentid=2820180516001",             # 35 达古冰川
        "https://gcalic.v.myalicdn.com/gc/ztd_1/index.m3u8?contentid=2820180516001",            # 36 白头叶猴保护区
        "https://gccncc.v.wscdns.com/gc/ztn_1/index.m3u8?contentid=2820180516001",             # 37 象鼻山
        "https://gcalic.v.myalicdn.com/gc/ztb_1/index.m3u8?contentid=2820180516001",            # 38 广州塔
        "https://gctxyc.liveplay.myqcloud.com/gc/yxhcyz_1/index.m3u8?contentid=2820180516001",  # 39 黟县宏村月沼
        "https://gctxyc.liveplay.myqcloud.com/gc/wygjt1_1/index.m3u8?contentid=2820180516001",  # 40 婺源江岭
        "https://gctxyc.liveplay.myqcloud.com/gc/hssxf_1/index.m3u8?contentid=2820180516001",   # 41 黄山始信峰
        "https://gctxyc.liveplay.myqcloud.com/gc/taishan01_1/index.m3u8?contentid=2820180516001",# 42 泰山主峰
        "https://gctxyc.liveplay.myqcloud.com/gc/taishan03_1/index.m3u8?contentid=2820180516001",# 43 泰山大观峰
        "https://gctxyc.liveplay.myqcloud.com/gc/wysyxdhp_1/index.m3u8?contentid=2820180516001",# 44 印象大红袍
        "https://gctxyc.liveplay.myqcloud.com/gc/wysdhpcy_1/index.m3u8?contentid=2820180516001",# 45 武夷山大红袍茶园
        "https://gctxyc.liveplay.myqcloud.com/gc/zjjjjdl_1/index.m3u8?contentid=2820180516001", # 46 张家界将军列队
        "https://gctxyc.liveplay.myqcloud.com/gc/emsarm_1/index.m3u8?contentid=2820180516001",  # 47 峨眉云海日出
        "https://gctxyc.liveplay.myqcloud.com/gc/emsyh_1/index.m3u8?contentid=2820180516001",   # 48 贡嘎雪山
        "https://gctxyc.liveplay.myqcloud.com/gc/tyhjtynl_1/index.m3u8?contentid=2820180516001",# 49 天涯鸟瞰
        "https://gctxyc.liveplay.myqcloud.com/gc/tyhjtys_1/index.m3u8?contentid=2820180516001", # 50 天涯石
        "https://gctxyc.liveplay.myqcloud.com/gc/tyhjntyz_1/index.m3u8?contentid=2820180516001",# 51 南天一柱
        "https://gctxyc.liveplay.myqcloud.com/gc/mdjxxmhjyxj_1/index.m3u8?contentid=2820180516001",# 52 雪乡梦幻家园
        "https://gctxyc.liveplay.myqcloud.com/gc/jyg04_1/index.m3u8?contentid=2820180516001",   # 53 嘉峪关长城
        "https://gcalic.v.myalicdn.com/gc/bsszxbdlg_1/index.m3u8?contentid=2820180516001",      # 54 小布达拉宫
        "https://gcalic.v.myalicdn.com/gc/bssztt_1/index.m3u8?contentid=2820180516001",         # 55 远眺山庄
        "https://gcalic.v.myalicdn.com/gc/bsszjs_1/index.m3u8?contentid=2820180516001",         # 56 金山
        "https://gcalic.v.myalicdn.com/gc/wgw01_1/index.m3u8?contentid=2820180516001",          # 57 水长城镜头一
        "https://gcalic.v.myalicdn.com/gc/wgw02_1/index.m3u8?contentid=2820180516001",          # 58 水长城镜头二
        "https://gccncc.v.wscdns.com/gc/wgw03_1/index.m3u8?contentid=2820180516001",           # 59 水长城镜头三
        "https://gccncc.v.wscdns.com/gc/wgw04_1/index.m3u8?contentid=2820180516001",           # 60 水长城镜头四
        "https://gccncc.v.wscdns.com/gc/ljgcszsnkgc_1/index.m3u8?contentid=2820180516001",     # 61 滨海新区1
        "https://gcalic.v.myalicdn.com/gc/ljgcwglytylxs_1/index.m3u8?contentid=2820180516001",  # 62 滨海新区2
        "https://gcalic.v.myalicdn.com/gc/ljgcdyhxgjt_1/index.m3u8?contentid=2820180516001",    # 63 井冈山
        "https://gccncc.v.wscdns.com/gc/yxhcyz_1/index.m3u8?contentid=2820180516001",          # 64 宏村月沼
        "https://gccncc.v.wscdns.com/gc/ytsxzg_1/index.m3u8?contentid=2820180516001",          # 65 渔港码头
        "https://gccncc.v.wscdns.com/gc/ytsbjy_1/index.m3u8?contentid=2820180516001",          # 66 红山
        "https://gccncc.v.wscdns.com/gc/ytszyf_1/index.m3u8?contentid=2820180516001",          # 67 棋子湾
        "https://gccncc.v.wscdns.com/gc/zjjsrsm_1/index.m3u8?contentid=2820180516001",         # 68 雁荡山
        "https://gccncc.v.wscdns.com/gc/zsslsgc_1/index.m3u8?contentid=2820180516001",         # 69 开州
        # === 水利/桥梁/河流/湿地 直播流（CCTV直播中国 / 天翼视联） ===
        "https://gcalic.v.myalicdn.com/gc/zjjsrsm_1/index.m3u8",                                 # 70 京娘湖水库
        "https://gcalic.v.myalicdn.com/gc/xjtcdhsz_1/index.m3u8",                                # 71 京娘湖水库全景
        "https://gcalic.v.myalicdn.com/gc/zsslsjjfsd_1/index.m3u8",                              # 72 成都安顺廊桥/锦江
        "https://gcalic.v.myalicdn.com/gc/hkts09_1/index.m3u8",                                  # 73 哈尔滨霁虹桥/松花江
        "https://gcalic.v.myalicdn.com/gc/djyqyl1_1/index.m3u8",                                 # 74 深圳福田红树林
        "https://gcalic.v.myalicdn.com/gc/xwh01_1/index.m3u8",                                   # 75 南京玄武湖
        "http://gctxyc.liveplay.myqcloud.com/gc/zjwzbblh_1_md.m3u8",                             # 76 乌镇西市河
        "http://gcksc.v.kcdnvip.com/gc/ljgc_1/index.m3u8",                                      # 77 丽江古城鸟瞰
        "https://gctxyc.liveplay.myqcloud.com/gc/sxzl_1_md.m3u8",                                # 78 上海南浦大桥
        "https://gcalic.v.myalicdn.com/gc/syn_1/index.m3u8",                                     # 79 北京居庸关长城
        "http://gctxyc.liveplay.myqcloud.com/gc/zjwzblt_1_md.m3u8",                              # 80 乌镇白莲塔
    ]
    # (id, name, type, city, lat, lng, source, stream_index)
    # type: water-水利 | traffic-交通 | scenic-景区 | weather-气象应急 | flood-防汛 | public-社会公益
    # source: 水利公开 | 交通公开 | 天翼视联 | 气象应急 | 社会公益
    cameras = [
        # ===== 景区直播（真实流） =====
        ("CAM001", "黄山卧云峰", "scenic", "黄山", 30.1371, 118.1672, "天翼视联", 6),
        ("CAM002", "黄山光明顶", "scenic", "黄山", 30.1571, 118.1472, "天翼视联", 10),
        ("CAM003", "黄山梦笔生花", "scenic", "黄山", 30.1470, 118.1580, "天翼视联", 7),
        ("CAM004", "黄山排云亭", "scenic", "黄山", 30.1380, 118.1380, "天翼视联", 8),
        ("CAM005", "黄山西海大峡谷", "scenic", "黄山", 30.1350, 118.1300, "天翼视联", 9),
        ("CAM006", "黄山始信峰", "scenic", "黄山", 30.1500, 118.1750, "天翼视联", 41),
        ("CAM007", "黄山飞来石", "scenic", "黄山", 30.1410, 118.1420, "天翼视联", 13),
        ("CAM008", "黟县宏村南湖", "scenic", "黄山", 30.0715, 117.9885, "天翼视联", 1),
        ("CAM009", "黟县西递牌坊", "scenic", "黄山", 29.9019, 117.9920, "天翼视联", 2),
        ("CAM010", "泰山迎客松", "scenic", "泰安", 36.2371, 117.1014, "天翼视联", 15),
        ("CAM011", "泰山玉皇顶", "scenic", "泰安", 36.2571, 117.1114, "天翼视联", 17),
        ("CAM012", "泰山天街", "scenic", "泰安", 36.2500, 117.1050, "天翼视联", 18),
        ("CAM013", "泰山主峰", "scenic", "泰安", 36.2560, 117.1100, "天翼视联", 42),
        ("CAM014", "千佛山", "scenic", "济南", 36.6428, 117.0270, "天翼视联", 19),
        ("CAM015", "武夷山玉女峰", "scenic", "南平", 27.7516, 118.0217, "天翼视联", 20),
        ("CAM016", "武夷山大红袍茶园", "scenic", "南平", 27.7400, 118.0300, "天翼视联", 45),
        ("CAM017", "张家界迷魂台", "scenic", "张家界", 29.3170, 110.4393, "天翼视联", 21),
        ("CAM018", "张家界阿凡达悬浮山", "scenic", "张家界", 29.3250, 110.4500, "天翼视联", 22),
        ("CAM019", "张家界将军列队", "scenic", "张家界", 29.3300, 110.4450, "天翼视联", 46),
        ("CAM020", "凤凰古城", "scenic", "湘西", 27.9487, 109.5996, "天翼视联", 23),
        ("CAM021", "凤凰古城南华山", "scenic", "湘西", 27.9500, 109.6010, "天翼视联", 24),
        ("CAM022", "峨眉山万佛顶", "scenic", "乐山", 29.5964, 103.4340, "天翼视联", 25),
        ("CAM023", "峨眉云海日出", "scenic", "乐山", 29.5980, 103.4360, "天翼视联", 47),
        ("CAM024", "贡嘎雪山", "scenic", "甘孜", 29.5960, 101.8800, "天翼视联", 48),
        ("CAM025", "滕王阁", "scenic", "南昌", 28.6793, 115.8808, "天翼视联", 5),
        ("CAM026", "井冈山", "scenic", "吉安", 26.7253, 114.2997, "天翼视联", 63),
        ("CAM027", "婺源江岭", "scenic", "上饶", 29.3710, 117.7530, "天翼视联", 40),
        ("CAM028", "云台山红石硖", "scenic", "焦作", 35.4267, 113.3785, "天翼视联", 14),
        ("CAM029", "象鼻山", "scenic", "桂林", 25.2618, 110.3117, "天翼视联", 37),
        ("CAM030", "广州塔", "public", "广州", 23.1066, 113.3244, "天翼视联", 38),
        ("CAM031", "天涯海角鸟瞰", "scenic", "三亚", 18.2311, 109.3560, "天翼视联", 49),
        ("CAM032", "天涯石", "scenic", "三亚", 18.2315, 109.3565, "天翼视联", 50),
        ("CAM033", "南天一柱", "scenic", "三亚", 18.2320, 109.3550, "天翼视联", 51),
        ("CAM034", "嘉峪关长城", "scenic", "嘉峪关", 39.7729, 98.2916, "天翼视联", 53),
        ("CAM035", "悬空寺全景", "scenic", "大同", 39.6625, 113.7133, "天翼视联", 28),
        ("CAM036", "水长城景区一", "scenic", "北京", 40.4927, 116.3253, "天翼视联", 57),
        ("CAM037", "水长城景区二", "scenic", "北京", 40.4930, 116.3260, "天翼视联", 58),
        ("CAM038", "承德小布达拉宫", "scenic", "承德", 40.9873, 117.9387, "天翼视联", 54),
        ("CAM039", "承德避暑山庄远眺", "scenic", "承德", 40.9870, 117.9400, "天翼视联", 55),
        ("CAM040", "雪乡梦幻家园", "scenic", "哈尔滨", 44.0500, 128.9900, "天翼视联", 52),
        ("CAM041", "达古冰川", "scenic", "阿坝", 32.4200, 102.7600, "天翼视联", 35),
        ("CAM042", "横店影视城", "scenic", "金华", 29.1595, 120.3100, "天翼视联", 33),
        ("CAM043", "雁荡山", "scenic", "温州", 28.3870, 121.0570, "天翼视联", 68),
        # ===== 水利监控（含真实水系直播流） =====
        ("CAM044", "永定河水利监控", "water", "北京", 39.8550, 116.2108, "水利公开", 57),
        ("CAM045", "黄浦江水利监控", "water", "上海", 31.2200, 121.4900, "水利公开", 78),
        ("CAM046", "秦淮河水利监控", "water", "南京", 32.0200, 118.7800, "水利公开", 75),
        ("CAM047", "钱塘江水利监控", "water", "杭州", 30.2100, 120.2100, "水利公开", 68),
        ("CAM048", "珠江水利监控", "water", "广州", 23.1050, 113.3200, "水利公开", 38),
        ("CAM049", "湘江水利监控", "water", "长沙", 28.1900, 112.9500, "水利公开", 26),
        ("CAM050", "黄河花园口水利监控", "water", "郑州", 34.9100, 113.6600, "水利公开", 14),
        ("CAM051", "嘉陵江水利监控", "water", "重庆", 29.5700, 106.5600, "水利公开", 69),
        ("CAM052", "锦江水利监控", "water", "成都", 30.5700, 104.0800, "水利公开", 72),
        ("CAM053", "松花江水利监控", "water", "哈尔滨", 45.7750, 126.6300, "水利公开", 73),
        ("CAM054", "浑河水利监控", "water", "沈阳", 41.7500, 123.4200, "水利公开", 27),
        ("CAM055", "汉江水利监控", "water", "武汉", 30.5700, 114.2500, "水利公开", 61),
        ("CAM056", "赣江水利监控", "water", "南昌", 28.6700, 115.8600, "水利公开", 5),
        ("CAM057", "闽江水利监控", "water", "福州", 26.0500, 119.3100, "水利公开", 44),
        ("CAM058", "洞庭湖水利监控", "water", "岳阳", 29.0700, 112.9500, "水利公开", 24),
        ("CAM059", "鄱阳湖水利监控", "water", "九江", 29.1200, 116.2700, "水利公开", 63),
        ("CAM060", "太湖水利监控", "water", "苏州", 31.2200, 120.2200, "水利公开", 33),
        ("CAM061", "滇池水利监控", "water", "昆明", 24.9000, 102.6800, "水利公开", 36),
        ("CAM062", "黄河兰州段水利监控", "water", "兰州", 36.0600, 103.8300, "水利公开", 34),
        ("CAM063", "渭河水利监控", "water", "西安", 34.3500, 108.9300, "水利公开", 31),
        # ===== 交通监控（真实景区流 + 按实际交通枢纽定位） =====
        ("CAM064", "长安街交通监控", "traffic", "北京", 39.9042, 116.3974, "交通公开", 58),
        ("CAM065", "西二环立交监控", "traffic", "北京", 39.9130, 116.3560, "交通公开", 59),
        ("CAM066", "外滩交通监控", "traffic", "上海", 31.2304, 121.4737, "交通公开", 62),
        ("CAM067", "南京路步行街监控", "traffic", "上海", 31.2350, 121.4750, "交通公开", 60),
        ("CAM068", "长江大桥南京段监控", "traffic", "南京", 32.1000, 118.7400, "交通公开", 1),
        ("CAM069", "新街口交通监控", "traffic", "南京", 32.0480, 118.7780, "交通公开", 2),
        ("CAM070", "天河立交监控", "traffic", "广州", 23.1340, 113.3220, "交通公开", 30),
        ("CAM071", "深南大道交通监控", "traffic", "深圳", 22.5431, 114.0579, "交通公开", 66),
        ("CAM072", "深圳湾大桥监控", "traffic", "深圳", 22.5000, 113.9500, "交通公开", 67),
        ("CAM073", "长江大桥武汉段监控", "traffic", "武汉", 30.5550, 114.2800, "交通公开", 3),
        ("CAM074", "解放碑交通监控", "traffic", "重庆", 29.5580, 106.5780, "交通公开", 4),
        ("CAM075", "天府广场交通监控", "traffic", "成都", 30.5728, 104.0668, "交通公开", 25),
        ("CAM076", "五一广场交通监控", "traffic", "长沙", 28.1975, 112.9680, "交通公开", 21),
        ("CAM077", "二七广场交通监控", "traffic", "郑州", 34.7533, 113.6544, "交通公开", 28),
        ("CAM078", "钟楼交通监控", "traffic", "西安", 34.2610, 108.9426, "交通公开", 29),
        ("CAM079", "中央大街交通监控", "traffic", "哈尔滨", 45.7706, 126.6178, "交通公开", 32),
        # ===== 防汛内涝监测 =====
        ("CAM080", "珠江新城内涝监测", "flood", "广州", 23.1190, 113.3200, "水利公开", 38),
        ("CAM081", "东湖内涝监测", "flood", "武汉", 30.5460, 114.3700, "水利公开", 61),
        ("CAM082", "洪崖洞内涝监测", "flood", "重庆", 29.5610, 106.5760, "水利公开", 69),
        # ===== 社会公益（城市地标） =====
        ("CAM083", "滨海新区城市监控", "public", "天津", 39.0100, 117.7200, "社会公益", 61),
        ("CAM084", "渔港码头", "public", "烟台", 37.4630, 121.4550, "社会公益", 65),
        ("CAM085", "红山公园", "public", "乌鲁木齐", 43.8225, 87.6168, "社会公益", 66),
        ("CAM086", "棋子湾海景", "public", "海口", 19.9150, 109.1700, "社会公益", 67),
        ("CAM087", "开州城区监控", "public", "重庆", 31.1600, 108.3930, "社会公益", 69),
        # ===== 水利/桥梁 真实直播流监控 =====
        ("CAM088", "京娘湖水库监控", "water", "邯郸", 36.4320, 113.7260, "水利公开", 70),
        ("CAM089", "京娘湖水库全景", "water", "邯郸", 36.4330, 113.7270, "水利公开", 71),
        ("CAM090", "深圳福田红树林湿地", "water", "深圳", 22.5270, 114.0030, "水利公开", 74),
        ("CAM091", "乌镇西市河水系", "water", "嘉兴", 30.7440, 120.4870, "水利公开", 76),
        ("CAM092", "丽江古城水系", "scenic", "丽江", 26.8725, 100.2330, "天翼视联", 77),
        ("CAM093", "居庸关长城", "scenic", "北京", 40.2910, 116.0700, "天翼视联", 79),
        ("CAM094", "乌镇白莲塔", "scenic", "嘉兴", 30.7460, 120.4880, "天翼视联", 80),
    ]
    for cam in cameras:
        cam_id, name, cam_type, city, lat, lng, source, stream_idx = cam
        stream_url = scenic_streams[stream_idx]
        db.execute(
            "INSERT OR IGNORE INTO cameras (id, name, type, city, lat, lng, stream_url, protocol, source, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'hls', ?, 'online')",
            (cam_id, name, cam_type, city, lat, lng, stream_url, source)
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
    body: { staff_id, staff_name, staff_phone, staff_wechat }
    """
    data = request.json or {}
    staff_id = data.get('staff_id', '')
    staff_name = data.get('staff_name', '')
    staff_phone = data.get('staff_phone', '')
    staff_wechat = data.get('staff_wechat', '')

    if not staff_name:
        return jsonify({"error": "请选择指派人员"}), 400

    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not task:
        db.close()
        return jsonify({"error": "任务不存在"}), 404

    # 尝试添加 assigned_wechat 列（兼容旧数据库）
    try:
        db.execute("ALTER TABLE tasks ADD COLUMN assigned_wechat TEXT DEFAULT ''")
        db.commit()
    except Exception:
        pass

    db.execute(
        "UPDATE tasks SET assigned_to=?, assigned_name=?, assigned_phone=?, assigned_wechat=?, "
        "status='in_progress', updated_at=datetime('now','localtime') WHERE id=?",
        (staff_id, staff_name, staff_phone, staff_wechat, task_id)
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

    # 生成微信通知文本
    notify_text = _build_wechat_notify_text(task_id, dict(task), staff_name)

    _broadcast_event('task_assigned', {
        "task_id": task_id, "title": task['title'],
        "assigned_to": staff_name, "phone": staff_phone
    })
    return jsonify({
        "message": f"已指派给 {staff_name}",
        "notify": notify_result,
        "notify_text": notify_text
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


def _build_wechat_notify_text(task_id, task, staff_name):
    """生成微信通知文本"""
    priority_labels = {'urgent': '紧急', 'high': '重要', 'normal': '普通'}
    pri = priority_labels.get(task.get('priority', ''), '普通')
    title = task.get('title', '')
    desc = task.get('description', '')
    now = datetime.now().strftime('%Y-%m-%d %H:%M')

    lines = [
        '【三防任务通知】',
        '━━━━━━━━━━━━',
        f'任务: {title}',
        f'优先级: {pri}',
    ]
    if desc:
        lines.append(f'内容: {desc}')
    if task.get('location'):
        lines.append(f'地点: {task["location"]}')
    lines.extend([
        f'负责人: {staff_name}',
        f'指派时间: {now}',
        '━━━━━━━━━━━━',
        '请尽快查看并处理，完成后请回复反馈。'
    ])
    return '\n'.join(lines)


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


# ==================== 8. 视频监控管理 ====================

@premium.route('/api/cameras', methods=['GET'])
def api_list_cameras():
    """获取摄像头列表（支持城市/类型/视口筛选）"""
    cam_type = request.args.get('type', '')
    city = request.args.get('city', '')
    bounds = request.args.get('bounds', '')
    db = get_db()
    query = "SELECT * FROM cameras WHERE 1=1"
    params = []
    if cam_type:
        query += " AND type=?"
        params.append(cam_type)
    if city:
        query += " AND city=?"
        params.append(city)
    if bounds:
        parts = bounds.split(',')
        if len(parts) == 4:
            sw_lat, sw_lng, ne_lat, ne_lng = [float(p) for p in parts]
            query += " AND lat>=? AND lat<=? AND lng>=? AND lng<=?"
            params.extend([sw_lat, ne_lat, sw_lng, ne_lng])
    query += " ORDER BY city, name"
    rows = db.execute(query, params).fetchall()
    db.close()
    return jsonify({"cameras": [dict(r) for r in rows]})


@premium.route('/api/cameras', methods=['POST'])
def api_create_camera():
    """添加摄像头"""
    data = request.json or {}
    if not data.get('name') or data.get('lat') is None or data.get('lng') is None or not data.get('stream_url'):
        return jsonify({"error": "名称、坐标和视频流地址为必填"}), 400

    cam_id = "CAM" + str(uuid.uuid4())[:6].upper()
    db = get_db()
    db.execute(
        "INSERT INTO cameras (id, name, type, city, lat, lng, stream_url, protocol, source, description, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cam_id, data['name'], data.get('type', 'traffic'), data.get('city', ''),
         data['lat'], data['lng'], data['stream_url'], data.get('protocol', 'hls'),
         data.get('source', ''), data.get('description', ''), data.get('status', 'online'))
    )
    db.commit()
    db.close()
    return jsonify({"message": "添加成功", "id": cam_id})


@premium.route('/api/cameras/<cam_id>', methods=['PUT'])
def api_update_camera(cam_id):
    """更新摄像头信息"""
    data = request.json or {}
    db = get_db()
    fields = ['name', 'type', 'city', 'lat', 'lng', 'stream_url', 'protocol', 'source', 'description', 'status']
    updates = []
    params = []
    for f in fields:
        if f in data:
            updates.append(f"{f}=?")
            params.append(data[f])
    if updates:
        params.append(cam_id)
        db.execute(f"UPDATE cameras SET {', '.join(updates)} WHERE id=?", params)
        db.commit()
    db.close()
    return jsonify({"message": "更新成功"})


@premium.route('/api/cameras/<cam_id>', methods=['DELETE'])
def api_delete_camera(cam_id):
    """删除摄像头"""
    db = get_db()
    db.execute("DELETE FROM cameras WHERE id=?", (cam_id,))
    db.commit()
    db.close()
    return jsonify({"message": "删除成功"})


# ==================== 9. 灾情上报（市民众源情报） ====================

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'reports')
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 允许的文件类型
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov', 'avi'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@premium.route('/api/reports/upload', methods=['POST'])
def api_upload_report_media():
    """上传灾情图片/视频，返回文件路径"""
    if 'file' not in request.files:
        return jsonify({"error": "未选择文件"}), 400
    f = request.files['file']
    if not f.filename or not _allowed_file(f.filename):
        return jsonify({"error": "不支持的文件格式"}), 400

    # 检查文件大小
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"error": "文件大小超过50MB限制"}), 400

    ext = f.filename.rsplit('.', 1)[1].lower()
    # 按日期分目录
    date_dir = datetime.now().strftime('%Y%m%d')
    save_dir = os.path.join(UPLOAD_DIR, date_dir)
    os.makedirs(save_dir, exist_ok=True)

    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    filepath = os.path.join(save_dir, filename)
    f.save(filepath)

    # 返回相对路径（供前端访问）
    url = f"/uploads/reports/{date_dir}/{filename}"
    file_type = 'video' if ext in ('mp4', 'mov', 'avi') else 'image'
    return jsonify({"url": url, "type": file_type, "size": size})


@premium.route('/api/reports', methods=['POST'])
def api_create_report():
    """
    创建灾情上报
    body: { title, type, severity, description, lat, lng, location, media: [{url, type}], user_name }
    type: flood-积水内涝 | landslide-山体滑坡 | wind-大风倒树 | road-道路损毁 | rescue-人员被困 | other-其他
    severity: low-轻微 | medium-中等 | high-严重 | critical-危急
    """
    data = request.json or {}
    if not data.get('title'):
        return jsonify({"error": "请填写灾情标题"}), 400
    if data.get('lat') is None or data.get('lng') is None:
        return jsonify({"error": "请提供定位信息"}), 400

    report_id = "DR" + datetime.now().strftime('%m%d') + str(uuid.uuid4())[:6].upper()
    media = json.dumps(data.get('media', []), ensure_ascii=False)

    db = get_db()
    db.execute(
        "INSERT INTO disaster_reports "
        "(id, user_id, user_name, type, severity, title, description, location, lat, lng, media, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
        (report_id, data.get('user_id', ''), data.get('user_name', '匿名市民'),
         data.get('type', 'flood'), data.get('severity', 'medium'),
         data['title'], data.get('description', ''),
         data.get('location', ''), data['lat'], data['lng'], media)
    )
    db.commit()
    db.close()

    # 广播新上报事件
    _broadcast_event('disaster_report', {
        "report_id": report_id,
        "title": data['title'],
        "type": data.get('type', 'flood'),
        "severity": data.get('severity', 'medium'),
        "lat": data['lat'],
        "lng": data['lng'],
        "user": data.get('user_name', '匿名市民'),
    })

    return jsonify({"message": "上报成功", "id": report_id})


@premium.route('/api/reports', methods=['GET'])
def api_list_reports():
    """
    获取灾情上报列表
    支持筛选: ?type=flood&status=pending&hours=24&bounds=sw_lat,sw_lng,ne_lat,ne_lng
    """
    report_type = request.args.get('type', '')
    status = request.args.get('status', '')
    hours = request.args.get('hours', '')
    bounds = request.args.get('bounds', '')

    db = get_db()
    query = "SELECT * FROM disaster_reports WHERE 1=1"
    params = []

    if report_type:
        query += " AND type=?"
        params.append(report_type)
    if status:
        query += " AND status=?"
        params.append(status)
    if hours:
        query += " AND created_at >= datetime('now', 'localtime', ?)"
        params.append(f"-{int(hours)} hours")
    if bounds:
        parts = bounds.split(',')
        if len(parts) == 4:
            sw_lat, sw_lng, ne_lat, ne_lng = [float(p) for p in parts]
            query += " AND lat>=? AND lat<=? AND lng>=? AND lng<=?"
            params.extend([sw_lat, ne_lat, sw_lng, ne_lng])

    query += " ORDER BY created_at DESC LIMIT 200"
    rows = db.execute(query, params).fetchall()
    db.close()

    reports = []
    for r in rows:
        d = dict(r)
        try:
            d['media'] = json.loads(d.get('media', '[]'))
        except Exception:
            d['media'] = []
        reports.append(d)

    # 统计
    stats = {
        "total": len(reports),
        "pending": len([r for r in reports if r['status'] == 'pending']),
        "verified": len([r for r in reports if r.get('verified')]),
        "by_type": {},
        "by_severity": {},
    }
    for r in reports:
        t = r.get('type', 'other')
        s = r.get('severity', 'medium')
        stats["by_type"][t] = stats["by_type"].get(t, 0) + 1
        stats["by_severity"][s] = stats["by_severity"].get(s, 0) + 1

    return jsonify({"reports": reports, "stats": stats})


@premium.route('/api/reports/<report_id>', methods=['GET'])
def api_get_report(report_id):
    """获取单条灾情上报详情"""
    db = get_db()
    row = db.execute("SELECT * FROM disaster_reports WHERE id=?", (report_id,)).fetchone()
    db.close()
    if not row:
        return jsonify({"error": "上报不存在"}), 404
    d = dict(row)
    try:
        d['media'] = json.loads(d.get('media', '[]'))
    except Exception:
        d['media'] = []
    return jsonify(d)


@premium.route('/api/reports/<report_id>', methods=['PUT'])
def api_update_report(report_id):
    """
    更新灾情上报状态（审核/确认/关闭）
    body: { status: "verified"|"processing"|"resolved"|"rejected", verified: 1 }
    """
    data = request.json or {}
    db = get_db()
    row = db.execute("SELECT * FROM disaster_reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "上报不存在"}), 404

    updates = ["updated_at=datetime('now','localtime')"]
    params = []
    for field in ['status', 'verified', 'severity', 'description']:
        if field in data:
            updates.append(f"{field}=?")
            params.append(data[field])

    params.append(report_id)
    db.execute(f"UPDATE disaster_reports SET {', '.join(updates)} WHERE id=?", params)
    db.commit()
    db.close()

    new_status = data.get('status', row['status'])
    _broadcast_event('report_updated', {
        "report_id": report_id, "title": row['title'], "status": new_status
    })
    return jsonify({"message": "更新成功"})


@premium.route('/api/reports/<report_id>', methods=['DELETE'])
def api_delete_report(report_id):
    """删除灾情上报"""
    db = get_db()
    db.execute("DELETE FROM disaster_reports WHERE id=?", (report_id,))
    db.commit()
    db.close()
    return jsonify({"message": "删除成功"})


@premium.route('/api/reports/<report_id>/upvote', methods=['POST'])
def api_upvote_report(report_id):
    """点赞/确认上报（多人确认同一灾情增加可信度）"""
    db = get_db()
    db.execute("UPDATE disaster_reports SET upvotes = upvotes + 1 WHERE id=?", (report_id,))
    db.commit()
    row = db.execute("SELECT upvotes FROM disaster_reports WHERE id=?", (report_id,)).fetchone()
    db.close()
    count = row['upvotes'] if row else 0
    return jsonify({"message": "已确认", "upvotes": count})


@premium.route('/api/reports/summary', methods=['GET'])
def api_reports_summary():
    """
    灾情上报汇总摘要 - 供AI研判系统使用
    返回最近N小时内的灾情上报统计和关键信息
    ?hours=6&lat=23.13&lng=113.27&radius=50
    """
    hours = int(request.args.get('hours', 6))
    center_lat = request.args.get('lat', type=float)
    center_lng = request.args.get('lng', type=float)
    radius_km = float(request.args.get('radius', 50))

    db = get_db()
    query = "SELECT * FROM disaster_reports WHERE created_at >= datetime('now', 'localtime', ?) ORDER BY created_at DESC"
    rows = db.execute(query, (f"-{hours} hours",)).fetchall()
    db.close()

    reports = [dict(r) for r in rows]

    # 按距离过滤（如果提供了中心坐标）
    if center_lat is not None and center_lng is not None:
        filtered = []
        for r in reports:
            dist = _haversine(center_lat, center_lng, r['lat'], r['lng'])
            if dist <= radius_km:
                r['distance_km'] = round(dist, 1)
                filtered.append(r)
        reports = filtered

    # 生成文本摘要供AI使用
    summary_lines = []
    type_labels = {
        'flood': '积水内涝', 'landslide': '山体滑坡', 'wind': '大风倒树',
        'road': '道路损毁', 'rescue': '人员被困', 'other': '其他'
    }
    severity_labels = {'low': '轻微', 'medium': '中等', 'high': '严重', 'critical': '危急'}

    type_counts = {}
    severity_counts = {}
    critical_reports = []

    for r in reports:
        t = r.get('type', 'other')
        s = r.get('severity', 'medium')
        type_counts[t] = type_counts.get(t, 0) + 1
        severity_counts[s] = severity_counts.get(s, 0) + 1
        if s in ('high', 'critical'):
            critical_reports.append(r)

    if reports:
        summary_lines.append(f"最近{hours}小时内收到{len(reports)}条市民灾情上报：")
        for t, c in type_counts.items():
            summary_lines.append(f"  - {type_labels.get(t, t)}: {c}条")
        if critical_reports:
            summary_lines.append(f"其中严重/危急上报{len(critical_reports)}条：")
            for cr in critical_reports[:5]:
                loc = cr.get('location', '') or f"({cr['lat']:.4f},{cr['lng']:.4f})"
                summary_lines.append(
                    f"  [{severity_labels.get(cr['severity'], '?')}] {cr['title']} - {loc}"
                )
                if cr.get('description'):
                    summary_lines.append(f"    描述: {cr['description'][:80]}")
                if cr.get('upvotes', 0) > 0:
                    summary_lines.append(f"    {cr['upvotes']}人确认")
    else:
        summary_lines.append(f"最近{hours}小时内无市民灾情上报。")

    return jsonify({
        "total": len(reports),
        "reports": reports,
        "type_counts": type_counts,
        "severity_counts": severity_counts,
        "critical_count": len(critical_reports),
        "summary_text": "\n".join(summary_lines),
    })


def _haversine(lat1, lng1, lat2, lng2):
    """计算两点间距离（公里）"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ==================== 二维码生成 API ====================

@premium.route('/api/qrcode', methods=['GET'])
def api_generate_qrcode():
    """
    生成二维码图片
    GET /api/qrcode?url=https://xxx/report?r=天河区&org=应急局&ch=qrcode
    可选参数:
      size: 图片尺寸，默认300
      format: 输出格式 png(默认)
    返回: PNG图片二进制流
    """
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({"error": "缺少url参数"}), 400

    size = min(int(request.args.get('size', 300)), 800)

    try:
        import qrcode
        from io import BytesIO
        from flask import make_response

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        # 缩放到目标尺寸
        img = img.resize((size, size))

        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = make_response(buf.read())
        resp.headers['Content-Type'] = 'image/png'
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp
    except ImportError:
        return jsonify({"error": "服务端未安装qrcode库，请执行 pip install qrcode[pil]"}), 500
    except Exception as e:
        return jsonify({"error": f"二维码生成失败: {str(e)}"}), 500


@premium.route('/api/qrcode/poster', methods=['GET'])
def api_generate_poster():
    """
    生成带二维码的灾情上报海报图片
    GET /api/qrcode/poster?region=天河区&org=天河区应急管理局
    可选: base_url(上报页地址前缀)
    返回: PNG图片
    """
    region = request.args.get('region', '').strip()
    org = request.args.get('org', '').strip()
    if not region:
        return jsonify({"error": "缺少region参数"}), 400

    base_url = request.args.get('base_url', '').strip()
    if not base_url:
        base_url = request.host_url.rstrip('/') + '/report'

    # 构建上报链接
    params = f"?r={region}&ch=qrcode"
    if org:
        params += f"&org={org}"
    report_url = base_url + params

    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont
        from io import BytesIO
        from flask import make_response

        W, H = 600, 800

        poster = Image.new('RGB', (W, H), '#ffffff')
        draw = ImageDraw.Draw(poster)

        # 顶部渐变蓝条（用纯色替代，PIL不方便做渐变）
        draw.rectangle([0, 0, W, 120], fill='#0277bd')

        # 文字（使用默认字体，中文可能需要系统有中文字体）
        try:
            font_title = ImageFont.truetype("msyh.ttc", 32)
            font_sub = ImageFont.truetype("msyh.ttc", 18)
            font_small = ImageFont.truetype("msyh.ttc", 14)
            font_tip = ImageFont.truetype("msyh.ttc", 12)
        except (OSError, IOError):
            try:
                font_title = ImageFont.truetype("simhei.ttf", 32)
                font_sub = ImageFont.truetype("simhei.ttf", 18)
                font_small = ImageFont.truetype("simhei.ttf", 14)
                font_tip = ImageFont.truetype("simhei.ttf", 12)
            except (OSError, IOError):
                font_title = ImageFont.load_default()
                font_sub = font_title
                font_small = font_title
                font_tip = font_title

        # 标题
        title_text = f"{region} 灾情上报"
        bbox = draw.textbbox((0, 0), title_text, font=font_title)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) / 2, 30), title_text, fill='#ffffff', font=font_title)

        sub_text = "扫码上报灾情 · 助力应急指挥"
        bbox2 = draw.textbbox((0, 0), sub_text, font=font_sub)
        tw2 = bbox2[2] - bbox2[0]
        draw.text(((W - tw2) / 2, 78), sub_text, fill='#e0f7fa', font=font_sub)

        # 生成二维码
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=2,
        )
        qr.add_data(report_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#263238", back_color="white")
        qr_size = 320
        qr_img = qr_img.resize((qr_size, qr_size))

        # 二维码居中放置
        qr_x = (W - qr_size) // 2
        qr_y = 160
        # 画白底边框
        draw.rectangle([qr_x - 15, qr_y - 15, qr_x + qr_size + 15, qr_y + qr_size + 15],
                        fill='#ffffff', outline='#e0e0e0', width=2)
        poster.paste(qr_img, (qr_x, qr_y))

        # 底部说明
        bot_y = qr_y + qr_size + 40
        main_text = "微信扫一扫 · 快速上报灾情"
        bbox3 = draw.textbbox((0, 0), main_text, font=font_sub)
        tw3 = bbox3[2] - bbox3[0]
        draw.text(((W - tw3) / 2, bot_y), main_text, fill='#263238', font=font_sub)

        desc_text = "拍照/视频 + 自动定位 + 实时上报"
        bbox4 = draw.textbbox((0, 0), desc_text, font=font_small)
        tw4 = bbox4[2] - bbox4[0]
        draw.text(((W - tw4) / 2, bot_y + 32), desc_text, fill='#78909c', font=font_small)

        if org:
            bbox5 = draw.textbbox((0, 0), org, font=font_small)
            tw5 = bbox5[2] - bbox5[0]
            draw.text(((W - tw5) / 2, bot_y + 62), org, fill='#0277bd', font=font_small)

        # 底部安全提示
        tip_text = "紧急险情请拨打 119 / 110"
        bbox6 = draw.textbbox((0, 0), tip_text, font=font_tip)
        tw6 = bbox6[2] - bbox6[0]
        draw.text(((W - tw6) / 2, H - 30), tip_text, fill='#b0bec5', font=font_tip)

        buf = BytesIO()
        poster.save(buf, format='PNG', quality=95)
        buf.seek(0)

        resp = make_response(buf.read())
        resp.headers['Content-Type'] = 'image/png'
        resp.headers['Content-Disposition'] = f'inline; filename=report_poster_{region}.png'
        return resp
    except ImportError:
        return jsonify({"error": "服务端未安装所需库，请执行 pip install qrcode[pil]"}), 500
    except Exception as e:
        return jsonify({"error": f"海报生成失败: {str(e)}"}), 500
