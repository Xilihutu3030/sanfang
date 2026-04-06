# -*- coding: utf-8 -*-
"""
行政区划数据服务
- 提供省/市/县区/乡镇街/村社区多级联动数据
- 代理获取行政区域GeoJSON边界数据
- 数据源：DataV Aliyun (阿里云DataV GeoAtlas)
"""

import json
import os
import hashlib
import time
import logging as _logging
from flask import Blueprint, jsonify, request

_logger = _logging.getLogger('sanfang.regions')


def _safe_log(msg):
    """Windows安全日志输出，避免中文/emoji字符导致OSError"""
    text = str(msg)
    try:
        with open('server_log.txt', 'a', encoding='utf-8') as f:
            f.write(text + '\n')
    except Exception:
        pass
    try:
        print(text)
    except Exception:
        pass

regions = Blueprint('regions', __name__)

# ==================== 边界数据缓存 ====================
_boundary_cache = {}  # code -> {data, time}
CACHE_TTL = 3600 * 24  # 缓存24小时
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache', 'regions')

def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


# ==================== 省级数据（内嵌） ====================
PROVINCES = [
    {"code": "110000", "name": "北京市"},
    {"code": "120000", "name": "天津市"},
    {"code": "130000", "name": "河北省"},
    {"code": "140000", "name": "山西省"},
    {"code": "150000", "name": "内蒙古自治区"},
    {"code": "210000", "name": "辽宁省"},
    {"code": "220000", "name": "吉林省"},
    {"code": "230000", "name": "黑龙江省"},
    {"code": "310000", "name": "上海市"},
    {"code": "320000", "name": "江苏省"},
    {"code": "330000", "name": "浙江省"},
    {"code": "340000", "name": "安徽省"},
    {"code": "350000", "name": "福建省"},
    {"code": "360000", "name": "江西省"},
    {"code": "370000", "name": "山东省"},
    {"code": "410000", "name": "河南省"},
    {"code": "420000", "name": "湖北省"},
    {"code": "430000", "name": "湖南省"},
    {"code": "440000", "name": "广东省"},
    {"code": "450000", "name": "广西壮族自治区"},
    {"code": "460000", "name": "海南省"},
    {"code": "500000", "name": "重庆市"},
    {"code": "510000", "name": "四川省"},
    {"code": "520000", "name": "贵州省"},
    {"code": "530000", "name": "云南省"},
    {"code": "540000", "name": "西藏自治区"},
    {"code": "610000", "name": "陕西省"},
    {"code": "620000", "name": "甘肃省"},
    {"code": "630000", "name": "青海省"},
    {"code": "640000", "name": "宁夏回族自治区"},
    {"code": "650000", "name": "新疆维吾尔自治区"},
    {"code": "710000", "name": "台湾省"},
    {"code": "810000", "name": "香港特别行政区"},
    {"code": "820000", "name": "澳门特别行政区"},
]


def _fetch_datav_geojson(code, full=True):
    """
    从DataV Aliyun获取行政区域GeoJSON数据
    full=True时获取含子区域边界的完整数据
    full=False时只获取当前区域边界
    """
    suffix = '_full' if full else ''
    url = f"https://geo.datav.aliyun.com/areas_v3/bound/{code}{suffix}.json"

    # 先检查文件缓存
    _ensure_cache_dir()
    cache_file = os.path.join(CACHE_DIR, f"{code}{suffix}.json")
    if os.path.exists(cache_file):
        try:
            mtime = os.path.getmtime(cache_file)
            if time.time() - mtime < CACHE_TTL:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass

    # 检查内存缓存
    cache_key = f"{code}{suffix}"
    if cache_key in _boundary_cache:
        entry = _boundary_cache[cache_key]
        if time.time() - entry['time'] < CACHE_TTL:
            return entry['data']

    # 从网络获取
    try:
        import requests
        resp = requests.get(url, timeout=10, headers={
            'User-Agent': 'SanfangSystem/1.0',
            'Referer': 'https://datav.aliyun.com/'
        })
        if resp.status_code == 200:
            data = resp.json()
            # 写入文件缓存
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
            except Exception:
                pass
            # 写入内存缓存
            _boundary_cache[cache_key] = {'data': data, 'time': time.time()}
            return data
    except Exception as e:
        _safe_log(f"[区划数据] 获取 {code} 失败: {e}")

    return None


# ==================== 乡镇街道数据（DataV不覆盖，从开源数据集获取） ====================
_township_cache = {}   # areaCode -> [{code, name}, ...]
_township_loaded = False

