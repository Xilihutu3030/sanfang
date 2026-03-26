# -*- coding: utf-8 -*-
"""
三防系统 - 全球实时气象数据模块
数据源：Open-Meteo API（全球免费，无需密钥）
功能：实时天气 + 逐小时降雨 + 预警评估
"""

import requests
from datetime import datetime
from typing import Dict

# ==================== Open-Meteo API ====================
WEATHER_API = "https://api.open-meteo.com/v1/forecast"


def get_realtime_weather(lat: float, lng: float) -> Dict:
    """
    获取全球任意坐标的实时气象数据
    包含：当前天气 + 过去24h降雨 + 未来24h预报
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "current": ",".join([
            "temperature_2m", "relative_humidity_2m", "apparent_temperature",
            "precipitation", "rain", "weather_code", "wind_speed_10m",
            "wind_direction_10m", "wind_gusts_10m", "pressure_msl",
        ]),
        "hourly": ",".join([
            "temperature_2m", "precipitation", "rain",
            "weather_code", "wind_speed_10m", "wind_gusts_10m",
            "visibility", "pressure_msl",
        ]),
        "past_hours": 24,
        "forecast_hours": 48,
        "timezone": "auto",
    }

    try:
        r = requests.get(WEATHER_API, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return _parse_weather(data, lat, lng)
    except Exception as e:
        print(f"[WARN] weather fetch failed: {e}")

    return _fallback_weather(lat, lng)


def _parse_weather(raw: Dict, lat: float, lng: float) -> Dict:
    """解析 Open-Meteo 天气响应"""
    current = raw.get("current", {})
    hourly = raw.get("hourly", {})
    times = hourly.get("time", [])
    precip_h = hourly.get("precipitation", [])
    rain_h = hourly.get("rain", [])
    temp_h = hourly.get("temperature_2m", [])
    wind_h = hourly.get("wind_speed_10m", [])
    gust_h = hourly.get("wind_gusts_10m", [])
    wcode_h = hourly.get("weather_code", [])
    vis_h = hourly.get("visibility", [])

    now_str = datetime.now().strftime("%Y-%m-%dT%H:00")

    # 找当前时刻索引
    now_idx = 0
    for i, t in enumerate(times):
        if t >= now_str:
            now_idx = i
            break

    # 过去24h降雨统计
    past_24_start = max(0, now_idx - 24)
    past_24_rain = [v for v in precip_h[past_24_start:now_idx] if v is not None]
    rain_24h = round(sum(past_24_rain), 1) if past_24_rain else 0

    # 过去1h降雨
    past_1_rain = [v for v in precip_h[max(0, now_idx - 1):now_idx] if v is not None]
    rain_1h = round(sum(past_1_rain), 1) if past_1_rain else 0

    # 未来6h/24h降雨预报
    future_6 = min(now_idx + 6, len(precip_h))
    future_24 = min(now_idx + 24, len(precip_h))
    future_48 = min(now_idx + 48, len(precip_h))
    rain_f6 = sum(v for v in precip_h[now_idx:future_6] if v is not None)
    rain_f24 = sum(v for v in precip_h[now_idx:future_24] if v is not None)

    # 未来最大风速
    future_wind = [v for v in wind_h[now_idx:future_24] if v is not None]
    future_gust = [v for v in gust_h[now_idx:future_24] if v is not None]
    max_wind = max(future_wind) if future_wind else 0
    max_gust = max(future_gust) if future_gust else 0

    # 天气代码解读
    wmo_code = current.get("weather_code", 0)
    weather_text = _wmo_code_to_text(wmo_code)

    # 未来6h天气代码 -> 最严重的
    future_codes = [v for v in wcode_h[now_idx:future_6] if v is not None]
    worst_future_code = max(future_codes) if future_codes else 0
    forecast_6h = _wmo_code_to_text(worst_future_code)

    # 预警等级评估
    warning = _assess_weather_warning(rain_24h, rain_f24, max_wind, max_gust, rain_1h)

    return {
        "update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "data_source": "Open-Meteo (real-time)",
        "location": {"lat": lat, "lng": lng},
        "综合研判": {
            "预警等级": warning["text"],
            "当前雨量_1h": rain_1h,
            "累计雨量_24h": rain_24h,
            "未来6h预报降雨": round(rain_f6, 1),
            "未来24h预报降雨": round(rain_f24, 1),
            "未来1h预报": weather_text,
            "未来6h预报": forecast_6h,
            "未来24h预报": _wmo_code_to_text(max(wcode_h[now_idx:future_24]) if wcode_h[now_idx:future_24] else 0),
            "雷达回波": _precip_intensity_text(rain_1h),
            "风险建议": warning["suggestion"],
            "warning_level": warning["level"],
        },
        "当前天气": {
            "天气": weather_text,
            "气温": current.get("temperature_2m", 0),
            "体感温度": current.get("apparent_temperature", 0),
            "湿度": current.get("relative_humidity_2m", 0),
            "气压": current.get("pressure_msl", 0),
            "风速": current.get("wind_speed_10m", 0),
            "阵风": current.get("wind_gusts_10m", 0),
            "风向": _wind_direction_text(current.get("wind_direction_10m", 0)),
            "当前降雨": current.get("precipitation", 0),
        },
        "未来预报": {
            "最大风速_24h": round(max_wind, 1),
            "最大阵风_24h": round(max_gust, 1),
            "累计降雨_6h": round(rain_f6, 1),
            "累计降雨_24h": round(rain_f24, 1),
        },
        "逐小时": {
            "time": times[now_idx:future_48],
            "precipitation": precip_h[now_idx:future_48],
            "temperature": temp_h[now_idx:future_48],
            "wind_speed": wind_h[now_idx:future_48],
        },
        "sources": [
            {"source": "Open-Meteo Global", "status": "success"},
        ],
    }


def _assess_weather_warning(rain_24h, rain_f24, max_wind, max_gust, rain_1h) -> Dict:
    """综合气象预警评估"""
    total_rain = rain_24h + rain_f24
    level = 0
    factors = []

    # 降雨等级
    if rain_24h >= 100 or rain_f24 >= 100:
        level = max(level, 4)
        factors.append("特大暴雨")
    elif rain_24h >= 50 or rain_f24 >= 50:
        level = max(level, 3)
        factors.append("暴雨")
    elif rain_24h >= 25 or rain_f24 >= 25:
        level = max(level, 2)
        factors.append("大雨")
    elif rain_24h >= 10 or rain_f24 >= 10:
        level = max(level, 1)
        factors.append("中雨")

    # 风力等级
    if max_gust >= 108:  # 12级以上
        level = max(level, 4)
        factors.append("超强台风级阵风")
    elif max_gust >= 62:  # 8级以上
        level = max(level, 3)
        factors.append("大风")
    elif max_gust >= 39:
        level = max(level, 2)
        factors.append("强风")

    # 短时强降雨
    if rain_1h >= 20:
        level = max(level, 3)
        factors.append("短时强降雨")

    colors = {0: "无预警", 1: "蓝色预警", 2: "黄色预警", 3: "橙色预警", 4: "红色预警"}
    suggestions = {
        0: "天气状况良好，保持常规监测",
        1: "注意防范，加强值守",
        2: "建议启动防御响应，重点区域巡查",
        3: "建议启动III级应急响应，低洼区域预警",
        4: "立即启动I级应急响应，组织人员转移",
    }

    return {
        "level": level,
        "text": colors.get(level, "无预警") + ("(" + "+".join(factors) + ")" if factors else ""),
        "suggestion": suggestions.get(level, ""),
        "factors": factors,
    }


def _wmo_code_to_text(code: int) -> str:
    """WMO 天气代码 -> 中文"""
    wmo = {
        0: "晴天", 1: "大部晴朗", 2: "多云", 3: "阴天",
        45: "雾", 48: "冻雾",
        51: "小毛毛雨", 53: "中毛毛雨", 55: "大毛毛雨",
        56: "冻毛毛雨", 57: "强冻毛毛雨",
        61: "小雨", 63: "中雨", 65: "大雨",
        66: "冻雨", 67: "强冻雨",
        71: "小雪", 73: "中雪", 75: "大雪",
        77: "雪粒", 80: "小阵雨", 81: "中阵雨", 82: "大阵雨/暴雨",
        85: "小阵雪", 86: "大阵雪",
        95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
    }
    return wmo.get(code, f"天气代码{code}")


def _precip_intensity_text(rain_1h: float) -> str:
    """降雨强度描述"""
    if rain_1h >= 16:
        return "特强降雨回波"
    elif rain_1h >= 8:
        return "强降雨回波"
    elif rain_1h >= 4:
        return "中等降雨回波"
    elif rain_1h >= 0.5:
        return "弱降雨回波"
    return "无明显降雨回波"


def _wind_direction_text(deg: float) -> str:
    """风向角度 -> 中文"""
    dirs = ["北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风"]
    idx = round(deg / 45) % 8
    return dirs[idx]


def _fallback_weather(lat: float, lng: float) -> Dict:
    """API 不可用时的兜底数据"""
    return {
        "update_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "data_source": "fallback",
        "location": {"lat": lat, "lng": lng},
        "综合研判": {
            "预警等级": "数据获取中",
            "当前雨量_1h": 0,
            "累计雨量_24h": 0,
            "未来6h预报降雨": 0,
            "未来24h预报降雨": 0,
            "未来1h预报": "数据获取中",
            "未来6h预报": "数据获取中",
            "未来24h预报": "数据获取中",
            "雷达回波": "无数据",
            "风险建议": "气象数据暂时不可用，请人工确认天气情况",
            "warning_level": 0,
        },
        "当前天气": {},
        "未来预报": {},
        "逐小时": {},
        "sources": [{"source": "Open-Meteo Global", "status": "fallback"}],
    }


# ==================== 测试 ====================
if __name__ == "__main__":
    import json
    # 广州
    print("=== Guangzhou ===")
    r = get_realtime_weather(23.13, 113.27)
    print(json.dumps(r, ensure_ascii=False, indent=2))
