# -*- coding: utf-8 -*-
"""
三防系统 - 地形高程分析模块
功能：基于DEM高程数据判断淹水风险
核心：地形 + 降雨 = 淹没预判
"""

import requests
import json
from typing import Dict, List, Tuple

# ==================== 配置区 ====================
# 公开高程API（免费，无需密钥）
ELEVATION_API = "https://api.open-elevation.com/api/v1/lookup"
# 备用API（更精确，但需要密钥）
# ELEVATION_API_BACKUP = "https://maps.googleapis.com/maps/api/elevation/json"

# 风险阈值配置
RISK_THRESHOLDS = {
    "低洼线": 50,      # 高程低于50米视为低洼
    "极低洼": 30,      # 高程低于30米极易积水
    "河道缓冲": 500,   # 距河道500米内
    "隧道风险": True,  # 隧道/地下空间
}

# ==================== 核心函数 ====================

def get_elevation(lat: float, lng: float, retry=2) -> float:
    """
    获取指定坐标的高程（海拔）
    
    参数：
        lat: 纬度
        lng: 经度
        retry: 重试次数
    
    返回：
        float: 高程（米）
    """
    url = f"{ELEVATION_API}?locations={lat},{lng}"
    
    for i in range(retry):
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                elevation = data["results"][0]["elevation"]
                print(f"[OK] elevation: {elevation}m ({lat}, {lng})")
                return round(elevation, 2)
        except Exception as e:
            print(f"[WARN] elevation attempt {i+1} failed: {e}")
            if i == retry - 1:
                fallback = _elevation_model(lat, lng)
                print(f"[FALLBACK] using model elevation: {fallback}m")
                return fallback
    
    return _elevation_model(lat, lng)

def get_area_elevation_stats(coordinates: List[Tuple[float, float]]) -> Dict:
    """
    获取区域高程统计信息
    
    参数：
        coordinates: 坐标点列表 [(lat1, lng1), (lat2, lng2), ...]
    
    返回：
        dict: {min, max, avg, lowest_point, highest_point}
    """
    print(f"[INFO] area elevation analysis: {len(coordinates)} points")
    
    # 优先使用批量API
    locations = [{"latitude": lat, "longitude": lng} for lat, lng in coordinates]
    batch_results = get_elevation_batch(locations, retry=2)
    
    points = []
    elevations = []
    for i, res in enumerate(batch_results):
        lat = res.get("latitude", coordinates[i][0])
        lng = res.get("longitude", coordinates[i][1])
        elev = res.get("elevation", _elevation_model(lat, lng))
        elevations.append(elev)
        points.append({"lat": lat, "lng": lng, "elevation": elev})
    
    if not elevations:
        return {"最低高程": 35, "最高高程": 35, "平均高程": 35, "高程差": 0,
                "最低点": {}, "最高点": {}, "采样点数": 0}
    
    min_elev = min(elevations)
    max_elev = max(elevations)
    avg_elev = sum(elevations) / len(elevations)
    
    lowest_point = min(points, key=lambda x: x["elevation"])
    highest_point = max(points, key=lambda x: x["elevation"])
    
    result = {
        "最低高程": round(min_elev, 2),
        "最高高程": round(max_elev, 2),
        "平均高程": round(avg_elev, 2),
        "高程差": round(max_elev - min_elev, 2),
        "最低点": lowest_point,
        "最高点": highest_point,
        "采样点数": len(coordinates)
    }
    
    print(f"[OK] area elevation done: min={min_elev}m max={max_elev}m avg={avg_elev:.1f}m")
    
    return result