def _load_township_data():
    """
    从开源数据集加载全国乡镇/街道数据（约4万条）
    数据源: modood/Administrative-divisions-of-China (GitHub)
    首次加载后缓存到本地文件和内存
    """
    global _township_cache, _township_loaded
    if _township_loaded and _township_cache:
        return _township_cache

    # 先检查本地缓存文件
    _ensure_cache_dir()
    cache_file = os.path.join(CACHE_DIR, 'streets_indexed.json')
    if os.path.exists(cache_file):
        try:
            mtime = os.path.getmtime(cache_file)
            if time.time() - mtime < CACHE_TTL:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    _township_cache = json.load(f)
                _township_loaded = True
                return _township_cache
        except Exception:
            pass

    # 从CDN获取（jsdelivr在国内访问快）
    urls = [
        "https://cdn.jsdelivr.net/gh/modood/Administrative-divisions-of-China@master/dist/streets.json",
        "https://raw.githubusercontent.com/modood/Administrative-divisions-of-China/master/dist/streets.json",
    ]
    try:
        import requests
        data = None
        for url in urls:
            try:
                resp = requests.get(url, timeout=20, headers={'User-Agent': 'SanfangSystem/1.0'})
                if resp.status_code == 200:
                    data = resp.json()
                    break
            except Exception:
                continue

        if data:
            # 按区县码索引
            indexed = {}
            for item in data:
                area_code = str(item.get('areaCode', ''))
                if area_code:
                    if area_code not in indexed:
                        indexed[area_code] = []
                    indexed[area_code].append({
                        'code': str(item.get('code', '')),
                        'name': item.get('name', ''),
                    })
            # 写入本地缓存
            try:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump(indexed, f, ensure_ascii=False)
            except Exception:
                pass
            _township_cache = indexed
            _township_loaded = True
            return indexed
    except Exception as e:
        _safe_log(f"[区划数据] 加载乡镇街道数据失败: {e}")

    return {}


def _get_townships_for_district(district_code):
    """根据区县代码获取下辖乡镇/街道列表"""
    data = _load_township_data()
    district_code = str(district_code)
    return data.get(district_code, [])


# 直辖市代码（北京、天津、上海、重庆）
MUNICIPALITY_CODES = {'110000', '120000', '310000', '500000'}


def _extract_children_from_geojson(geojson):
    """从GeoJSON的features中提取子区域列表"""
    children = []
    if not geojson or 'features' not in geojson:
        return children
    for feat in geojson['features']:
        props = feat.get('properties', {})
        code = str(props.get('adcode', ''))
        name = props.get('name', '')
        # 计算中心点
        center = props.get('center') or props.get('centroid')
        center_lng = center[0] if center else None
        center_lat = center[1] if center else None
        level = props.get('level', '')
        children.append({
            'code': code,
            'name': name,
            'level': level,
            'center': [center_lng, center_lat] if center_lng else None,
        })
    return children


# ==================== API路由 ====================

@regions.route('/api/regions/provinces', methods=['GET'])
def api_provinces():
    """获取省级列表"""
    return jsonify({"regions": PROVINCES, "level": "province"})


@regions.route('/api/regions/children/<code>', methods=['GET'])
def api_children(code):
    """
    获取指定区域的子区域列表
    例: /api/regions/children/440000 → 广东省下的城市
         /api/regions/children/440100 → 广州市下的区县
         /api/regions/children/440106 → 天河区下的街道
    直辖市（北京/天津/上海/重庆）自动跳过"市辖区"，直接返回区县
    """
    code_str = str(code)
    is_municipality = code_str in MUNICIPALITY_CODES

    geojson = _fetch_datav_geojson(code, full=True)
    children = []
    if geojson:
        children = _extract_children_from_geojson(geojson)

    # 直辖市：跳过"市辖区"中间层，获取实际区县
    if is_municipality and children:
        real_districts = []
        for child in children:
            sub_geojson = _fetch_datav_geojson(child['code'], full=True)
            if sub_geojson:
                sub_children = _extract_children_from_geojson(sub_geojson)
                real_districts.extend(sub_children)
        if real_districts:
            children = real_districts

    # DataV无子区域数据时（区县级别），回退到开源乡镇街道数据集
    parent_center = None
    if not children:
        townships = _get_townships_for_district(code)
        if townships:
            children = [{'code': t['code'], 'name': t['name'], 'level': 'street', 'center': None} for t in townships]
            # 获取父级区县的中心坐标，供前端定位乡镇使用
            parent_geojson = _fetch_datav_geojson(code, full=False)
            if parent_geojson and parent_geojson.get('features'):
                props = parent_geojson['features'][0].get('properties', {})
                pc = props.get('center') or props.get('centroid')
                if pc:
                    parent_center = [pc[0], pc[1]]

    # 确定子级层级
    if is_municipality:
        child_level = 'district'
    elif len(code_str) == 6:
        suffix = code_str[2:]
        if suffix == '0000':
            child_level = 'city'
        elif suffix[-2:] == '00':
            child_level = 'district'
        else:
            child_level = 'town'
    else:
        child_level = 'unknown'

    result = {
        "parent_code": code,
        "regions": children,
        "level": child_level,
        "count": len(children),
    }
    if is_municipality:
        result["is_municipality"] = True
    if parent_center:
        result["parent_center"] = parent_center
    return jsonify(result)


