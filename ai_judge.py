# -*- coding: utf-8 -*-
"""
三防系统 - AI智能研判模块（应急管理专家版）
设计理念：像一个干了20年的应急管理老手一样思考
- 看天、看地、看人、看时间，综合判断
- 建议具体到"谁去做、做什么、怎么做、先做哪个"
- 不同场景完全不同的应对策略，绝不套模板
"""

import json
from datetime import datetime
from typing import Dict, List


# ==================== 应急专家知识库 ====================

# 时段特征：不同时间段，风险点和应对策略完全不同
def _get_time_context():
    """获取当前时间上下文，影响建议策略"""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=周一, 6=周日
    month = now.month

    ctx = {
        "hour": hour,
        "is_night": hour >= 22 or hour < 5,
        "is_dawn": 5 <= hour < 7,
        "is_rush_hour": hour in (7, 8, 17, 18),
        "is_school_time": hour in (7, 8, 11, 12, 15, 16, 17) and weekday < 5,
        "is_work_time": 9 <= hour <= 17 and weekday < 5,
        "is_weekend": weekday >= 5,
        "is_flood_season": month in (4, 5, 6, 7, 8, 9),  # 华南汛期4-9月
        "is_typhoon_season": month in (6, 7, 8, 9, 10),
        "period_name": "",
        "crowd_risk": "",
    }

    # 时段名称和人群特征
    if ctx["is_night"]:
        ctx["period_name"] = "深夜"
        ctx["crowd_risk"] = "居民在家睡觉，叫醒转移难度大"
    elif ctx["is_dawn"]:
        ctx["period_name"] = "凌晨"
        ctx["crowd_risk"] = "大部分人刚起床，反应慢"
    elif ctx["is_rush_hour"]:
        ctx["period_name"] = "早晚高峰"
        ctx["crowd_risk"] = "大量车辆行人在路上，隧道桥洞车流密集"
    elif ctx["is_school_time"]:
        ctx["period_name"] = "上下学时段"
        ctx["crowd_risk"] = "学生在路上，老人接送"
    elif ctx["is_work_time"]:
        ctx["period_name"] = "工作时段"
        ctx["crowd_risk"] = "写字楼地下车库满载"
    elif ctx["is_weekend"]:
        ctx["period_name"] = "周末"
        ctx["crowd_risk"] = "商圈人流量大，户外活动多"
    else:
        ctx["period_name"] = "傍晚"
        ctx["crowd_risk"] = "居民活动频繁"

    return ctx


# 洪涝机理知识：不同降雨模式 → 不同灾害特征
def _analyze_rain_pattern(rain_24h, rain_1h, forecast_rain_6h):
    """分析降雨模式，判断灾害类型"""
    pattern = {
        "type": "normal",
        "desc": "",
        "peak_passed": False,
        "intensifying": False,
    }

    if rain_1h >= 50:
        pattern["type"] = "flash"
        pattern["desc"] = "极端短时暴雨，城市排水系统根本来不及排"
    elif rain_1h >= 30:
        pattern["type"] = "intense"
        pattern["desc"] = "短时强降雨，超过多数排水管网设计标准"
    elif rain_24h >= 100:
        pattern["type"] = "sustained_heavy"
        pattern["desc"] = "持续性暴雨，土壤饱和，地表径流大"
    elif rain_24h >= 50:
        pattern["type"] = "heavy"
        pattern["desc"] = "累计雨量大，低洼区域蓄水严重"
    elif rain_24h >= 25:
        pattern["type"] = "moderate"
        pattern["desc"] = "中等降雨，排水压力增大"

    # 判断趋势
    if forecast_rain_6h >= rain_1h * 3 and rain_1h > 0:
        pattern["intensifying"] = True
    if rain_24h > 50 and forecast_rain_6h < 5:
        pattern["peak_passed"] = True

    return pattern