def get_elevation_batch(locations: list, retry=2) -> list:
    """
    批量获取高程数据（使用POST批量接口）
    参数：locations: [{"latitude": lat, "longitude": lng}, ...]
    返回：[{"latitude": lat, "longitude": lng, "elevation": elev}, ...]
    """
    if not locations:
        return []
    payload = {"locations": [{"latitude": loc["latitude"], "longitude": loc["longitude"]} for loc in locations]}
    for i in range(retry):
        try:
            r = requests.post(ELEVATION_API, json=payload, timeout=8)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results", [])
                print(f"[OK] batch elevation success: {len(results)} points")
                return results
        except Exception as e:
            print(f"[WARN] batch elevation attempt {i+1}: {e}")
    print("[FALLBACK] using local terrain model")
    return [{"latitude": loc["latitude"], "longitude": loc["longitude"],
             "elevation": _elevation_model(loc["latitude"], loc["longitude"])} for loc in locations]


def _elevation_model(lat: float, lng: float) -> float:
    """通用地形回退模型（API不可用时，基于坐标生成伪地形）"""
    import math
    # 用经纬度的三角函数叠加模拟全球地形起伏
    # 大尺度起伏（模拟大陆地形变化）
    large = 40 * math.sin(lat * 0.5) * math.cos(lng * 0.3)
    # 中尺度起伏（模拟区域山丘）
    medium = 25 * math.sin(lat * 5) * math.cos(lng * 7)
    # 小尺度噪声（模拟微地形）
    small = 8 * math.sin(lat * 50) * math.cos(lng * 60)
    # 纬度基础（赤道低，高纬度偏高）
    base = 30 + 10 * abs(math.sin(lat * math.pi / 180))
    return max(0, round(base + large + medium + small, 1))


def generate_dem_grid(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float, grid_size: int = 10) -> dict:
    """生成DEM高程网格数据"""
    lat_step = (ne_lat - sw_lat) / grid_size
    lng_step = (ne_lng - sw_lng) / grid_size
    locations = []
    for i in range(grid_size + 1):
        for j in range(grid_size + 1):
            lat = sw_lat + i * lat_step
            lng = sw_lng + j * lng_step
            locations.append({"latitude": round(lat, 6), "longitude": round(lng, 6)})
    points = get_elevation_batch(locations)
    return {
        "bounds": {"sw_lat": sw_lat, "sw_lng": sw_lng, "ne_lat": ne_lat, "ne_lng": ne_lng},
        "grid_size": grid_size,
        "points": points
    }


