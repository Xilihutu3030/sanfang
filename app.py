# -*- coding: utf-8 -*-
"""
三防形势智能研判与指挥辅助系统 - 统一后端服务
整合：气象爬虫 + 地形分析 + 智能研判 + 前端服务
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime

# Windows GBK控制台无法输出emoji，强制UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from flask import Flask, jsonify, request, send_from_directory, g
from flask_cors import CORS

# 加载 .env 配置
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass

from crawler import crawl_all_weather, TARGET_AREA
from terrain import get_elevation, analyze_terrain_risk, get_area_elevation_stats, generate_dem_grid
from ai_judge import ai_comprehensive_judge, ai_comprehensive_judge_v2, generate_report
from tide import get_full_marine_report, get_marine_data, predict_tide
from weather_api import get_realtime_weather
from resources_handler import (
    RESOURCE_TYPES, list_resources, get_resource, add_resource,
    update_resource, delete_resource, import_from_excel, import_from_csv,
    generate_template, get_all_statistics,
)
from auth import init_db, register_auth_routes, auth_required, optional_auth, premium_required, get_db
from premium_features import premium, init_premium_tables, check_alert_rules
from yuezhengyi import yzy

app = Flask(__name__, static_folder=None)
CORS(app)

# 全局500错误捕获（调试用）
@app.errorhandler(500)
def handle_500(e):
    import traceback
    err_msg = traceback.format_exc()
    with open('error_log.txt', 'a', encoding='utf-8') as f:
        f.write('\n--- %s ---\n%s\n' % (datetime.now(), err_msg))
    return jsonify({"error": str(e), "trace": err_msg}), 500

# 初始化数据库和认证路由
init_db()
init_premium_tables()
register_auth_routes(app)
app.register_blueprint(premium)
app.register_blueprint(yzy)

# ==================== 全局数据缓存 ====================
weather_cache = {
    "update_time": None,
    "data": None
}

# 默认风险点数据（可后续对接数据库）
DEFAULT_HAZARDS = [
    {"name": "岗贝隧道", "type": "隧道", "level": "重大", "历史淹水": True,
     "elevation": 18, "location": "白云区岗贝路", "lat": 23.1810, "lng": 113.2420},
    {"name": "广园立交桥底", "type": "桥下", "level": "重大", "历史淹水": True,
     "elevation": 22, "location": "越秀区广园路", "lat": 23.1450, "lng": 113.2780},
    {"name": "暨南花园地下车库", "type": "地下空间", "level": "重大",
     "elevation": 25, "location": "天河区黄埔大道", "lat": 23.1280, "lng": 113.3520},
    {"name": "沙河涌棠下段", "type": "河道", "level": "一般",
     "elevation": 12, "location": "天河区棠下", "lat": 23.1350, "lng": 113.3650},
    {"name": "石牌东路低洼区", "type": "易涝点", "level": "一般", "历史淹水": True,
     "elevation": 28, "location": "天河区石牌东", "lat": 23.1320, "lng": 113.3410},
    {"name": "火车站下穿通道", "type": "隧道", "level": "重大", "历史淹水": True,
     "elevation": 15, "location": "越秀区环市西路", "lat": 23.1480, "lng": 113.2560},
    {"name": "猎德涌珠江汇入口", "type": "河道", "level": "一般",
     "elevation": 8, "location": "天河区猎德", "lat": 23.1100, "lng": 113.3280},
    {"name": "大沙头旧楼群", "type": "危房", "level": "重大",
     "elevation": 30, "location": "越秀区大沙头路", "lat": 23.1200, "lng": 113.2800},
]


# ==================== 前端页面 ====================
@app.route('/')
def landing():
    return send_from_directory('.', 'landing.html')

@app.route('/system')
def index():
    resp = send_from_directory('.', 'index.html')
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers.pop('ETag', None)
    return resp

@app.route('/favicon.png')
def favicon():
    return send_from_directory('.', 'favicon.png')

@app.route('/favicon.ico')
def favicon_ico():
    return send_from_directory('.', 'icon.ico')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/login')
def login_page():
    return send_from_directory('.', 'login.html')


# ==================== 气象数据 API ====================
@app.route('/api/weather', methods=['GET'])
def get_weather():
    """获取最新气象数据（优先实时API，兼容旧爬虫数据）"""
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    # 有坐标参数 -> 调用全球实时API
    if lat is not None and lng is not None:
        data = get_realtime_weather(lat, lng)
        weather_cache["data"] = data
        weather_cache["update_time"] = datetime.now().isoformat()
        return jsonify(data)

    # 无坐标 -> 使用缓存
    if weather_cache["data"]:
        return jsonify(weather_cache["data"])

    # 都没有 -> 默认广州实时数据
    data = get_realtime_weather(23.13, 113.27)
    weather_cache["data"] = data
    return jsonify(data)


@app.route('/api/weather/refresh', methods=['POST'])
def refresh_weather():
    """刷新气象数据"""
    data = request.json or {}
    lat = data.get('lat', 23.13)
    lng = data.get('lng', 113.27)

    result = get_realtime_weather(lat, lng)
    weather_cache["data"] = result
    weather_cache["update_time"] = datetime.now().isoformat()
    return jsonify(result)


def _get_weather_fallback():
    """气象数据兜底（模拟数据）"""
    return {
        "update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "target_area": TARGET_AREA,
        "综合研判": {
            "预警等级": "暴雨蓝色预警",
            "当前雨量_1h": 2.5,
            "累计雨量_24h": 35.0,
            "未来1h预报": "中雨",
            "未来6h预报": "大雨",
            "未来24h预报": "暴雨",
            "雷达回波": "降雨回波逼近",
            "风险建议": "建议启动防御响应"
        },
        "sources": [
            {"source": "中央气象台", "status": "fallback"},
            {"source": "广东省气象局", "status": "fallback"},
            {"source": "广州市气象局", "status": "fallback"},
            {"source": "和风天气", "status": "fallback"},
            {"source": "彩云天气", "status": "fallback"},
        ]
    }


# ==================== 地形分析 API ====================
@app.route('/api/terrain/elevation', methods=['GET'])
def api_get_elevation():
    """获取单点高程"""
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None:
        return jsonify({"error": "缺少 lat/lng 参数"}), 400

    elev = get_elevation(lat, lng)
    return jsonify({"lat": lat, "lng": lng, "elevation": elev})


@app.route('/api/terrain/risk', methods=['POST'])
def api_terrain_risk():
    """单点地形风险分析"""
    data = request.json
    if not data or 'lat' not in data or 'lng' not in data:
        return jsonify({"error": "缺少坐标参数"}), 400

    result = analyze_terrain_risk(
        data['lat'], data['lng'],
        data.get('rain_24h', 50),
        data.get('is_river_side', False),
        data.get('is_tunnel', False),
        data.get('is_underground', False)
    )
    return jsonify(result)


@app.route('/api/terrain/area', methods=['POST'])
def api_area_elevation():
    """区域高程统计"""
    data = request.json
    if not data or 'coordinates' not in data:
        return jsonify({"error": "缺少坐标列表"}), 400

    coords = [(c['lat'], c['lng']) for c in data['coordinates']]
    result = get_area_elevation_stats(coords)
    return jsonify(result)


@app.route('/api/terrain/dem-grid', methods=['POST'])
def api_dem_grid():
    """获取DEM高程网格数据（用于前端地形可视化）"""
    data = request.json or {}
    bounds = data.get('bounds', {})
    grid_size = min(data.get('grid_size', 10), 15)
    sw_lat = bounds.get('sw_lat', 23.08)
    sw_lng = bounds.get('sw_lng', 113.20)
    ne_lat = bounds.get('ne_lat', 23.18)
    ne_lng = bounds.get('ne_lng', 113.32)
    result = generate_dem_grid(sw_lat, sw_lng, ne_lat, ne_lng, grid_size)
    return jsonify(result)


# ==================== 潮汐/海洋数据 API ====================
@app.route('/api/tide', methods=['GET'])
def api_tide():
    """获取完整潮汐+海洋数据"""
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None:
        return jsonify({"error": "缺少 lat/lng 参数"}), 400
    result = get_full_marine_report(lat, lng)
    return jsonify(result)


@app.route('/api/tide/marine', methods=['GET'])
def api_marine():
    """仅获取海洋气象数据（波浪/涌浪）"""
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None:
        return jsonify({"error": "缺少 lat/lng 参数"}), 400
    return jsonify(get_marine_data(lat, lng))


@app.route('/api/tide/predict', methods=['GET'])
def api_tide_predict():
    """仅获取天文潮汐预测"""
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)
    if lat is None or lng is None:
        return jsonify({"error": "缺少 lat/lng 参数"}), 400
    return jsonify(predict_tide(lat, lng))


# ==================== 智能研判 API ====================
@app.route('/api/ai/judge', methods=['POST'])
def api_ai_judge():
    """
    智能研判 - 基于真实数据动态生成
    前端传入真实气象、坐标、圈选区域、风险点数据
    """
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    # 1. 获取气象数据
    weather = _build_weather_input(data.get('weather'))

    # 2. 获取中心坐标
    center = data.get('center', {'lat': 23.13, 'lng': 113.27})

    # 3. 获取风险点 - 优先用前端传入的真实数据
    hazards = data.get('hazards')
    if not hazards or len(hazards) == 0:
        hazards = []  # 没有真实风险点数据就传空，不用默认点凑数

    # 4. 根据圈选区域过滤风险点（只保留圈选范围内的点）
    area = data.get('area')
    if area and area.get('type'):
        # 有圈选区域时，用DEFAULT_HAZARDS中落在范围内的点补充
        if not hazards:
            hazards = DEFAULT_HAZARDS
        filtered = _filter_hazards_by_area(hazards, area)
        hazards = filtered  # 即使为空也用空，不在范围内就是不在

    # 5. 获取/构建地形数据
    terrain = data.get('terrain')
    if not terrain:
        terrain = _terrain_from_hazards(hazards, center)
    else:
        terrain = _build_terrain_input(terrain, center)

    if area:
        terrain['圈选区域'] = area

    # 6. 执行智能研判（默认纯规则模式，秒级响应；前端可传mode='hybrid'启用LLM增强）
    mode = data.get('mode', os.getenv("LLM_MODE", "rule"))
    if mode in ('llm', 'hybrid'):
        try:
            import signal, threading
            # 限时15秒，超时降级为规则引擎
            result_container = [None]
            exc_container = [None]
            def _run_v2():
                try:
                    result_container[0] = ai_comprehensive_judge_v2(weather, terrain, hazards, mode=mode)
                except Exception as e:
                    exc_container[0] = e
            t = threading.Thread(target=_run_v2)
            t.start()
            t.join(timeout=15)
            if t.is_alive() or result_container[0] is None:
                print("[智能研判] LLM超时或失败，降级为规则引擎")
                result = ai_comprehensive_judge(weather, terrain, hazards)
                result["_fallback"] = True
                result["_fallback_reason"] = str(exc_container[0]) if exc_container[0] else "LLM调用超时(15s)"
            else:
                result = result_container[0]
        except Exception as e:
            print(f"[智能研判] 异常: {e}，降级为规则引擎")
            result = ai_comprehensive_judge(weather, terrain, hazards)
    else:
        result = ai_comprehensive_judge(weather, terrain, hazards)

    # 7. 生成简报
    report_text = generate_report(result)
    result["简报文本"] = report_text

    # 8. 有风险时匹配附近可调度资源
    risk_level = result.get("1_综合风险等级", {}).get("等级", "")
    if risk_level != "暂无风险":
        try:
            resources = _match_nearby_resources(center, area)
            if resources:
                result["7_可调度资源"] = resources
        except Exception as e:
            print(f"[资源匹配] 异常: {e}")

    return jsonify(result)


@app.route('/api/ai/report', methods=['POST'])
def api_generate_report():
    """根据研判结果生成简报"""
    data = request.json
    if not data:
        return jsonify({"error": "缺少研判数据"}), 400

    report = generate_report(data)
    return jsonify({"report": report})


# ==================== AI 智能对话 API ====================
# 对话会话管理（内存存储，最多100个会话，每个最多10轮，30分钟过期）
chat_sessions = {}
CHAT_SESSION_MAX = 100
CHAT_HISTORY_MAX = 10
CHAT_SESSION_EXPIRE = 30 * 60  # 30分钟


def _cleanup_sessions():
    """清理过期会话"""
    now = time.time()
    expired = [sid for sid, s in chat_sessions.items()
               if now - s.get("last_time", 0) > CHAT_SESSION_EXPIRE]
    for sid in expired:
        del chat_sessions[sid]
    # 超出上限时清理最旧的
    if len(chat_sessions) > CHAT_SESSION_MAX:
        sorted_sessions = sorted(chat_sessions.items(), key=lambda x: x[1].get("last_time", 0))
        for sid, _ in sorted_sessions[:len(chat_sessions) - CHAT_SESSION_MAX]:
            del chat_sessions[sid]


@app.route('/api/ai/chat', methods=['POST'])
def api_ai_chat():
    """
    AI智能对话
    POST body:
        message: 用户消息
        context: 研判结果摘要（首次对话时传入）
        session_id: 会话ID（可选，不传则新建）
    """
    llm_enabled = os.getenv("ENABLE_LLM", "false").lower() == "true"
    if not llm_enabled:
        return jsonify({"error": "大模型未启用，请在 .env 中设置 ENABLE_LLM=true"}), 400

    data = request.json or {}
    message = data.get('message', '').strip()
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    session_id = data.get('session_id', '')
    context = data.get('context')

    # 清理过期会话
    _cleanup_sessions()

    # 获取或创建会话
    if session_id and session_id in chat_sessions:
        session = chat_sessions[session_id]
    else:
        session_id = str(uuid.uuid4())[:8]
        session = {
            "history": [],
            "context": context,
            "create_time": time.time(),
            "last_time": time.time(),
        }
        chat_sessions[session_id] = session

    # 如果传了新的 context，更新
    if context:
        session["context"] = context

    try:
        from qwen_client import QwenClient
        client = QwenClient()
        reply = client.chat(
            message=message,
            context=session.get("context"),
            history=session["history"],
        )
    except Exception as e:
        print(f"[AI对话] 异常: {e}")
        return jsonify({
            "error": "AI助手暂时无法响应",
            "detail": str(e),
            "session_id": session_id,
        }), 500

    # 记录历史
    session["history"].append({"role": "user", "content": message})
    session["history"].append({"role": "assistant", "content": reply})
    session["last_time"] = time.time()

    # 限制历史轮数（每轮=user+assistant，保留最近N轮）
    max_entries = CHAT_HISTORY_MAX * 2
    if len(session["history"]) > max_entries:
        session["history"] = session["history"][-max_entries:]

    return jsonify({
        "reply": reply,
        "session_id": session_id,
    })


def _build_weather_input(weather_override=None):
    """构建气象输入数据"""
    if weather_override:
        return weather_override

    # 从缓存获取（现在缓存里是实时API数据）
    weather_raw = weather_cache.get("data")
    if not weather_raw:
        try:
            with open("weather_data.json", 'r', encoding='utf-8') as f:
                weather_raw = json.load(f)
        except FileNotFoundError:
            pass

    if weather_raw and "综合研判" in weather_raw:
        info = weather_raw["综合研判"]
        return {
            "rain_24h": info.get("累计雨量_24h", 0),
            "rain_1h": info.get("当前雨量_1h", 0),
            "warning_level": info.get("warning_level", _parse_warning_level(info.get("预警等级", ""))),
            "forecast": info.get("未来6h预报", "--"),
            "forecast_rain_6h": info.get("未来6h预报降雨", 0),
            "forecast_rain_24h": info.get("未来24h预报降雨", 0),
        }

    # 兜底默认：无雨无预警
    return {"rain_24h": 0, "warning_level": 0, "forecast": "--"}


def _match_nearby_resources(center, area=None):
    """匹配附近可调度的应急资源，返回按类型分组的结果"""
    import math
    clat = center.get('lat', 23.13)
    clng = center.get('lng', 113.27)
    result = {}

    # --- 场所设施（有坐标，算距离）---
    try:
        fac_data = list_resources('facilities')
        fac_items = fac_data.get('items', [])
        nearby_fac = []
        for f in fac_items:
            flat = f.get('lat', 0)
            flng = f.get('lng', 0)
            status = f.get('status', '')
            if status in ('停用', '维修中'):
                continue
            item = {
                'name': f.get('name', ''),
                'type': f.get('type', ''),
                'capacity': f.get('capacity', ''),
                'address': f.get('address', ''),
                'phone': f.get('phone', ''),
                'status': status or '可用',
            }
            if flat and flng:
                dlat = (flat - clat) * 111000
                dlng = (flng - clng) * 111000 * math.cos(math.radians(clat))
                dist = math.sqrt(dlat**2 + dlng**2) / 1000
                if dist <= 10:
                    item['distance_km'] = round(dist, 1)
                    nearby_fac.append(item)
            else:
                item['distance_km'] = None
                nearby_fac.append(item)
        nearby_fac.sort(key=lambda x: x['distance_km'] if x['distance_km'] is not None else 999)
        if nearby_fac:
            result['facilities'] = {'label': '场所设施', 'items': nearby_fac[:8]}
    except Exception as e:
        print(f"[资源匹配] facilities异常: {e}")

    # --- 人员队伍（无坐标，按状态过滤）---
    try:
        per_data = list_resources('personnel')
        per_items = per_data.get('items', [])
        avail = []
        for p in per_items:
            st = p.get('status', '')
            if st in ('休假', '离职', ''):
                continue
            avail.append({
                'name': p.get('name', ''),
                'team': p.get('team', ''),
                'phone': p.get('phone', ''),
                'status': st,
                'location': p.get('location', ''),
            })
        if avail:
            result['personnel'] = {'label': '人员队伍', 'items': avail[:10]}
    except Exception as e:
        print(f"[资源匹配] personnel异常: {e}")

    # --- 物资装备（无坐标，按状态过滤）---
    try:
        mat_data = list_resources('materials')
        mat_items = mat_data.get('items', [])
        avail = []
        for m in mat_items:
            st = m.get('status', '')
            qty = m.get('quantity', 0)
            if st in ('报废', '维修中') or (isinstance(qty, (int, float)) and qty <= 0):
                continue
            avail.append({
                'name': m.get('name', ''),
                'category': m.get('category', ''),
                'quantity': qty,
                'unit': m.get('unit', ''),
                'location': m.get('location', ''),
            })
        if avail:
            result['materials'] = {'label': '物资装备', 'items': avail[:10]}
    except Exception as e:
        print(f"[资源匹配] materials异常: {e}")

    # --- 车辆运力（无坐标，按状态过滤）---
    try:
        veh_data = list_resources('vehicles')
        veh_items = veh_data.get('items', [])
        avail = []
        for v in veh_items:
            st = v.get('status', '')
            if st in ('维修', '报废', '出勤中'):
                continue
            avail.append({
                'plate_number': v.get('plate_number', ''),
                'type': v.get('type', ''),
                'driver': v.get('driver', ''),
                'driver_phone': v.get('driver_phone', ''),
                'status': st or '可用',
            })
        if avail:
            result['vehicles'] = {'label': '车辆运力', 'items': avail[:10]}
    except Exception as e:
        print(f"[资源匹配] vehicles异常: {e}")

    return result if result else None


def _filter_hazards_by_area(hazards, area):
    """根据圈选区域过滤风险点，只保留范围内的"""
    area_type = area.get('type')
    result = []

    for h in hazards:
        hlat = h.get('lat', 0)
        hlng = h.get('lng', 0)
        if not hlat or not hlng:
            continue

        inside = False
        if area_type == 'rectangle':
            inside = (area.get('swLat', 0) <= hlat <= area.get('neLat', 0) and
                      area.get('swLng', 0) <= hlng <= area.get('neLng', 0))
        elif area_type == 'circle':
            clat = area.get('centerLat', 0)
            clng = area.get('centerLng', 0)
            radius = area.get('radius', 0)  # 米
            import math
            dlat = (hlat - clat) * 111000
            dlng = (hlng - clng) * 111000 * math.cos(math.radians(clat))
            dist = math.sqrt(dlat**2 + dlng**2)
            inside = dist <= radius
        elif area_type == 'polygon':
            pts = area.get('points', [])
            inside = _point_in_polygon(hlat, hlng, pts)

        if inside:
            result.append(h)

    return result


def _point_in_polygon(lat, lng, polygon_points):
    """射线法判断点是否在多边形内"""
    n = len(polygon_points)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        pi = polygon_points[i]
        pj = polygon_points[j]
        yi, xi = pi.get('lat', 0), pi.get('lng', 0)
        yj, xj = pj.get('lat', 0), pj.get('lng', 0)
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _terrain_from_hazards(hazards, center=None):
    """从风险点的高程数据直接推算地形参数，避免调用慢速外部API"""
    elevations = [h.get("elevation", 35) for h in hazards if h.get("elevation")]
    if not elevations:
        elevations = [35]
    min_elev = min(elevations)
    avg_elev = sum(elevations) / len(elevations)
    low_count = len([e for e in elevations if e < 50])
    return {
        "最低高程": min_elev,
        "平均高程": round(avg_elev, 1),
        "低洼易涝点": low_count,
        "可能淹没面积": f"{max(0.1, (50 - min_elev) * 0.05):.1f}km2" if min_elev < 50 else "0.1km2",
        "最大积水深度": f"{max(0.1, (50 - min_elev) * 0.03):.1f}-{max(0.3, (50 - min_elev) * 0.05):.1f}米" if min_elev < 50 else "0.1-0.3米",
        "是否沿河": min_elev < 40 or any("河道" in h.get("type", "") for h in hazards),
    }


def _build_terrain_input(terrain_override=None, center=None):
    """构建地形输入数据 - 使用真实高程"""
    if terrain_override:
        return terrain_override

    if center:
        lat = center.get('lat', 23.13)
        lng = center.get('lng', 113.27)
    else:
        lat, lng = 23.13, 113.27

    try:
        elev_center = get_elevation(lat, lng)
        stats = get_area_elevation_stats([
            (lat - 0.02, lng - 0.02), (lat + 0.02, lng - 0.02),
            (lat + 0.02, lng + 0.02), (lat - 0.02, lng + 0.02),
        ])
        min_elev = stats.get("最低高程", elev_center)
        avg_elev = stats.get("平均高程", elev_center)
        low_count = stats.get("低洼点数量", 0) if "低洼点数量" in stats else (3 if min_elev < 50 else 0)

        return {
            "最低高程": min_elev,
            "平均高程": avg_elev,
            "低洼易涝点": low_count,
            "可能淹没面积": f"{max(0.1, (50 - min_elev) * 0.05):.1f}km2" if min_elev < 50 else "0.1km2",
            "最大积水深度": f"{max(0.1, (50 - min_elev) * 0.03):.1f}-{max(0.3, (50 - min_elev) * 0.05):.1f}米" if min_elev < 50 else "0.1-0.3米",
            "是否沿河": min_elev < 40,
        }
    except Exception as e:
        print(f"[WARN] terrain input build failed: {e}")

    return {
        "最低高程": 28,
        "平均高程": 45,
        "低洼易涝点": 3,
        "可能淹没面积": "0.8km2",
        "最大积水深度": "0.5-1.2米",
        "是否沿河": True
    }


def _parse_warning_level(text):
    """解析预警等级文本为数字"""
    if "红色" in text:
        return 4
    elif "橙色" in text:
        return 3
    elif "黄色" in text:
        return 2
    elif "蓝色" in text:
        return 1
    return 0


def _generate_local_hazards(lat, lng, terrain):
    """
    根据坐标和地形数据动态生成当地风险点
    用Nominatim反向地理编码获取真实地名
    """
    import math, hashlib

    min_elev = terrain.get("最低高程", 40)
    avg_elev = terrain.get("平均高程", 50)

    templates = [
        {"type": "隧道", "suffix": "下穿隧道", "base_elev_offset": -8, "level": "重大", "历史淹水": True},
        {"type": "桥下", "suffix": "桥底通道", "base_elev_offset": -5, "level": "重大", "历史淹水": True},
        {"type": "地下空间", "suffix": "地下停车场", "base_elev_offset": -3, "level": "重大", "历史淹水": False},
        {"type": "河道", "suffix": "河段", "base_elev_offset": -12, "level": "一般", "历史淹水": False},
        {"type": "易涝点", "suffix": "低洼路段", "base_elev_offset": -2, "level": "一般", "历史淹水": True},
        {"type": "隧道", "suffix": "下穿通道", "base_elev_offset": -10, "level": "重大", "历史淹水": True},
        {"type": "河道", "suffix": "涌汇入口", "base_elev_offset": -15, "level": "一般", "历史淹水": False},
        {"type": "危房", "suffix": "旧楼群", "base_elev_offset": 2, "level": "重大", "历史淹水": False},
    ]

    seed = hashlib.md5(f"{lat:.4f},{lng:.4f}".encode()).hexdigest()
    directions = [
        ("东北", 0.008, 0.010), ("东南", -0.006, 0.012),
        ("西北", 0.010, -0.008), ("南", -0.012, 0.002),
        ("东", 0.003, 0.015), ("西南", -0.009, -0.007),
        ("北", 0.014, -0.003), ("西", 0.001, -0.013),
    ]

    nearby_names = _get_nearby_place_names(lat, lng)

    # 如果地理编码全部失败，直接使用DEFAULT_HAZARDS（已有真实广州地名）
    valid_names = [n for n in nearby_names if n]
    if len(valid_names) == 0:
        print("[风险点生成] Nominatim全部失败，使用默认广州风险点数据")
        return DEFAULT_HAZARDS

    hazards = []

    for i, (tmpl, (direction, dlat, dlng)) in enumerate(zip(templates, directions)):
        h_lat = lat + dlat
        h_lng = lng + dlng
        h_elev = max(1, avg_elev + tmpl["base_elev_offset"] + int(seed[i*2:i*2+2], 16) % 10 - 5)

        if i < len(nearby_names) and nearby_names[i]:
            name = nearby_names[i] + tmpl["suffix"]
            location = nearby_names[i] + "附近"
        else:
            # 部分失败时，用DEFAULT_HAZARDS中同类型的点补充
            fallback = next((h for h in DEFAULT_HAZARDS if h["type"] == tmpl["type"] and h["name"] not in [x["name"] for x in hazards]), None)
            if fallback:
                hazards.append(dict(fallback))
                continue
            name = f"{direction}方向{tmpl['suffix']}"
            location = f"中心点{direction}约{math.sqrt(dlat**2+dlng**2)*111:.1f}km处"

        hazards.append({
            "name": name,
            "type": tmpl["type"],
            "level": tmpl["level"],
            "历史淹水": tmpl["历史淹水"],
            "elevation": h_elev,
            "location": location,
            "lat": round(h_lat, 6),
            "lng": round(h_lng, 6),
        })

    return hazards


def _get_nearby_place_names(lat, lng):
    """通过Nominatim反向地理编码获取附近地名"""
    names = []
    offsets = [
        (0.008, 0.010), (-0.006, 0.012), (0.010, -0.008), (-0.012, 0.002),
        (0.003, 0.015), (-0.009, -0.007), (0.014, -0.003), (0.001, -0.013),
    ]
    try:
        import requests
        for dlat, dlng in offsets[:4]:
            try:
                resp = requests.get(
                    f"https://nominatim.openstreetmap.org/reverse?lat={lat+dlat}&lon={lng+dlng}&format=json&zoom=16&accept-language=zh",
                    headers={"User-Agent": "SanfangSystem/1.0"},
                    timeout=3
                )
                if resp.status_code == 200:
                    data = resp.json()
                    addr = data.get("address", {})
                    name = addr.get("road") or addr.get("neighbourhood") or addr.get("suburb") or addr.get("quarter") or ""
                    names.append(name if name and len(name) <= 12 else "")
                else:
                    names.append("")
            except Exception:
                names.append("")
    except Exception as e:
        print(f"[地名查询] 失败: {e}")
    while len(names) < 8:
        names.append("")
    return names


# ==================== 风险点 API ====================
@app.route('/api/hazards', methods=['GET'])
@optional_auth
def get_hazards():
    """获取风险点列表，支持按区域bounds过滤"""
    try:
        hazards = DEFAULT_HAZARDS
        if g.user_id:
            db = get_db()
            rows = db.execute(
                "SELECT * FROM hazards ORDER BY created_at DESC"
            ).fetchall()
            db.close()
            if rows:
                hazards = [dict(r) for r in rows]

        # 按区域bounds过滤
        sw_lat = request.args.get('sw_lat', type=float)
        sw_lng = request.args.get('sw_lng', type=float)
        ne_lat = request.args.get('ne_lat', type=float)
        ne_lng = request.args.get('ne_lng', type=float)
        if sw_lat is not None and ne_lat is not None:
            hazards = [h for h in hazards
                       if h.get('lat') and h.get('lng')
                       and sw_lat <= h['lat'] <= ne_lat
                       and sw_lng <= h['lng'] <= ne_lng]

        type_count = {}
        for h in hazards:
            t = h.get("type", "")
            type_count[t] = type_count.get(t, 0) + 1

        return jsonify({
            "hazards": hazards,
            "统计": {
                "易涝点": type_count.get("易涝点", 0) + type_count.get("桥下", 0),
                "危房": type_count.get("危房", 0),
                "地下空间": type_count.get("地下空间", 0),
                "河道": type_count.get("河道", 0),
                "隧道": type_count.get("隧道", 0),
                "总计": len(hazards)
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "hazards": DEFAULT_HAZARDS, "统计": {"总计": len(DEFAULT_HAZARDS)}}), 200


# ==================== 历史记录 API ====================
HISTORY_FILE = "judge_history.json"


@app.route('/api/history', methods=['GET'])
@optional_auth
def get_history():
    """获取研判历史"""
    if g.user_id:
        db = get_db()
        rows = db.execute(
            "SELECT * FROM judge_history WHERE user_id=? ORDER BY save_time DESC LIMIT 50",
            (g.user_id,)
        ).fetchall()
        db.close()
        return jsonify([{**dict(r), "result": json.loads(r["result"])} for r in rows])

    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
        return jsonify(history)
    except FileNotFoundError:
        return jsonify([])


@app.route('/api/history', methods=['POST'])
@optional_auth
def save_history():
    """保存研判记录"""
    data = request.json
    if not data:
        return jsonify({"error": "无数据"}), 400

    if g.user_id:
        db = get_db()
        record_id = str(uuid.uuid4())[:8]
        db.execute(
            "INSERT INTO judge_history (id, user_id, result) VALUES (?, ?, ?)",
            (record_id, g.user_id, json.dumps(data, ensure_ascii=False))
        )
        db.commit()
        count = db.execute("SELECT COUNT(*) as c FROM judge_history WHERE user_id=?", (g.user_id,)).fetchone()['c']
        db.close()
        return jsonify({"message": "保存成功", "total": count})

    # 未登录 -> 兼容旧文件存储
    history = []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except FileNotFoundError:
        pass

    data["save_time"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    history.insert(0, data)
    history = history[:50]

    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    return jsonify({"message": "保存成功", "total": len(history)})


# ==================== 应急资源管理 API ====================

def _validate_resource_type(rtype):
    if rtype not in RESOURCE_TYPES:
        return False
    return True


@app.route('/api/resources/statistics', methods=['GET'])
def api_resources_statistics():
    """资源总览统计"""
    return jsonify(get_all_statistics())


@app.route('/api/resources/<rtype>', methods=['GET'])
def api_list_resources(rtype):
    """获取某类资源列表"""
    if not _validate_resource_type(rtype):
        return jsonify({"error": f"无效资源类型: {rtype}"}), 400
    return jsonify(list_resources(rtype))


@app.route('/api/resources/<rtype>', methods=['POST'])
def api_add_resource(rtype):
    """手动添加单个资源"""
    if not _validate_resource_type(rtype):
        return jsonify({"error": f"无效资源类型: {rtype}"}), 400
    data = request.json
    if not data:
        return jsonify({"error": "缺少数据"}), 400
    try:
        item = add_resource(rtype, data)
        return jsonify({"message": "添加成功", "item": item})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/resources/<rtype>/<resource_id>', methods=['PUT'])
def api_update_resource(rtype, resource_id):
    """更新资源"""
    if not _validate_resource_type(rtype):
        return jsonify({"error": f"无效资源类型: {rtype}"}), 400
    data = request.json
    if not data:
        return jsonify({"error": "缺少数据"}), 400
    item = update_resource(rtype, resource_id, data)
    if item:
        return jsonify({"message": "更新成功", "item": item})
    return jsonify({"error": "资源不存在"}), 404


@app.route('/api/resources/<rtype>/<resource_id>', methods=['DELETE'])
def api_delete_resource(rtype, resource_id):
    """删除资源"""
    if not _validate_resource_type(rtype):
        return jsonify({"error": f"无效资源类型: {rtype}"}), 400
    if delete_resource(rtype, resource_id):
        return jsonify({"message": "删除成功"})
    return jsonify({"error": "资源不存在"}), 404


@app.route('/api/resources/import/<rtype>', methods=['POST'])
def api_import_resources(rtype):
    """Excel/CSV批量导入资源"""
    if not _validate_resource_type(rtype):
        return jsonify({"error": f"无效资源类型: {rtype}"}), 400

    if 'file' not in request.files:
        return jsonify({"error": "未上传文件"}), 400

    file = request.files['file']
    filename = file.filename.lower() if file.filename else ""

    try:
        if filename.endswith(('.xlsx', '.xls')):
            result = import_from_excel(rtype, file)
        elif filename.endswith('.csv'):
            result = import_from_csv(rtype, file)
        else:
            return jsonify({"error": "仅支持 .xlsx / .xls / .csv 格式"}), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"导入失败: {str(e)}"}), 500


@app.route('/api/resources/template/<rtype>', methods=['GET'])
def api_download_template(rtype):
    """下载Excel导入模板"""
    if not _validate_resource_type(rtype):
        return jsonify({"error": f"无效资源类型: {rtype}"}), 400
    from flask import make_response
    data = generate_template(rtype)
    resp = make_response(data)
    resp.headers['Content-Type'] = 'application/octet-stream'
    resp.headers['Content-Disposition'] = f'attachment; filename={rtype}_template.xlsx'
    resp.headers['Content-Length'] = len(data)
    return resp


# ==================== 启动 ====================
if __name__ == '__main__':
    print("""
    ╔═══════════════════════════════════════════════╗
    ║  三防形势智能研判与指挥辅助系统               ║
    ║  统一后端服务 v2.0 (小程序版)                 ║
    ╚═══════════════════════════════════════════════╝
    """)
    print("  API 接口列表:")
    print("  ─────────────────────────────────────────")
    print("  GET  /                      前端页面")
    print("  GET  /login                 登录页面")
    print("  POST /api/auth/login        用户登录")
    print("  GET  /api/auth/me           当前用户信息")
    print("  POST /api/auth/password     修改密码")
    print("  GET  /api/weather           获取气象数据")
    print("  POST /api/weather/refresh   刷新气象数据")
    print("  GET  /api/terrain/elevation 单点高程查询")
    print("  POST /api/terrain/risk      单点风险分析")
    print("  POST /api/terrain/area      区域高程统计")
    print("  POST /api/ai/judge          AI综合研判")
    print("  POST /api/ai/report         生成研判简报")
    print("  POST /api/ai/chat           AI智能对话")
    print("  GET  /api/hazards           风险点列表")
    print("  GET  /api/history           研判历史")
    print("  POST /api/history           保存研判记录")
    print()
    print("  [应急资源管理]")
    print("  GET  /api/resources/statistics        资源总览")
    print("  GET  /api/resources/<type>            资源列表")
    print("  POST /api/resources/<type>            添加资源")
    print("  PUT  /api/resources/<type>/<id>       更新资源")
    print("  DEL  /api/resources/<type>/<id>       删除资源")
    print("  POST /api/resources/import/<type>     批量导入")
    print("  GET  /api/resources/template/<type>   下载模板")
    print()
    print("  [管理接口 - 需要登录]")
    print("  GET  /api/admin/users                 用户列表(admin)")
    print("  POST /api/admin/users                 创建用户(admin)")
    print("  ─────────────────────────────────────────")
    print()

    # 启动时先获取一次气象数据
    print("  正在获取初始气象数据...")
    try:
        weather_cache["data"] = crawl_all_weather(TARGET_AREA)
        weather_cache["update_time"] = datetime.now().isoformat()
        print("  气象数据就绪")
    except Exception as e:
        print(f"  气象爬取失败，使用模拟数据: {e}")
        weather_cache["data"] = _get_weather_fallback()

    print()
    print("  服务启动: http://localhost:5000")
    print("  浏览器访问上述地址即可使用系统")
    print()

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