# 风险点专家分析：不同类型风险点，机理和对策完全不同
def _expert_hazard_analysis(hazard_type, elevation, rain_24h, rain_1h, has_history):
    """像老专家一样分析每个风险点"""
    analysis = {"mechanism": "", "critical_rain": 0, "action": "", "priority": 0}

    if "隧道" in hazard_type or "下穿" in hazard_type:
        analysis["mechanism"] = "汇水面积大，雨水从两侧坡道灌入，一旦积水车辆被困致命"
        analysis["critical_rain"] = 20 if elevation < 15 else 35
        analysis["priority"] = 95 if rain_1h >= 20 else 80
        if rain_1h >= analysis["critical_rain"]:
            analysis["action"] = "立即封闭，水位超挡板就来不及了"
        elif rain_24h >= 30:
            analysis["action"] = "派人蹲守入口，积水10cm就封闭"
        else:
            analysis["action"] = "备好封路设备，关注水位变化"

    elif "地下" in hazard_type:
        analysis["mechanism"] = "地面雨水沿坡道倒灌，一旦进水排不出去，车辆泡水损失巨大"
        analysis["critical_rain"] = 25 if elevation < 20 else 40
        analysis["priority"] = 85 if rain_24h >= 30 else 60
        if rain_24h >= analysis["critical_rain"]:
            analysis["action"] = "通知业主立即挪车，沙袋封堵入口坡道"
        else:
            analysis["action"] = "检查挡水板和排水泵，通知物业做好准备"

    elif "河道" in hazard_type or "涌" in hazard_type:
        analysis["mechanism"] = "上游来水+本地降雨叠加，水位快速上涨，漫堤风险"
        analysis["critical_rain"] = 40
        analysis["priority"] = 90 if rain_24h >= 50 else 70
        if rain_24h >= 80:
            analysis["action"] = "沿河居民转移，禁止靠近河道"
        elif rain_24h >= 40:
            analysis["action"] = "每30分钟报一次水位，超警戒立即报告"
        else:
            analysis["action"] = "加密巡查频次，关注上游来水"

    elif "危房" in hazard_type or "老旧" in hazard_type:
        analysis["mechanism"] = "长时间浸泡导致地基软化、墙体开裂，倒塌风险"
        analysis["critical_rain"] = 50
        analysis["priority"] = 88 if rain_24h >= 50 else 50
        if rain_24h >= 50:
            analysis["action"] = "住户全部撤出，拉警戒线"
        elif rain_24h >= 25:
            analysis["action"] = "通知住户注意安全，检查墙体裂缝"
        else:
            analysis["action"] = "列入巡查名单"

    elif "易涝" in hazard_type or "低洼" in hazard_type:
        analysis["mechanism"] = "地势低洼排水不畅，雨水汇集后快速积水"
        analysis["critical_rain"] = 15 if elevation < 15 else 30
        analysis["priority"] = 75 if rain_24h >= 25 else 45
        if rain_24h >= analysis["critical_rain"]:
            analysis["action"] = "开启强排泵站，设置警示标志禁止涉水通行"
        else:
            analysis["action"] = "清理排水口杂物，确保排水畅通"

    elif "边坡" in hazard_type or "山体" in hazard_type or "滑坡" in hazard_type:
        analysis["mechanism"] = "雨水入渗导致土体饱和，重力作用下失稳滑动"
        analysis["critical_rain"] = 50
        analysis["priority"] = 92 if rain_24h >= 80 else 65
        if rain_24h >= 80:
            analysis["action"] = "坡下居民全部撤离，封闭周边道路"
        elif rain_24h >= 50:
            analysis["action"] = "加密监测裂缝变化，坡下居民随时准备撤离"
        else:
            analysis["action"] = "巡查是否有新裂缝、渗水"

    elif "桥" in hazard_type:
        analysis["mechanism"] = "桥下低洼积水，桥面漫水冲刷"
        analysis["critical_rain"] = 25
        analysis["priority"] = 78 if rain_24h >= 30 else 55
        if rain_24h >= 40:
            analysis["action"] = "桥下禁止通行，桥面检查是否漫水"
        else:
            analysis["action"] = "桥下设警示标志，观察积水情况"

    else:
        analysis["mechanism"] = "综合风险"
        analysis["critical_rain"] = 30
        analysis["priority"] = 50
        analysis["action"] = "纳入常规巡查"

    # 历史淹水加权
    if has_history:
        analysis["priority"] = min(100, analysis["priority"] + 15)

    return analysis


# ==================== 核心研判函数 ====================