# ==================== 地理编码（定位乡镇街道） ====================

_geocode_cache = {}  # query_hash -> {lat, lng, time}

def _geocode_place(query):
    """使用Photon免费地理编码服务定位地名（基于OpenStreetMap数据，国内可达）"""
    cache_key = hashlib.md5(query.encode('utf-8')).hexdigest()
    if cache_key in _geocode_cache:
        entry = _geocode_cache[cache_key]
        if time.time() - entry['time'] < CACHE_TTL:
            return entry.get('data')

    # 检查文件缓存
    _ensure_cache_dir()
    cache_file = os.path.join(CACHE_DIR, f"geo_{cache_key}.json")
    if os.path.exists(cache_file):
        try:
            mtime = os.path.getmtime(cache_file)
            if time.time() - mtime < CACHE_TTL:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                _geocode_cache[cache_key] = {'data': data, 'time': time.time()}
                return data
        except Exception:
            pass

    try:
        import requests as req
        # Photon geocoder（komoot，基于OSM，国内可访问）
        # 注意：不能用 lang=zh（Photon不支持），直接用中文查询即可
        resp = req.get(
            "https://photon.komoot.io/api/",
            params={'q': query, 'limit': 3},
            timeout=20,
            headers={'User-Agent': 'SanfangSystem/1.0'}
        )
        if resp.status_code == 200:
            data = resp.json()
            features = data.get('features', [])
            if features:
                # 优先选择 osm_key=place 的结果（行政区划），否则取第一个
                best = features[0]
                for f in features:
                    if f.get('properties', {}).get('osm_key') == 'place':
                        best = f
                        break
                coords = best.get('geometry', {}).get('coordinates', [])
                props = best.get('properties', {})
                if len(coords) >= 2:
                    result = {
                        'lat': float(coords[1]),
                        'lng': float(coords[0]),
                        'display_name': props.get('name', '') or props.get('district', ''),
                    }
                    # Photon返回extent=[west_lng, north_lat, east_lng, south_lat]
                    extent = props.get('extent')
                    if extent and len(extent) == 4:
                        result['bbox'] = {
                            'sw_lng': float(extent[0]),
                            'sw_lat': float(extent[3]),
                            'ne_lng': float(extent[2]),
                            'ne_lat': float(extent[1]),
                        }
                    # 写入缓存
                    try:
                        with open(cache_file, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False)
                    except Exception:
                        pass
                    _geocode_cache[cache_key] = {'data': result, 'time': time.time()}
                    return result
    except Exception as e:
        _safe_log(f"[区划数据] 地理编码失败: {e}")
    return None


@regions.route('/api/regions/geocode', methods=['GET'])
def api_geocode():
    """
    地理编码：根据地名获取坐标
    ?q=广州市黄埔区夏港街道  → 返回 {lat, lng}
    用于定位乡镇/街道级别（DataV无此级别数据时的fallback）
    """
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({"error": "查询参数q至少2个字符"}), 400
    result = _geocode_place(q)
    if result:
        return jsonify(result)
    return jsonify({"error": f"无法定位「{q}」"}), 404


@regions.route('/api/regions/boundary/<code>', methods=['GET'])
def api_boundary(code):
    """
    获取指定区域的GeoJSON边界数据
    ?full=1 包含子区域边界（默认）
    ?full=0 仅当前区域边界
    ?simplify=1 简化坐标点（减少传输量）
    """
    full = request.args.get('full', '1') == '1'
    simplify = request.args.get('simplify', '0') == '1'

    geojson = _fetch_datav_geojson(code, full=full)
    if not geojson:
        return jsonify({"error": f"无法获取区域 {code} 的边界数据"}), 404

    if simplify:
        geojson = _simplify_geojson(geojson)

    return jsonify(geojson)