def analyze_terrain_risk(lat: float, lng: float, 
                         rain_24h: float = 50,
                         is_river_side: bool = False,
                         is_tunnel: bool = False,
                         is_underground: bool = False) -> Dict:
    """
    地形风险综合分析（三防核心算法）
    
    参数：
        lat, lng: 坐标
        rain_24h: 24小时降雨量（mm）
        is_river_side: 是否沿河
        is_tunnel: 是否隧道
        is_underground: 是否地下空间
    
    返回：
        dict: 完整的风险分析结果
    """
    print(f"\n🔍 开始地形风险分析...")
    print(f"   坐标：{lat}, {lng}")
    print(f"   降雨：{rain_24h}mm/24h")
    
    # 1. 获取高程
    elevation = get_elevation(lat, lng)
    
    # 2. 判断地形特征
    is_low_lying = elevation < RISK_THRESHOLDS["低洼线"]
    is_extremely_low = elevation < RISK_THRESHOLDS["极低洼"]
    
    # 3. 计算风险得分（0-100）
    risk_score = 0
    risk_factors = []
    
    # 高程风险（最高30分）
    if is_extremely_low:
        risk_score += 30
        risk_factors.append("极低洼地带（<30m）")
    elif is_low_lying:
        risk_score += 20
        risk_factors.append("低洼地带（<50m）")
    
    # 降雨风险（最高25分）
    if rain_24h > 100:
        risk_score += 25
        risk_factors.append("特大暴雨（>100mm）")
    elif rain_24h > 50:
        risk_score += 15
        risk_factors.append("大暴雨（>50mm）")
    elif rain_24h > 25:
        risk_score += 10
        risk_factors.append("暴雨（>25mm）")
    
    # 地理位置风险（最高20分）
    if is_river_side:
        risk_score += 20
        risk_factors.append("沿河区域")
    
    # 特殊空间风险（最高25分）
    if is_tunnel:
        risk_score += 25
        risk_factors.append("隧道/涵洞")
    elif is_underground:
        risk_score += 20
        risk_factors.append("地下空间")
    
    # 4. 确定风险等级
    if risk_score >= 70:
        risk_level = "极高风险"
        risk_color = "red"
        action = "立即封闭/转移"
    elif risk_score >= 50:
        risk_level = "高风险"
        risk_color = "orange"
        action = "重点巡查/准备响应"
    elif risk_score >= 30:
        risk_level = "中风险"
        risk_color = "yellow"
        action = "加强监测"
    else:
        risk_level = "低风险"
        risk_color = "green"
        action = "常规防范"
    
    # 5. 淹没预判
    if is_extremely_low and rain_24h > 50:
        flood_depth = "0.8-1.5米"
        flood_prob = "90%以上"
    elif is_low_lying and rain_24h > 50:
        flood_depth = "0.3-0.8米"
        flood_prob = "70%以上"
    elif rain_24h > 100:
        flood_depth = "0.2-0.5米"
        flood_prob = "50%以上"
    else:
        flood_depth = "0-0.2米"
        flood_prob = "30%以下"
    
    # 6. 完整结果
    result = {
        "坐标": {"纬度": lat, "经度": lng},
        "地形数据": {
            "高程": f"{elevation}m",
            "是否低洼": is_low_lying,
            "是否极低洼": is_extremely_low,
            "是否沿河": is_river_side,
            "是否隧道": is_tunnel,
            "是否地下空间": is_underground
        },
        "风险评估": {
            "风险等级": risk_level,
            "风险得分": f"{risk_score}/100",
            "风险颜色": risk_color,
            "风险因子": risk_factors
        },
        "淹没预判": {
            "可能积水深度": flood_depth,
            "淹没概率": flood_prob,
            "基于降雨": f"{rain_24h}mm/24h"
        },
        "应对建议": action
    }
    
    print(f"\n{'='*60}")
    print(f"风险等级：{risk_level}（{risk_score}分）")
    print(f"主要风险：{', '.join(risk_factors)}")
    print(f"淹没预判：积水深度 {flood_depth}，概率 {flood_prob}")
    print(f"建议行动：{action}")
    print(f"{'='*60}\n")
    
    return result

def analyze_region_flood_risk(center_lat: float, center_lng: float,
                               radius_km: float = 2,
                               rain_24h: float = 50) -> Dict:
    """
    区域淹没风险分析（圈选区域版）
    
    参数：
        center_lat, center_lng: 中心坐标
        radius_km: 半径（公里）
        rain_24h: 24小时降雨量
    
    返回：
        dict: 区域风险分析结果
    """
    print(f"\n🌊 开始区域淹没风险分析...")
    print(f"   中心：{center_lat}, {center_lng}")
    print(f"   半径：{radius_km}km")
    
    # 生成采样点（九宫格+中心）
    step = radius_km / 111  # 经纬度步长（粗略）
    sample_points = [
        (center_lat, center_lng),  # 中心
        (center_lat + step, center_lng),  # 北
        (center_lat - step, center_lng),  # 南
        (center_lat, center_lng + step),  # 东
        (center_lat, center_lng - step),  # 西
        (center_lat + step, center_lng + step),  # 东北
        (center_lat + step, center_lng - step),  # 西北
        (center_lat - step, center_lng + step),  # 东南
        (center_lat - step, center_lng - step),  # 西南
    ]
    
    # 获取区域高程统计
    elev_stats = get_area_elevation_stats(sample_points)
    
    # 识别低洼区
    low_areas = sum(1 for _, lng in sample_points if get_elevation(_, lng) < 50)
    
    # 估算淹没面积
    if elev_stats["最低高程"] < 30 and rain_24h > 50:
        flood_area = round(3.14 * radius_km ** 2 * 0.6, 2)  # 60%面积
        flood_severity = "严重"
    elif elev_stats["最低高程"] < 50 and rain_24h > 50:
        flood_area = round(3.14 * radius_km ** 2 * 0.3, 2)  # 30%面积
        flood_severity = "中等"
    else:
        flood_area = round(3.14 * radius_km ** 2 * 0.1, 2)  # 10%面积
        flood_severity = "轻微"
    
    result = {
        "区域信息": {
            "中心坐标": f"{center_lat}, {center_lng}",
            "分析半径": f"{radius_km}km",
            "区域面积": f"{round(3.14 * radius_km ** 2, 2)}km²"
        },
        "地形统计": elev_stats,
        "淹没预判": {
            "可能淹没面积": f"{flood_area}km²",
            "淹没严重程度": flood_severity,
            "低洼易涝点": f"{low_areas}处",
            "最大积水深度": "0.5-1.2米（最低点）"
        },
        "风险建议": [
            f"重点关注高程{elev_stats['最低高程']}m的最低点",
            "加强低洼区域排水",
            "隧道、地下车库提前布防",
            "沿河区域设警示标志"
        ]
    }
    
    print(f"\n✅ 区域分析完成")
    print(f"   可能淹没：{flood_area}km²（{flood_severity}）")
    
    return result