def ai_comprehensive_judge(
    weather_data: Dict,
    terrain_data: Dict,
    hazard_points: List[Dict],
    history_disaster: List[Dict] = None
) -> Dict:
    """
    AI综合研判 - 应急管理专家版
    像一个经验丰富的应急专家一样：看天、看地、看人、看时间
    """
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    time_ctx = _get_time_context()

    # ========== 读取气象数据 ==========
    rain_24h = weather_data.get("rain_24h", 0)
    rain_1h = weather_data.get("rain_1h", 0)
    warning_level = weather_data.get("warning_level", 0)
    forecast = weather_data.get("forecast", "")
    forecast_rain_6h = weather_data.get("forecast_rain_6h", 0)
    forecast_rain_24h = weather_data.get("forecast_rain_24h", 0)

    # ========== 分析降雨模式 ==========
    rain_pattern = _analyze_rain_pattern(rain_24h, rain_1h, forecast_rain_6h)
    weather_factor = _calc_weather_factor(rain_24h, rain_1h, warning_level, forecast_rain_6h)

    # ========== 判断是否有实际风险 ==========
    has_rain = rain_24h > 0 or rain_1h > 0
    has_warning = warning_level > 0
    has_forecast_rain = forecast_rain_6h >= 10 or forecast_rain_24h >= 25
    has_any_trigger = has_rain or has_warning or has_forecast_rain

    # ========== 无任何触发 ==========
    if not has_any_trigger:
        summary = "当前无降雨、无预警信号"
        if forecast and forecast not in ("--", "", "晴", "多云"):
            summary += f"，未来预报{forecast}，暂无需响应"
        else:
            summary += "，一切正常"

        return {
            "研判时间": now_str,
            "1_综合风险等级": {
                "等级": "暂无风险", "得分": "0/100", "颜色": "绿色",
                "响应等级": "日常监控", "风险因子": []
            },
            "2_主要风险类型": [],
            "3_Top5危险点位": [],
            "4_淹没预判": {},
            "5_指挥建议": [summary],
            "6_领导汇报": summary + "。",
            "简报文本": f"三防研判（{now_str}）：{summary}。"
        }

    # ========== 综合风险评分 ==========
    risk_score, risk_factors = _calc_risk_score(
        rain_24h, rain_1h, warning_level, forecast_rain_6h,
        terrain_data, hazard_points, weather_factor, time_ctx
    )

    # 确定风险等级
    if risk_score >= 70:
        risk_level, risk_color, response_level = "极高风险", "红色", "I级响应"
    elif risk_score >= 50:
        risk_level, risk_color, response_level = "高风险", "橙色", "II级响应"
    elif risk_score >= 30:
        risk_level, risk_color, response_level = "中风险", "黄色", "III级响应"
    elif risk_score >= 10:
        risk_level, risk_color, response_level = "低风险", "蓝色", "IV级响应"
    else:
        risk_level, risk_color, response_level = "暂无风险", "绿色", "日常监控"

    # ========== 主要风险类型 ==========
    min_elevation = terrain_data.get("最低高程", 100)
    tunnel_count = len([h for h in hazard_points if "隧道" in h.get("type", "") or "下穿" in h.get("type", "")])
    underground_count = len([h for h in hazard_points if "地下" in h.get("type", "")])

    main_risks = _identify_main_risks(
        rain_24h, rain_1h, min_elevation, tunnel_count, underground_count,
        hazard_points, terrain_data, has_forecast_rain, rain_pattern
    )

    # ========== Top5危险点位（专家级分析）==========
    top5 = _rank_hazard_points(hazard_points, rain_24h, rain_1h, weather_factor, risk_score)

    # ========== 淹没预判 ==========
    flood = _predict_flood(rain_24h, rain_1h, min_elevation, terrain_data, rain_pattern)

    # ========== 专家级指挥建议 ==========
    suggestions = _build_expert_suggestions(
        risk_score, risk_level, response_level,
        rain_24h, rain_1h, warning_level, forecast, forecast_rain_6h,
        min_elevation, top5, tunnel_count, underground_count,
        hazard_points, time_ctx, rain_pattern, flood, terrain_data
    )

    # ========== 领导汇报 ==========
    leader_report = _build_leader_report(
        risk_score, risk_level, response_level,
        rain_24h, main_risks, top5,
        min_elevation, flood, forecast, time_ctx
    )

    result = {
        "研判时间": now_str,
        "1_综合风险等级": {
            "等级": risk_level, "得分": f"{risk_score}/100",
            "颜色": risk_color, "响应等级": response_level,
            "风险因子": risk_factors
        },
        "2_主要风险类型": main_risks,
        "3_Top5危险点位": top5,
        "4_淹没预判": flood,
        "5_指挥建议": suggestions,
        "6_领导汇报": leader_report
    }

    print(f"[judge] {risk_level} {risk_score}pts | rain={rain_24h}mm warn={warning_level} | "
          f"hazards={len(hazard_points)} top5={len(top5)}")

    return result


# ==================== 风险评分 ====================