@regions.route('/api/regions/search', methods=['GET'])
def api_search_region():
    """
    搜索行政区域名称
    ?q=天河  → 模糊匹配包含"天河"的区域
    返回匹配结果（从已缓存的数据中搜索，以及从全国数据中搜索）
    """
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify({"error": "搜索关键词至少2个字符", "results": []}), 400

    results = []

    # 先从省级搜索
    for p in PROVINCES:
        if q in p['name']:
            results.append({**p, 'level': 'province', 'path': p['name']})

    # 从缓存的GeoJSON数据中搜索
    for cache_key, entry in _boundary_cache.items():
        if not cache_key.endswith('_full'):
            continue
        data = entry.get('data')
        if not data or 'features' not in data:
            continue
        for feat in data['features']:
            props = feat.get('properties', {})
            name = props.get('name', '')
            if q in name:
                center = props.get('center') or props.get('centroid')
                results.append({
                    'code': str(props.get('adcode', '')),
                    'name': name,
                    'level': props.get('level', ''),
                    'center': list(center) if center else None,
                    'path': props.get('parent', {}).get('adcode', ''),
                })

    # 去重
    seen = set()
    unique = []
    for r in results:
        if r['code'] not in seen:
            seen.add(r['code'])
            unique.append(r)

    return jsonify({"results": unique[:20], "query": q})


@regions.route('/api/regions/info/<code>', methods=['GET'])
def api_region_info(code):
    """获取单个区域的详细信息（名称、中心点、层级、边界bbox）"""
    geojson = _fetch_datav_geojson(code, full=False)
    if not geojson:
        return jsonify({"error": f"无法获取区域 {code} 的信息"}), 404

    # 从features中提取
    if 'features' in geojson and geojson['features']:
        feat = geojson['features'][0]
        props = feat.get('properties', {})
        center = props.get('center') or props.get('centroid')
        # 计算bbox
        bbox = _calc_bbox(feat.get('geometry', {}))
        return jsonify({
            'code': str(props.get('adcode', code)),
            'name': props.get('name', ''),
            'level': props.get('level', ''),
            'center': list(center) if center else None,
            'bbox': bbox,
            'parent': props.get('parent', {}),
        })

    return jsonify({"error": "数据格式异常"}), 500


def _calc_bbox(geometry):
    """计算GeoJSON geometry的边界框"""
    coords = []
    gtype = geometry.get('type', '')
    raw = geometry.get('coordinates', [])

    if gtype == 'Polygon':
        for ring in raw:
            coords.extend(ring)
    elif gtype == 'MultiPolygon':
        for poly in raw:
            for ring in poly:
                coords.extend(ring)

    if not coords:
        return None

    lngs = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return {
        'sw_lng': min(lngs),
        'sw_lat': min(lats),
        'ne_lng': max(lngs),
        'ne_lat': max(lats),
    }


def _simplify_geojson(geojson, tolerance=0.005):
    """简化GeoJSON坐标（Douglas-Peucker简化的简单版本：间隔采样）"""
    if not geojson or 'features' not in geojson:
        return geojson

    result = {**geojson, 'features': []}
    for feat in geojson['features']:
        new_feat = {**feat}
        geom = feat.get('geometry', {})
        gtype = geom.get('type', '')
        coords = geom.get('coordinates', [])

        if gtype == 'Polygon':
            new_coords = [_simplify_ring(ring, tolerance) for ring in coords]
            new_feat['geometry'] = {**geom, 'coordinates': new_coords}
        elif gtype == 'MultiPolygon':
            new_coords = [[_simplify_ring(ring, tolerance) for ring in poly] for poly in coords]
            new_feat['geometry'] = {**geom, 'coordinates': new_coords}

        result['features'].append(new_feat)
    return result


def _simplify_ring(ring, tolerance):
    """简化坐标环：保留首尾+间距大于tolerance的点"""
    if len(ring) <= 10:
        return ring
    simplified = [ring[0]]
    for i in range(1, len(ring) - 1):
        dx = ring[i][0] - simplified[-1][0]
        dy = ring[i][1] - simplified[-1][1]
        if abs(dx) > tolerance or abs(dy) > tolerance:
            simplified.append(ring[i])
    simplified.append(ring[-1])
    return simplified
