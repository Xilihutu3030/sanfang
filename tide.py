# -*- coding: utf-8 -*-
"""
三防系统 - 潮汐与海洋数据模块
数据源：Open-Meteo Marine API（全球免费，无需密钥）
功能：潮汐/波浪/海洋气象数据获取与风险评估
"""

import requests
import math
from datetime import datetime, timedelta
from typing import Dict, Optional

# ==================== 配置 ====================
MARINE_API = "https://marine-api.open-meteo.com/v1/marine"
# 潮汐高度简化模型参数（天文潮）
TIDE_PERIOD_M2 = 12.4206  # 主太阴半日潮周期(小时)
TIDE_PERIOD_S2 = 12.0     # 主太阳半日潮周期(小时)

# ==================== 海洋气象数据 ====================

def get_marine_data(lat: float, lng: float, forecast_days: int = 2) -> Dict:
    """
    获取海洋气象数据（波浪、涌浪等）
    全球任意坐标，Open-Meteo Marine API
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": ",".join([
            "wave_height", "wave_direction", "wave_period",
            "wind_wave_height", "wind_wave_period",
            "swell_wave_height", "swell_wave_period", "swell_wave_direction",
        ]),
        "forecast_days": min(forecast_days, 7),
        "timezone": "auto",
    }
    try:
        r = requests.get(MARINE_API, params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return _parse_marine_data(data)
    except Exception as e:
        print(f"[WARN] marine data fetch failed: {e}")
    return _empty_marine()


def _parse_marine_data(raw: Dict) -> Dict:
    """解析 Open-Meteo Marine 响应"""
    hourly = raw.get("hourly", {})
    times = hourly.get("time", [])
    wave_h = hourly.get("wave_height", [])
    wave_d = hourly.get("wave_direction", [])
    wave_p = hourly.get("wave_period", [])
    wind_wave_h = hourly.get("wind_wave_height", [])
    swell_h = hourly.get("swell_wave_height", [])
    swell_d = hourly.get("swell_wave_direction", [])

    if not times:
        return _empty_marine()

    # 找当前最近的时刻
    now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
    idx = 0
    for i, t in enumerate(times):
        if t >= now_str:
            idx = i
            break

    # 未来24小时数据
    future_24 = min(idx + 24, len(times))
    wave_h_24 = [v for v in wave_h[idx:future_24] if v is not None]
    swell_h_24 = [v for v in swell_h[idx:future_24] if v is not None]

    current = {
        "wave_height": wave_h[idx] if idx < len(wave_h) and wave_h[idx] is not None else 0,
        "wave_direction": wave_d[idx] if idx < len(wave_d) and wave_d[idx] is not None else 0,
        "wave_period": wave_p[idx] if idx < len(wave_p) and wave_p[idx] is not None else 0,
        "wind_wave_height": wind_wave_h[idx] if idx < len(wind_wave_h) and wind_wave_h[idx] is not None else 0,
        "swell_height": swell_h[idx] if idx < len(swell_h) and swell_h[idx] is not None else 0,
        "swell_direction": swell_d[idx] if idx < len(swell_d) and swell_d[idx] is not None else 0,
    }

    forecast_max_wave = max(wave_h_24) if wave_h_24 else 0
    forecast_max_swell = max(swell_h_24) if swell_h_24 else 0

    return {
        "status": "ok",
        "current": current,
        "forecast_24h": {
            "max_wave_height": round(forecast_max_wave, 2),
            "max_swell_height": round(forecast_max_swell, 2),
            "avg_wave_height": round(sum(wave_h_24) / len(wave_h_24), 2) if wave_h_24 else 0,
        },
        "hourly": {
            "time": times[idx:future_24],
            "wave_height": wave_h[idx:future_24],
            "swell_height": swell_h[idx:future_24],
        },
        "risk": _assess_marine_risk(current, forecast_max_wave, forecast_max_swell),
    }


def _empty_marine() -> Dict:
    return {"status": "unavailable", "current": {}, "forecast_24h": {}, "hourly": {}, "risk": {}}


# ==================== 天文潮汐简化计算 ====================

def predict_tide(lat: float, lng: float, hours_ahead: int = 24) -> Dict:
    """
    简化天文潮汐预测（基于调和分析主分潮）
    适用于全球任意沿海位置的粗略潮汐预测
    """
    now = datetime.utcnow()
    predictions = []

    # 基于经度估算潮汐相位偏移
    phase_offset = (lng / 360) * 2 * math.pi

    for h in range(hours_ahead + 1):
        t = now + timedelta(hours=h)
        hours_since_epoch = (t - datetime(2000, 1, 1)).total_seconds() / 3600

        # M2主太阴半日潮（最主要分潮）
        m2 = 0.8 * math.cos(2 * math.pi * hours_since_epoch / TIDE_PERIOD_M2 + phase_offset)
        # S2主太阳半日潮
        s2 = 0.3 * math.cos(2 * math.pi * hours_since_epoch / TIDE_PERIOD_S2 + phase_offset * 0.9)
        # K1太阴太阳赤纬日潮
        k1 = 0.2 * math.cos(2 * math.pi * hours_since_epoch / 23.9345 + phase_offset * 1.1)
        # 纬度影响振幅
        lat_factor = max(0.3, math.cos(math.radians(lat)))

        level = round((m2 + s2 + k1) * lat_factor, 2)
        predictions.append({
            "time": t.strftime("%Y-%m-%dT%H:00"),
            "level": level,
        })

    # 识别高低潮
    highs, lows = _find_extremes(predictions)

    current_level = predictions[0]["level"] if predictions else 0
    trend = "rising" if len(predictions) > 1 and predictions[1]["level"] > predictions[0]["level"] else "falling"

    return {
        "status": "ok",
        "method": "astronomical_harmonic",
        "current": {
            "level": current_level,
            "trend": trend,
            "trend_cn": "涨潮中" if trend == "rising" else "退潮中",
        },
        "next_high_tides": highs[:3],
        "next_low_tides": lows[:3],
        "hourly": predictions,
        "risk": _assess_tide_risk(current_level, highs),
    }


def _find_extremes(predictions: list):
    """从预测序列中找高低潮"""
    highs, lows = [], []
    for i in range(1, len(predictions) - 1):
        prev_l = predictions[i - 1]["level"]
        curr_l = predictions[i]["level"]
        next_l = predictions[i + 1]["level"]
        if curr_l > prev_l and curr_l > next_l:
            highs.append(predictions[i])
        elif curr_l < prev_l and curr_l < next_l:
            lows.append(predictions[i])
    return highs, lows


# ==================== 风险评估 ====================

def _assess_marine_risk(current: Dict, max_wave: float, max_swell: float) -> Dict:
    """海洋气象风险评估"""
    score = 0
    factors = []

    wh = current.get("wave_height", 0) or 0
    if wh >= 4:
        score += 40; factors.append(f"巨浪({wh:.1f}m)")
    elif wh >= 2.5:
        score += 25; factors.append(f"大浪({wh:.1f}m)")
    elif wh >= 1.5:
        score += 10; factors.append(f"中浪({wh:.1f}m)")

    if max_wave >= 4:
        score += 20; factors.append(f"24h内预计巨浪({max_wave:.1f}m)")
    elif max_wave >= 2.5:
        score += 10; factors.append(f"24h内预计大浪({max_wave:.1f}m)")

    sh = current.get("swell_height", 0) or 0
    if sh >= 3:
        score += 20; factors.append(f"大涌浪({sh:.1f}m)")
    elif sh >= 1.5:
        score += 10; factors.append(f"中涌浪({sh:.1f}m)")

    if score >= 60:
        level, color = "extreme", "red"
    elif score >= 40:
        level, color = "high", "orange"
    elif score >= 20:
        level, color = "medium", "yellow"
    else:
        level, color = "low", "green"

    level_cn = {"extreme": "极高风险", "high": "高风险", "medium": "中风险", "low": "低风险"}

    return {
        "score": score,
        "level": level,
        "level_cn": level_cn.get(level, "低风险"),
        "color": color,
        "factors": factors,
    }


def _assess_tide_risk(current_level: float, highs: list) -> Dict:
    """潮汐风险评估"""
    score = 0
    factors = []

    if current_level > 0.8:
        score += 30; factors.append("当前高潮位")
    elif current_level > 0.5:
        score += 15; factors.append("当前潮位偏高")

    if highs:
        max_high = max(h["level"] for h in highs[:3])
        if max_high > 0.9:
            score += 25; factors.append(f"近期将出现高潮位({max_high:.2f}m)")

    if score >= 40:
        level_cn = "高风险"
    elif score >= 20:
        level_cn = "中风险"
    else:
        level_cn = "低风险"

    return {"score": score, "level_cn": level_cn, "factors": factors}


# ==================== 综合接口 ====================

def get_full_marine_report(lat: float, lng: float) -> Dict:
    """获取完整的海洋/潮汐报告"""
    marine = get_marine_data(lat, lng)
    tide = predict_tide(lat, lng)

    return {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "location": {"lat": lat, "lng": lng},
        "marine": marine,
        "tide": tide,
    }


# ==================== 测试 ====================
if __name__ == "__main__":
    import json
    # 测试：广州(23.13, 113.27)
    print("=== Test: Guangzhou ===")
    r1 = get_full_marine_report(23.13, 113.27)
    print(json.dumps(r1, ensure_ascii=False, indent=2, default=str))

    # 测试：纽约(40.7, -74.0)
    print("\n=== Test: New York ===")
    r2 = get_full_marine_report(40.7, -74.0)
    print(json.dumps(r2, ensure_ascii=False, indent=2, default=str))