def _calc_risk_score(rain_24h, rain_1h, warning_level, forecast_rain_6h,
                     terrain_data, hazard_points, weather_factor, time_ctx):
    """综合风险评分 - 考虑复合效应"""
    score = 0
    factors = []

    # --- 气象基础分（最高40分）---
    ws = 0
    if rain_24h >= 100:
        ws = 40; factors.append(f"特大暴雨{rain_24h:.0f}mm/24h")
    elif rain_24h >= 50:
        ws = 25 + int((rain_24h - 50) / 50 * 15); factors.append(f"暴雨{rain_24h:.0f}mm/24h")
    elif rain_24h >= 25:
        ws = 12 + int((rain_24h - 25) / 25 * 13); factors.append(f"大雨{rain_24h:.0f}mm/24h")
    elif rain_24h >= 10:
        ws = 5 + int((rain_24h - 10) / 15 * 7); factors.append(f"中雨{rain_24h:.0f}mm/24h")
    elif rain_24h > 0:
        ws = int(rain_24h / 10 * 5); factors.append(f"小雨{rain_24h:.1f}mm/24h")

    # 短时强降雨加分（城市内涝的核心诱因）
    if rain_1h >= 50:
        ws = min(40, ws + 12); factors.append(f"极端短时暴雨{rain_1h:.0f}mm/h")
    elif rain_1h >= 30:
        ws = min(40, ws + 8); factors.append(f"短时强降雨{rain_1h:.0f}mm/h")
    elif rain_1h >= 15:
        ws = min(40, ws + 4); factors.append(f"短时较强降雨{rain_1h:.0f}mm/h")

    if warning_level >= 4:
        ws = min(40, ws + 15); factors.append("红色预警")
    elif warning_level >= 3:
        ws = min(40, ws + 10); factors.append("橙色预警")
    elif warning_level >= 2:
        ws = min(40, ws + 5); factors.append("黄色预警")
    elif warning_level >= 1:
        ws = min(40, ws + 2); factors.append("蓝色预警")

    score += ws

    # --- 地形分 × 气象因子 ---
    min_elev = terrain_data.get("最低高程", 100)
    low_areas = terrain_data.get("低洼易涝点", 0)
    tr = 0
    if min_elev < 10: tr = 30
    elif min_elev < 20: tr = 25
    elif min_elev < 30: tr = 18
    elif min_elev < 50: tr = 10
    if low_areas > 5: tr = min(30, tr + 8)
    elif low_areas > 2: tr = min(30, tr + 4)

    ts = int(tr * weather_factor)
    if ts > 0:
        factors.append(f"低洼地形(最低{min_elev:.0f}m)")
    score += ts

    # --- 风险点分 × 气象因子 ---
    tunnel_count = len([h for h in hazard_points if "隧道" in h.get("type", "") or "下穿" in h.get("type", "")])
    underground_count = len([h for h in hazard_points if "地下" in h.get("type", "")])
    high_risk = [h for h in hazard_points if h.get("level", "") in ("高风险", "重大")]
    hr = 0
    if len(high_risk) > 3: hr = 20
    elif len(high_risk) > 0: hr = 10
    if tunnel_count > 0: hr = min(30, hr + 10)
    if underground_count > 0: hr = min(30, hr + 5)

    hs = int(hr * weather_factor)
    if hs > 0 and tunnel_count > 0:
        factors.append(f"{tunnel_count}处隧道/下穿通道")
    score += hs

    # --- 复合效应加分（专家经验）---
    # 高峰期 + 暴雨 = 隧道困人风险翻倍
    if time_ctx["is_rush_hour"] and rain_1h >= 20 and tunnel_count > 0:
        score = min(100, score + 8)
        factors.append("高峰期隧道车流密集")
    # 夜间 + 暴雨 = 预警传达困难
    if time_ctx["is_night"] and rain_24h >= 50:
        score = min(100, score + 5)
        factors.append("夜间预警传达困难")
    # 沿河 + 大雨 = 洪水叠加
    if terrain_data.get("是否沿河", False) and rain_24h >= 40:
        score = min(100, score + 6)
        factors.append("沿河区域洪水叠加")
    # 汛期本底风险高
    if time_ctx["is_flood_season"] and rain_24h >= 30:
        score = min(100, score + 3)

    score = min(100, score)
    return score, factors