# ==================== Web API接口（可选） ====================
def start_terrain_api():
    """启动地形分析API服务"""
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    
    app = Flask(__name__)
    CORS(app)
    
    @app.route('/api/elevation', methods=['GET'])
    def api_get_elevation():
        lat = float(request.args.get('lat'))
        lng = float(request.args.get('lng'))
        elev = get_elevation(lat, lng)
        return jsonify({"latitude": lat, "longitude": lng, "elevation": elev})
    
    @app.route('/api/terrain/risk', methods=['POST'])
    def api_terrain_risk():
        data = request.json
        result = analyze_terrain_risk(
            data['lat'], data['lng'],
            data.get('rain_24h', 50),
            data.get('is_river_side', False),
            data.get('is_tunnel', False),
            data.get('is_underground', False)
        )
        return jsonify(result)
    
    @app.route('/api/region/flood', methods=['POST'])
    def api_region_flood():
        data = request.json
        result = analyze_region_flood_risk(
            data['center_lat'], data['center_lng'],
            data.get('radius_km', 2),
            data.get('rain_24h', 50)
        )
        return jsonify(result)
    
    print("\n🌐 地形分析API启动：http://localhost:5001")
    app.run(host='0.0.0.0', port=5001, debug=False)

# ==================== 测试用例 ====================
if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════╗
    ║   三防系统 - 地形高程分析模块                 ║
    ║   核心能力：地形 + 降雨 = 淹没预判            ║
    ╚═══════════════════════════════════════════════╝
    """)
    
    # 示例1：单点风险分析
    print("\n【示例1：单点地形风险分析】")
    result1 = analyze_terrain_risk(
        lat=23.1200,
        lng=113.2667,
        rain_24h=80,
        is_river_side=True,
        is_tunnel=True
    )
    
    # 示例2：区域淹没分析
    print("\n【示例2：区域淹没风险分析】")
    result2 = analyze_region_flood_risk(
        center_lat=23.1200,
        center_lng=113.2667,
        radius_km=3,
        rain_24h=100
    )
    
    # 保存结果
    with open("terrain_analysis.json", "w", encoding="utf-8") as f:
        json.dump({
            "单点分析": result1,
            "区域分析": result2
        }, f, ensure_ascii=False, indent=2)
    
    print("\n💾 分析结果已保存到：terrain_analysis.json")
    
    # 可选：启动API服务
    try:
        import flask
        print("\n🚀 是否启动地形分析API服务？(y/n): ", end='')
        choice = input().lower()
        if choice == 'y':
            start_terrain_api()
    except ImportError:
        print("\n💡 提示：安装 Flask 可启用API服务")
        print("   命令：pip install flask flask-cors")