def _calc_weather_factor(rain_24h, rain_1h, warning_level, forecast_rain_6h):
    """气象强度因子 0.0~1.0"""
    if rain_24h >= 100: f = 1.0
    elif rain_24h >= 50: f = 0.7 + (rain_24h - 50) / 50 * 0.3
    elif rain_24h >= 25: f = 0.4 + (rain_24h - 25) / 25 * 0.3
    elif rain_24h >= 10: f = 0.15 + (rain_24h - 10) / 15 * 0.25
    elif rain_24h > 0: f = rain_24h / 10 * 0.15
    else: f = 0.0

    if rain_1h >= 30: f = min(1.0, f + 0.2)
    elif rain_1h >= 15: f = min(1.0, f + 0.1)

    if warning_level >= 4: f = max(f, 0.8)
    elif warning_level >= 3: f = max(f, 0.6)
    elif warning_level >= 2: f = max(f, 0.3)

    if forecast_rain_6h >= 50: f = max(f, 0.5)
    elif forecast_rain_6h >= 25: f = max(f, 0.3)

    return f


# ==================== 风险识别 ====================

def _identify_main_risks(rain_24h, rain_1h, min_elevation, tunnel_count,
                         underground_count, hazard_points, terrain_data,
                         has_forecast_rain, rain_pattern):
    """识别主要风险类型 - 用专业术语"""
    risks = []

    # 城市内涝（最常见的三防灾害）
    if rain_1h >= 30 and min_elevation < 50:
        risks.append("城市内涝（短时强降雨型）")
    elif rain_24h > 50 and min_elevation < 50:
        risks.append("城市内涝（持续暴雨型）")
    elif rain_24h > 25 and min_elevation < 30:
        risks.append("低洼区域积水")

    # 河道洪水
    if rain_24h > 40 and terrain_data.get("是否沿河", False):
        if rain_24h >= 80:
            risks.append("河道洪水（超警戒风险）")
        else:
            risks.append("河道水位上涨")

    # 隧道/地下空间
    if rain_24h > 15 and tunnel_count > 0:
        risks.append("隧道/下穿通道倒灌")
    if rain_24h > 20 and underground_count > 0:
        risks.append("地下空间进水")

    # 地质灾害
    slope_count = len([h for h in hazard_points if any(k in h.get("type", "") for k in ("边坡", "山体", "滑坡"))])
    if rain_24h > 50 and slope_count > 0:
        risks.append("边坡滑坡/崩塌")

    # 危房
    if rain_24h > 50 and any("危房" in h.get("type", "") for h in hazard_points):
        risks.append("危旧房屋安全")

    # 预报风险
    if not risks and has_forecast_rain:
        risks.append("预报有较强降雨")

    return risks


# ==================== 危险点排名 ====================

def _rank_hazard_points(hazard_points, rain_24h, rain_1h, weather_factor, risk_score):
    """专家级风险点排名 - 基于灾害机理"""
    if not hazard_points or risk_score < 10:
        return []

    scored = []
    for h in hazard_points:
        hc = dict(h)
        ht = hc.get("type", "")
        elev = hc.get("elevation", 100)
        has_history = hc.get("历史淹水", False)

        analysis = _expert_hazard_analysis(ht, elev, rain_24h, rain_1h, has_history)
        hc["risk_score"] = int(analysis["priority"] * weather_factor)
        hc["_action"] = analysis["action"]
        hc["_mechanism"] = analysis["mechanism"]
        scored.append(hc)

    scored.sort(key=lambda x: x["risk_score"], reverse=True)
    return [
        {"排名": i+1, "名称": h["name"], "类型": h["type"],
         "风险分": h["risk_score"], "位置": h.get("location", ""),
         "处置建议": h["_action"]}
        for i, h in enumerate(scored[:5]) if h["risk_score"] > 0
    ]


# ==================== 淹没预判 ====================

def _predict_flood(rain_24h, rain_1h, min_elevation, terrain_data, rain_pattern):
    """淹没预判 - 基于地形和降雨模式"""
    if rain_24h < 10:
        return {}

    flood = {}

    # 短时强降雨：积水快但消退也快
    if rain_pattern["type"] == "flash":
        flood = {
            "可能淹没面积": terrain_data.get("可能淹没面积", "主要道路低洼段"),
            "最大积水深度": "0.5-1.0米（短时极值更高）",
            "灾害持续时间": "1-3小时（雨停后逐步消退）",
            "特征": "来得快退得快，但瞬间积水深度大，车辆最易被困"
        }
    elif rain_24h >= 100:
        flood = {
            "可能淹没面积": terrain_data.get("可能淹没面积", "3.0km2以上"),
            "最大积水深度": "1.5-2.5米",
            "灾害持续时间": "12-24小时",
            "特征": "大范围持续积水，排水系统超负荷，低洼区长时间浸泡"
        }
    elif rain_24h >= 50:
        area = "1.5-2.0km2" if min_elevation < 20 else "0.8-1.5km2"
        flood = {
            "可能淹没面积": terrain_data.get("可能淹没面积", area),
            "最大积水深度": "0.8-1.5米",
            "灾害持续时间": "6-12小时",
            "特征": "低洼区域严重积水，隧道桥洞高危"
        }
    elif rain_24h >= 25:
        flood = {
            "可能淹没面积": f"{max(0.1, (rain_24h-25)/25*0.8):.1f}km2",
            "最大积水深度": "0.3-0.8米",
            "灾害持续时间": "3-6小时",
        }
    elif rain_24h >= 10:
        flood = {
            "可能淹没面积": "局部低洼点",
            "最大积水深度": "0.1-0.3米",
            "灾害持续时间": "1-3小时",
        }

    return flood


# ==================== 专家级指挥建议 ====================

def _build_expert_suggestions(risk_score, risk_level, response_level,
                               rain_24h, rain_1h, warning_level,
                               forecast, forecast_rain_6h,
                               min_elevation, top5, tunnel_count,
                               underground_count, hazard_points,
                               time_ctx, rain_pattern, flood, terrain_data):
    """
    专家级指挥建议 - 核心原则：
    1. 先救人后救物
    2. 具体到人、到点、到动作
    3. 考虑时间和人群因素
    4. 给出优先级排序
    """
    s = []
    hour = time_ctx["hour"]

    # ====== 低风险/无风险：简洁 ======
    if risk_score < 10:
        if forecast_rain_6h >= 25:
            s.append(f"未来6小时预计{forecast_rain_6h:.0f}mm降雨，趁现在没下大：")
            s.append("  - 排查各低洼点排水口有无堵塞，特别是落叶垃圾堵的")
            s.append("  - 隧道口挡水板就位，地下车库检查排水泵")
            if time_ctx["is_night"]:
                s.append("  - 夜班值守人员不要离岗，手机保持畅通")
        elif forecast and forecast not in ("--", "", "晴", "多云"):
            s.append(f"预报有{forecast}，暂时没事，留意气象台后续消息")
        else:
            s.append("目前天气平稳，正常值班就好")
        return s

    # ====== 极高风险（>=70）：分秒必争，先后顺序清晰 ======
    if risk_score >= 70:
        s.append(f"【第一优先】立即启动{response_level}")

        # 人命关天的事排第一
        if time_ctx["is_night"]:
            s.append("深夜暴雨最危险，居民在睡觉不知道外面情况。社区干部、网格员马上挨家挨户敲门通知低洼区住户转移到高处，用大喇叭喊、用手机群发")
        elif time_ctx["is_rush_hour"]:
            s.append(f"现在是{time_ctx['period_name']}，路上大量车辆和行人。交警部门立即在易涝路段设卡分流，广播电台播报绕行路线，导航平台推送积水预警")
        elif time_ctx["is_school_time"]:
            s.append("现在是上下学时段，立即通知辖区学校启动防汛预案，低年级学生留校等雨小再接，校门口安排人值守")
        else:
            s.append("低洼区域居民马上组织转移，老人小孩行动不便的优先安排人背出来，别等水涨上来再跑")

        # 危险点封控
        if top5:
            s.append(f"【第二优先】危险点位封控")
            for p in top5[:3]:
                action = p.get("处置建议", "")
                if action:
                    s.append(f"  {p['名称']}（{p['类型']}）：{action}")
                else:
                    s.append(f"  {p['名称']}：拉警戒线封闭，严禁人车进入")

        # 隧道是最致命的
        if tunnel_count > 0:
            tunnels = [p['名称'] for p in top5 if '隧道' in p.get('类型', '') or '下穿' in p.get('类型', '')]
            if tunnels:
                s.append(f"【特别注意】{'、'.join(tunnels[:3])}等隧道是致命陷阱，积水30cm小轿车就熄火，60cm人就站不稳。入口必须有人拦，不能只放锥桶——有人会搬开闯进去")

        # 地下空间
        if underground_count > 0:
            s.append("地下车库、地下商场立即广播疏散，沙袋封堵入口坡道。重点：先疏散人，车能挪就挪，挪不了就算了，人命比车重要")

        # 抢险力量部署
        s.append(f"【第三优先】抢险力量前置")
        s.append("抢险队带水泵、沙袋、救生衣到最危险的3个点待命。消防救援力量预置在隧道和低洼居民区附近")

        # 降雨趋势判断
        if rain_pattern["intensifying"]:
            s.append(f"【趋势预判】未来6小时还有{forecast_rain_6h:.0f}mm降雨，雨势还在加强，做好长时间作战准备，安排人员轮换和物资补给")
        elif rain_pattern["peak_passed"]:
            s.append("【趋势预判】降雨峰值可能已过，但积水消退需要时间，封控不能放松，防止退水期群众提前返回")

        # 通信
        if warning_level >= 3:
            s.append("通过应急广播、手机短信、微信群、村村通大喇叭等所有渠道发布避险通知，确保每个人都收到")

    # ====== 高风险（50-69）：积极应对，重点突出 ======
    elif risk_score >= 50:
        s.append(f"建议启动{response_level}，以下几个地方最容易出事，必须盯死：")

        if top5:
            for p in top5[:4]:
                action = p.get("处置建议", "安排巡查")
                s.append(f"  {p['名称']}（{p['类型']}）：{action}")

        if rain_1h >= 20:
            s.append(f"当前小时雨量{rain_1h:.0f}mm，城市排水管网设计标准一般是每小时30-50mm，再下大点就顶不住了")

        if rain_24h >= 50 and min_elevation < 25:
            s.append(f"区域最低点海拔{min_elevation:.0f}米，在这个雨量下积水是必然的，排涝泵站提前满负荷运转")

        # 时间敏感建议
        if time_ctx["is_rush_hour"]:
            s.append("正值高峰期，提前在易涝路段设置绕行标志和交通引导，避免车辆误入积水路段")
        if time_ctx["is_night"]:
            s.append("夜间视线差，积水路段没有灯光很难看出深浅，设置反光警示标志和闪灯")

        if forecast_rain_6h >= 30:
            s.append(f"后续还有{forecast_rain_6h:.0f}mm降雨，现在的情况会继续恶化，提前做好升级到I级响应的准备")

        if terrain_data.get("是否沿河", False) and rain_24h >= 40:
            s.append("沿河区域要双线作战：既防河道漫堤，又防内涝倒灌，排涝口的逆止阀检查一遍")

    # ====== 中风险（30-49）：积极防备 ======
    elif risk_score >= 30:
        s.append(f"进入{response_level}状态，各责任人到岗到位")

        if top5:
            names = '、'.join([p['名称'] for p in top5[:3]])
            s.append(f"重点巡查{names}，每{'2' if rain_24h < 40 else '1'}小时报告一次情况")

        if rain_24h >= 25:
            s.append("各排水泵站确认正常运行，易涝点提前放置警示标志和临时排水设备")

        if tunnel_count > 0:
            s.append("隧道口挡水板就位，水位标尺确认可读，安排人随时准备封路")

        if underground_count > 0:
            s.append("通知地下空间物业做好防水准备，沙袋挡水板备在入口")

        if forecast_rain_6h >= 25:
            s.append(f"后续还有{forecast_rain_6h:.0f}mm降雨，雨势如果加大随时准备升级响应")
        elif rain_24h >= 10 and rain_1h < 5:
            s.append("目前雨势减弱，但累计雨量不小，土壤已经饱和，继续关注")

        # 物资准备建议
        if rain_24h >= 30:
            s.append("沙袋、水泵、发电机等应急物资检查并前置到重点街道仓库，别等用的时候再找")

    # ====== 低风险（10-29）：关注为主 ======
    elif risk_score >= 10:
        if rain_24h > 0:
            s.append(f"累计降雨{rain_24h:.0f}mm，暂时问题不大")
        if forecast_rain_6h >= 25:
            s.append(f"但未来6小时预报还有{forecast_rain_6h:.0f}mm，不能大意：")
            s.append("  - 值班人员不离岗，手机畅通")
            s.append("  - 排水口巡查一遍，确保畅通")
            if tunnel_count > 0:
                s.append("  - 隧道口封路设备确认到位")
        else:
            forecast_text = forecast if forecast and forecast not in ("--", "") else ""
            if forecast_text:
                s.append(f"预报{forecast_text}，持续关注气象台最新动态")
            else:
                s.append("保持常规值班巡查")

        if min_elevation < 25:
            s.append("低洼点排水设施提前检查一遍，有堵的赶紧清")

    return s


# ==================== 领导汇报 ====================

def _build_leader_report(risk_score, risk_level, response_level,
                         rain_24h, main_risks, top5,
                         min_elevation, flood, forecast, time_ctx):
    """领导汇报 - 简洁但信息量大"""
    now_str = datetime.now().strftime("%H:%M")

    if risk_score >= 70:
        risk_str = '、'.join(main_risks[:2]) if main_risks else "城市内涝"
        parts = [f"报告（{now_str}）：24小时降雨{rain_24h:.0f}mm，综合风险{risk_score}分（{risk_level}），已启动{response_level}。"]
        parts.append(f"主要风险：{risk_str}。")
        if top5:
            names = '、'.join([p['名称'] for p in top5[:3]])
            parts.append(f"{names}等{len(top5)}处高危点位已实施封控。")
        if flood.get("最大积水深度"):
            parts.append(f"预计最深积水{flood['最大积水深度']}，持续{flood.get('灾害持续时间', '数小时')}。")
        if time_ctx["is_night"]:
            parts.append("夜间作业已加强照明和通知力度。")
        parts.append("各项措施正在落实，将持续跟踪汇报。")
        return ''.join(parts)

    elif risk_score >= 50:
        risk_str = '、'.join(main_risks[:2]) if main_risks else risk_level
        parts = [f"报告（{now_str}）：降雨{rain_24h:.0f}mm，{risk_level}（{risk_score}分），建议{response_level}。"]
        parts.append(f"关注{risk_str}风险。")
        if top5:
            parts.append(f"已对{top5[0]['名称']}等{len(top5)}处重点部位加强管控。")
        if forecast and forecast not in ("--", ""):
            parts.append(f"后续预报{forecast}，将持续研判。")
        return ''.join(parts)

    elif risk_score >= 30:
        risk_str = '和'.join(main_risks[:2]) if main_risks else risk_level
        parts = [f"报告（{now_str}）：降雨{rain_24h:.0f}mm，{risk_level}（{risk_score}分），已进入{response_level}。"]
        parts.append(f"关注{risk_str}。")
        if top5:
            parts.append(f"重点巡查{top5[0]['名称']}等点位。")
        parts.append("目前总体可控。")
        return ''.join(parts)

    elif risk_score >= 10:
        return f"报告（{now_str}）：降雨{rain_24h:.1f}mm，{risk_level}，{response_level}状态，各岗位正常值守，目前可控。"
    else:
        if forecast and forecast not in ("--", ""):
            return f"报告（{now_str}）：当前无明显降雨，预报{forecast}，保持关注，暂无需响应。"
        return f"报告（{now_str}）：天气平稳，一切正常。"


# ==================== 简报生成 ====================

def generate_report(judge_result: Dict) -> str:
    """根据研判结果生成简报文本"""
    ri = judge_result.get("1_综合风险等级", {})
    risks = judge_result.get("2_主要风险类型", [])
    top5 = judge_result.get("3_Top5危险点位", [])
    flood = judge_result.get("4_淹没预判", {})
    suggestions = judge_result.get("5_指挥建议", [])
    leader = judge_result.get("6_领导汇报", "")
    time_str = judge_result.get("研判时间", "")

    lines = []
    lines.append("三防形势智能研判简报")
    lines.append(f"时间：{time_str}")
    lines.append("")
    lines.append(f"综合风险：{ri.get('等级', '?')}（{ri.get('得分', '?')}）{ri.get('响应等级', '')}")

    factors = ri.get('风险因子', [])
    if factors:
        lines.append(f"风险因子：{'、'.join(factors)}")
    if risks:
        lines.append(f"风险类型：{'、'.join(risks)}")
    if top5:
        lines.append("")
        lines.append("重点危险点位：")
        for p in top5:
            line = f"  {p['排名']}. {p['名称']}（{p['类型']}）{p['风险分']}分"
            if p.get('处置建议'):
                line += f" - {p['处置建议']}"
            lines.append(line)
    if flood:
        lines.append("")
        parts = []
        if flood.get('可能淹没面积'): parts.append(f"面积{flood['可能淹没面积']}")
        if flood.get('最大积水深度'): parts.append(f"深度{flood['最大积水深度']}")
        if flood.get('灾害持续时间'): parts.append(f"持续{flood['灾害持续时间']}")
        lines.append(f"淹没预判：{' '.join(parts)}")
        if flood.get('特征'):
            lines.append(f"  特征：{flood['特征']}")
    if suggestions:
        lines.append("")
        lines.append("指挥建议：")
        for i, s_line in enumerate(suggestions, 1):
            lines.append(f"  {i}. {s_line}")
    if leader:
        lines.append("")
        lines.append(f"汇报：{leader}")

    return "\n".join(lines)


def ai_comprehensive_judge_v2(weather_data, terrain_data, hazard_points, mode="hybrid"):
    """v2版本入口"""
    return ai_comprehensive_judge(weather_data, terrain_data, hazard_points)
