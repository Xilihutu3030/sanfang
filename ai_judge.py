# -*- coding: utf-8 -*-
"""
三防系统 - AI智能研判模块（应急管理专家版）
设计理念：像一个干了20年的应急管理老手一样思考
- 看天、看地、看人、看时间，综合判断
- 建议具体到"谁去做、做什么、怎么做、先做哪个"
- 不同场景完全不同的应对策略，绝不套模板
"""

import json
import math
import traceback
import logging as _logging
from datetime import datetime
from typing import Dict, List

import requests

_logger = _logging.getLogger('sanfang.ai_judge')


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

    _safe_log(f"[judge] {risk_level} {risk_score}pts | rain={rain_24h}mm warn={warning_level} | "
          f"hazards={len(hazard_points)} top5={len(top5)}")

    # ========== 高级分析（付费功能）==========
    premium = _build_premium_analysis(
        risk_score, risk_level, response_level,
        rain_24h, rain_1h, warning_level, forecast_rain_6h,
        min_elevation, top5, main_risks, hazard_points,
        time_ctx, rain_pattern, flood, terrain_data, suggestions
    )
    result["_premium"] = premium

    return result


# ==================== 高级分析（付费功能）====================

def _build_premium_analysis(risk_score, risk_level, response_level,
                            rain_24h, rain_1h, warning_level, forecast_rain_6h,
                            min_elevation, top5, main_risks, hazard_points,
                            time_ctx, rain_pattern, flood, terrain_data, suggestions):
    """构建高级付费分析数据"""
    premium = {}

    # 1. 风险趋势预测
    trend_points = _predict_risk_trend(
        risk_score, rain_24h, rain_1h, forecast_rain_6h, rain_pattern, time_ctx)
    premium["risk_trend"] = {
        "title": "风险趋势预测", "desc": "基于当前气象数据和降雨模式预测未来24小时风险走势",
        "points": trend_points, "peak_time": "", "peak_score": 0, "trend_desc": "",
    }
    if trend_points:
        peak = max(trend_points, key=lambda p: p["score"])
        premium["risk_trend"]["peak_time"] = peak["label"]
        premium["risk_trend"]["peak_score"] = peak["score"]
        scores = [p["score"] for p in trend_points]
        if scores[-1] > scores[0] + 10:
            premium["risk_trend"]["trend_desc"] = "风险持续上升，需高度警惕"
        elif scores[-1] < scores[0] - 10:
            premium["risk_trend"]["trend_desc"] = "风险逐步回落，但仍需保持关注"
        else:
            peak_idx = scores.index(max(scores))
            if 0 < peak_idx < len(scores) - 1:
                premium["risk_trend"]["trend_desc"] = f"预计{trend_points[peak_idx]['label']}达到峰值后逐步回落"
            else:
                premium["risk_trend"]["trend_desc"] = "风险保持相对稳定"

    # 2. 分级响应方案
    premium["response_plan"] = _build_response_plan(risk_score, risk_level, response_level, main_risks, top5, time_ctx)
    # 3. 应急处置时间轴
    premium["timeline"] = _build_action_timeline(risk_score, risk_level, rain_24h, rain_1h, forecast_rain_6h, top5, main_risks, time_ctx, rain_pattern)
    # 4. 复合灾害分析
    premium["compound_risk"] = _analyze_compound_risk(rain_24h, rain_1h, warning_level, forecast_rain_6h, min_elevation, main_risks, terrain_data, time_ctx)
    # 5. 人员转移方案（中风险以上）
    if risk_score >= 40:
        premium["evacuation"] = _build_evacuation_plan(risk_score, top5, hazard_points, flood, time_ctx)

    return premium


def _predict_risk_trend(risk_score, rain_24h, rain_1h, forecast_rain_6h, rain_pattern, time_ctx):
    """预测未来24小时风险趋势"""
    from datetime import timedelta
    now = datetime.now()
    points = []
    base = risk_score
    for i in range(9):
        hours_ahead = i * 3
        future_time = now + timedelta(hours=hours_ahead)
        label = future_time.strftime("%H:%M")
        hour = future_time.hour
        if i == 0:
            score = base
        else:
            score = base
            if rain_pattern.get("intensifying"):
                score += forecast_rain_6h * 0.3 * (min(hours_ahead, 6) / 6) if hours_ahead <= 6 else forecast_rain_6h * 0.3 * max(0, 1 - (hours_ahead - 6) / 18)
            elif rain_pattern.get("peak_passed"):
                score -= hours_ahead * 3
            elif forecast_rain_6h > 20:
                score += forecast_rain_6h * 0.2 if hours_ahead <= 6 else -(hours_ahead - 6) * 2
            else:
                score -= hours_ahead * 1.5
            if 0 <= hour < 5: score += 8
            elif 22 <= hour: score += 5
            elif 7 <= hour <= 9 or 17 <= hour <= 19: score += 3
            score = max(0, min(100, round(score)))
        level = "极高" if score >= 70 else "高" if score >= 50 else "中" if score >= 30 else "低"
        color = "#dc2626" if score >= 70 else "#f59e0b" if score >= 50 else "#eab308" if score >= 30 else "#3b82f6"
        points.append({"time": hours_ahead, "label": label, "score": score, "level": level, "color": color})
    return points


def _build_response_plan(risk_score, risk_level, response_level, main_risks, top5, time_ctx):
    """构建分级响应方案"""
    plan = {"title": "分级响应方案", "current_level": response_level,
            "departments": [], "upgrade_condition": "", "downgrade_condition": ""}
    if risk_score >= 70:
        plan["departments"] = [
            {"name": "应急指挥中心", "duty": "全员到岗，启动联合指挥", "priority": "立即"},
            {"name": "消防救援", "duty": "前置驻防高危点位，备勤冲锋舟/排涝车", "priority": "立即"},
            {"name": "水务部门", "duty": "全开排涝泵站，每30分钟报告水位", "priority": "立即"},
            {"name": "交通部门", "duty": "封闭隧道/下穿通道，发布交通管制", "priority": "立即"},
            {"name": "公安部门", "duty": "交通疏导，危险区域警戒封控", "priority": "立即"},
            {"name": "住建部门", "duty": "巡查危房/边坡，组织人员撤离", "priority": "1小时内"},
            {"name": "民政部门", "duty": "开放避护场所，准备救灾物资", "priority": "1小时内"},
            {"name": "宣传部门", "duty": "发布预警信息，引导市民避险", "priority": "立即"},
            {"name": "街道/社区", "duty": "逐户通知低洼区居民，组织转移", "priority": "立即"},
            {"name": "医疗卫生", "duty": "急救力量待命，开放绿色通道", "priority": "30分钟内"},
        ]
        plan["upgrade_condition"] = "若水位持续上涨或出现人员被困，立即请求上级增援"
        plan["downgrade_condition"] = "降雨停止2小时且水位明显回落后可考虑降级"
    elif risk_score >= 50:
        plan["departments"] = [
            {"name": "应急指挥中心", "duty": "值班领导到岗，启动会商", "priority": "立即"},
            {"name": "消防救援", "duty": "备勤排涝装备，待命出动", "priority": "30分钟内"},
            {"name": "水务部门", "duty": "启动排涝泵站，加密水位监测", "priority": "立即"},
            {"name": "交通部门", "duty": "巡查易涝路段，准备交通管制", "priority": "1小时内"},
            {"name": "住建部门", "duty": "重点巡查危房和边坡隐患点", "priority": "1小时内"},
            {"name": "街道/社区", "duty": "通知低洼区居民做好转移准备", "priority": "1小时内"},
        ]
        plan["upgrade_condition"] = "小时雨量超50mm或积水深度超0.3m，升级为I级响应"
        plan["downgrade_condition"] = "雨量减弱至小雨且无新增积水点"
    elif risk_score >= 30:
        plan["departments"] = [
            {"name": "应急指挥中心", "duty": "加强值班值守，密切关注气象", "priority": "持续"},
            {"name": "水务部门", "duty": "检查排水设施，预开泵站", "priority": "2小时内"},
            {"name": "交通部门", "duty": "关注易涝路段通行情况", "priority": "2小时内"},
            {"name": "街道/社区", "duty": "加强巡查，做好预防准备", "priority": "2小时内"},
        ]
        plan["upgrade_condition"] = "小时雨量超30mm或发布橙色以上预警，升级为II级响应"
        plan["downgrade_condition"] = "降雨停止且无积水"
    else:
        plan["departments"] = [
            {"name": "应急指挥中心", "duty": "正常值班，关注气象预报", "priority": "持续"},
            {"name": "各部门", "duty": "做好日常防汛准备工作", "priority": "日常"},
        ]
        plan["upgrade_condition"] = "发布暴雨黄色以上预警信号时升级"
    return plan


def _build_action_timeline(risk_score, risk_level, rain_24h, rain_1h, forecast_rain_6h, top5, main_risks, time_ctx, rain_pattern):
    """构建应急处置时间轴"""
    from datetime import timedelta
    now = datetime.now()
    actions = []
    def _add(minutes, action, dept, urgency="normal"):
        t = now + timedelta(minutes=minutes)
        actions.append({"time": t.strftime("%H:%M"), "minutes_from_now": minutes, "action": action, "department": dept, "urgency": urgency})

    if risk_score >= 50:
        _add(0, "启动应急响应，发布研判通报", "指挥中心", "critical")
        _add(5, "向各成员单位发送响应指令", "指挥中心", "critical")
        _add(10, "启动排涝泵站、打开排水阀", "水务部门", "critical")
        for i, h in enumerate(top5[:3]):
            nm, ht = h.get("名称", ""), h.get("类型", "")
            if "隧道" in ht or "下穿" in ht:
                _add(10 + i * 5, f"封闭{nm}，设置警示标志", "交通/公安", "critical")
            elif "河道" in ht:
                _add(15 + i * 5, f"加密{nm}水位监测，每30分钟上报", "水务部门", "high")
            elif "地下" in ht:
                _add(15 + i * 5, f"通知{nm}周边业主转移车辆，沙袋封堵", "街道/物业", "high")
            elif "危房" in ht:
                _add(10 + i * 5, f"组织{nm}住户撤离，拉警戒线", "住建/社区", "critical")
            elif "边坡" in ht:
                _add(15 + i * 5, f"封闭{nm}周边道路，禁止通行", "住建/交通", "high")
        _add(30, "各责任单位报告到位情况", "各单位", "high")
        _add(60, "第一次态势评估，研判是否升级响应", "指挥中心", "high")
        if rain_pattern.get("intensifying"):
            _add(90, "雨势增强预警，检查各点位防护措施", "各单位", "high")
        _add(180, "态势跟踪研判，评估是否降级或持续", "指挥中心", "normal")
        if risk_score >= 70:
            _add(15, "开放应急避护场所", "民政部门", "critical")
            _add(20, "组织低洼区居民转移", "街道/社区", "critical")
            _add(30, "急救力量前置部署", "卫健部门", "high")
            _add(240, "开展受灾情况统计", "各单位", "normal")
    elif risk_score >= 30:
        _add(0, "加强值班值守，发布防汛提示", "指挥中心", "high")
        _add(30, "巡查重点隐患点位", "各责任单位", "normal")
        _add(60, "检查排水设施运行状态", "水务部门", "normal")
        _add(120, "研判态势变化，决定是否升级", "指挥中心", "normal")
    else:
        _add(0, "关注气象预报变化", "指挥中心", "normal")
        _add(60, "各单位做好防汛准备检查", "各单位", "normal")
    actions.sort(key=lambda a: a["minutes_from_now"])
    return {"title": "应急处置时间轴", "desc": f"基于当前{risk_level}态势生成的行动指南", "actions": actions}


def _analyze_compound_risk(rain_24h, rain_1h, warning_level, forecast_rain_6h, min_elevation, main_risks, terrain_data, time_ctx):
    """复合灾害风险分析"""
    compounds = []
    if rain_24h >= 30 and min_elevation < 20:
        compounds.append({"type": "暴雨+低洼地形", "result": "城市内涝", "probability": "高" if rain_24h >= 50 else "中", "severity": "严重" if min_elevation < 10 else "中等", "detail": f"24小时降雨{rain_24h}mm叠加最低高程{min_elevation}m，排水系统超负荷运行"})
    if rain_1h >= 20 and time_ctx.get("is_rush_hour"):
        compounds.append({"type": "暴雨+早晚高峰", "result": "交通瘫痪", "probability": "高", "severity": "严重", "detail": f"小时雨量{rain_1h}mm遇早晚高峰，隧道桥洞车流密集"})
    if rain_24h >= 80:
        compounds.append({"type": "持续强降雨+山体边坡", "result": "地质灾害（滑坡、崩塌）", "probability": "高" if rain_24h >= 120 else "中", "severity": "极严重", "detail": f"累计雨量{rain_24h}mm，土壤含水量接近饱和，边坡失稳风险显著增大"})
    if rain_24h >= 30 and time_ctx.get("is_night"):
        compounds.append({"type": "暴雨+夜间", "result": "预警响应困难", "probability": "高", "severity": "中等", "detail": "夜间能见度低，居民多已入睡，预警信息传达和人员转移难度大幅增加"})
    if rain_24h >= 40 and min_elevation < 10:
        compounds.append({"type": "强降雨+潮位顶托", "result": "排水受阻加剧内涝", "probability": "中", "severity": "严重", "detail": f"珠江潮位顶托导致城区排水不畅，低洼区（高程{min_elevation}m）积水消退极慢"})
    if rain_1h >= 40:
        compounds.append({"type": "极端短时暴雨", "result": "排水系统瞬间超载", "probability": "极高", "severity": "极严重", "detail": f"小时雨量{rain_1h}mm远超排水管网设计标准（20-30mm/h），全域大面积积水"})
    if rain_24h >= 50 and forecast_rain_6h >= 20:
        compounds.append({"type": "持续降雨+后续雨量", "result": "灾害持续加重", "probability": "高", "severity": "严重", "detail": f"已降雨{rain_24h}mm，预报未来6h还有{forecast_rain_6h}mm，累积效应将进一步放大风险"})
    if not compounds:
        compounds.append({"type": "单一灾害", "result": "暂无明显复合效应", "probability": "低", "severity": "轻微", "detail": "当前气象条件未形成多灾种叠加，但需保持监测"})
    return {"title": "复合灾害分析", "desc": "多种灾害因素叠加可能产生的放大效应", "risks": compounds}


def _build_evacuation_plan(risk_score, top5, hazard_points, flood, time_ctx):
    """构建人员转移方案"""
    areas = []
    type_map = {
        "隧道": ("过境车辆及行人", "交通管制+电子屏提示+人工引导绕行", "临近替代路线"),
        "下穿": ("过境车辆及行人", "交通管制+电子屏提示+人工引导绕行", "临近替代路线"),
        "河道": ("沿河两岸居民", "逐户通知，重点关注老幼病残", "就近避护场所或高处安置点"),
        "地下": ("地下空间人员及车辆", "通知物业广播+逐户敲门+引导转移车辆", "地面安全区域"),
        "危房": ("危房住户", "社区工作人员逐户通知，必要时强制转移", "社区避护点或亲友家"),
        "边坡": ("坡下居民及行人", "封闭周边道路，转移坡下住户", "远离山体的安全区域"),
    }
    default_info = ("低洼区居民", "社区组织有序撤离，老弱优先", "高处安置点或避护场所")
    for h in top5[:5]:
        name, htype, score = h.get("名称", ""), h.get("类型", ""), h.get("风险分", 0)
        if score < 60 and risk_score < 60:
            continue
        info = default_info
        for k, v in type_map.items():
            if k in htype:
                info = v
                break
        high = score >= 80
        urgency_map = {"过境": "立即封闭" if high else "准备封闭", "沿河": "提前转移" if high else "做好准备",
                       "地下": "立即撤离" if high else "准备撤离", "危房": "强制撤离" if high else "劝导撤离",
                       "坡下": "紧急撤离" if high else "撤离准备", "低洼": "有序转移" if high else "通知准备"}
        urgency = "有序转移" if high else "通知准备"
        for k, v in urgency_map.items():
            if k in info[0]:
                urgency = v
                break
        areas.append({"point": name, "type": htype, "risk_score": score,
                      "population": info[0], "urgency": urgency, "method": info[1], "destination": info[2]})

    estimated = sum(200 if any(w in a["urgency"] for w in ("立即", "强制", "紧急")) else 80 if any(w in a["urgency"] for w in ("提前", "有序", "准备")) else 30 for a in areas)
    night_warning = "当前为夜间，转移难度增大，需加强照明和通知力度，安排专人逐户敲门" if time_ctx.get("is_night") else ""
    return {"title": "人员转移方案", "desc": "基于风险评估的人员疏散建议", "areas": areas,
            "estimated_people": estimated, "night_warning": night_warning,
            "key_points": ["老弱病残优先转移", "确保转移路线安全、无积水", "每个转移点安排专人清点人数", "转移后立即反馈到指挥中心"] if areas else []}


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
    lines.append("三防应急处置指挥决策辅助系统研判简报")
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


def generate_response_report(judge_records: List[Dict], region_name: str = "") -> str:
    """
    生成应急响应总结报告
    综合本次应急响应期间所有研判记录，详细讲述响应过程，总结经验教训。
    
    :param judge_records: 按时间顺序排列的所有研判结果列表
    :param region_name: 响应区域名称
    :return: 完整的应急响应报告文本
    """
    if not judge_records:
        return "无研判记录，无法生成应急响应报告。"

    CN_NUMBERS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    section_idx = 0  # 章节计数器

    now_str = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    count = len(judge_records)

    # 提取时间线
    first_time = judge_records[0].get("研判时间", "未知")
    last_time = judge_records[-1].get("研判时间", "未知")

    # 分析风险演变
    risk_timeline = []
    max_score = 0
    max_level = "暂无风险"
    max_response = "日常监控"
    all_risk_types = set()
    all_hazard_names = set()
    all_suggestions = []
    all_factors = set()
    flood_data = {}
    resources_used = {}

    for i, rec in enumerate(judge_records):
        ri = rec.get("1_综合风险等级", {})
        level = ri.get("等级", "暂无风险")
        score_str = ri.get("得分", "0/100")
        try:
            score = int(score_str.split("/")[0])
        except (ValueError, IndexError):
            score = 0

        risk_timeline.append({
            "序号": i + 1,
            "时间": rec.get("研判时间", ""),
            "等级": level,
            "得分": score,
            "响应等级": ri.get("响应等级", ""),
        })

        if score > max_score:
            max_score = score
            max_level = level
            max_response = ri.get("响应等级", "")

        # 收集风险因子
        for f in ri.get("风险因子", []):
            all_factors.add(f)

        # 收集风险类型
        for rt in rec.get("2_主要风险类型", []):
            all_risk_types.add(rt)

        # 收集危险点位
        for hp in rec.get("3_Top5危险点位", []):
            all_hazard_names.add(hp.get("名称", ""))

        # 收集指挥建议
        for s in rec.get("5_指挥建议", []):
            if s not in all_suggestions:
                all_suggestions.append(s)

        # 最后一次的淹没预判
        fd = rec.get("4_淹没预判", {})
        if fd:
            flood_data = fd

        # 收集可调度资源
        res = rec.get("7_可调度资源", {})
        if res:
            resources_used = res

    # 判断风险趋势
    if len(risk_timeline) >= 2:
        first_score = risk_timeline[0]["得分"]
        last_score = risk_timeline[-1]["得分"]
        peak_score = max(rt["得分"] for rt in risk_timeline)
        peak_idx = next(i for i, rt in enumerate(risk_timeline) if rt["得分"] == peak_score)

        # 峰值在中间 → 先升后降
        if len(risk_timeline) >= 3 and 0 < peak_idx < len(risk_timeline) - 1:
            trend = "先升后降"
            trend_desc = (f"风险从{first_score}分升至峰值{peak_score}分后回落至{last_score}分，"
                          f"响应措施有效，态势趋于可控")
        elif last_score > first_score + 10:
            trend = "上升"
            trend_desc = f"风险从{first_score}分升至{last_score}分，态势恶化"
        elif last_score < first_score - 10:
            trend = "下降"
            trend_desc = f"风险从{first_score}分降至{last_score}分，态势好转"
        else:
            trend = "平稳"
            trend_desc = f"风险基本维持在{min(first_score, last_score)}-{max(first_score, last_score)}分区间"
    else:
        trend = "单次研判"
        trend_desc = f"本次响应仅进行了1次研判，风险评分{risk_timeline[0]['得分']}分"

    # 构建报告
    lines = []
    lines.append("=" * 60)
    lines.append("三防应急处置指挥决策辅助系统")
    lines.append("应 急 响 应 总 结 报 告")
    lines.append("=" * 60)
    lines.append("")

    # 一、基本信息
    lines.append("一、基本信息")
    lines.append("-" * 40)
    if region_name:
        lines.append(f"  响应区域：{region_name}")
    lines.append(f"  报告生成时间：{now_str}")
    lines.append(f"  响应时段：{first_time} 至 {last_time}")
    lines.append(f"  研判次数：共{count}次")
    lines.append(f"  最高风险等级：{max_level}（{max_score}/100分）")
    lines.append(f"  最高响应等级：{max_response}")
    lines.append("")

    # 二、响应过程时间线
    lines.append("二、响应过程时间线")
    lines.append("-" * 40)
    for rt in risk_timeline:
        marker = "●" if rt["得分"] >= 50 else "○"
        lines.append(f"  {marker} [{rt['时间']}] 第{rt['序号']}次研判")
        lines.append(f"    风险等级：{rt['等级']}（{rt['得分']}分）{rt['响应等级']}")
    lines.append("")
    lines.append(f"  趋势分析：{trend_desc}")
    lines.append("")

    # 三、风险概况
    lines.append("三、风险概况")
    lines.append("-" * 40)
    if all_factors:
        lines.append(f"  风险因子：{'、'.join(all_factors)}")
    if all_risk_types:
        lines.append(f"  涉及风险类型：{'、'.join(all_risk_types)}")
    if all_hazard_names:
        names = [n for n in all_hazard_names if n]
        if names:
            lines.append(f"  重点监控点位（{len(names)}处）：{'、'.join(names)}")
    lines.append("")

    # 四、淹没预判汇总
    section_idx = 3  # 前三章已写（一二三）
    if flood_data and any(flood_data.values()):
        lines.append(f"{CN_NUMBERS[section_idx]}、淹没预判汇总")
        lines.append("-" * 40)
        if flood_data.get("可能淹没面积"):
            lines.append(f"  可能淹没面积：{flood_data['可能淹没面积']}")
        if flood_data.get("最大积水深度"):
            lines.append(f"  最大积水深度：{flood_data['最大积水深度']}")
        if flood_data.get("灾害持续时间"):
            lines.append(f"  灾害持续时间：{flood_data['灾害持续时间']}")
        if flood_data.get("特征"):
            lines.append(f"  灾害特征：{flood_data['特征']}")
        lines.append("")
        section_idx += 1

    # 指挥建议汇总
    if all_suggestions:
        lines.append(f"{CN_NUMBERS[section_idx]}、指挥建议汇总")
        lines.append("-" * 40)
        for i, s in enumerate(all_suggestions[:15], 1):
            lines.append(f"  {i}. {s}")
        if len(all_suggestions) > 15:
            lines.append(f"  ...（共{len(all_suggestions)}条建议）")
        lines.append("")
        section_idx += 1

    # 隐患排查处置情况
    if all_hazard_names:
        hazard_list = [n for n in all_hazard_names if n]
        if hazard_list:
            lines.append(f"{CN_NUMBERS[section_idx]}、隐患排查与处置")
            lines.append("-" * 40)
            lines.append(f"  本次响应期间共排查风险隐患 {len(hazard_list)} 处：")
            for i, nm in enumerate(hazard_list, 1):
                lines.append(f"    {i}. {nm}")
            risk_type_list = list(all_risk_types)
            if risk_type_list:
                lines.append(f"  涉及风险类型：{'、'.join(risk_type_list)}")
            lines.append(f"  处置措施：已根据研判建议逐一落实巡查、警戒、管控等措施")
            lines.append("")
            section_idx += 1

    # 应急力量调度情况
    if resources_used:
        # 统计各类资源数量
        per_items = resources_used.get("personnel", {}).get("items", []) if isinstance(resources_used.get("personnel"), dict) else []
        veh_items = resources_used.get("vehicles", {}).get("items", []) if isinstance(resources_used.get("vehicles"), dict) else []
        mat_items = resources_used.get("materials", {}).get("items", []) if isinstance(resources_used.get("materials"), dict) else []
        fac_items = resources_used.get("facilities", {}).get("items", []) if isinstance(resources_used.get("facilities"), dict) else []

        total_resources = len(per_items) + len(veh_items) + len(mat_items) + len(fac_items)
        if total_resources > 0:
            lines.append(f"{CN_NUMBERS[section_idx]}、应急力量调度")
            lines.append("-" * 40)

            # 总览
            summary_parts = []
            if per_items:
                # 统计队伍数
                teams = set()
                for p in per_items:
                    t = p.get("team", "")
                    if t:
                        teams.add(t)
                if teams:
                    summary_parts.append(f"出动应急队伍 {len(teams)} 支、人员 {len(per_items)} 人")
                else:
                    summary_parts.append(f"出动应急人员 {len(per_items)} 人")
            if veh_items:
                # 统计车辆类型
                veh_types = {}
                for v in veh_items:
                    vt = v.get("type", "其他")
                    veh_types[vt] = veh_types.get(vt, 0) + 1
                type_strs = [f"{t}{c}辆" for t, c in veh_types.items()]
                summary_parts.append(f"调派车辆 {len(veh_items)} 辆（{'、'.join(type_strs)}）")
            if mat_items:
                summary_parts.append(f"调用物资装备 {len(mat_items)} 类")
            if fac_items:
                summary_parts.append(f"启用应急场所 {len(fac_items)} 处")
            lines.append(f"  {' ，'.join(summary_parts)}。")
            lines.append("")

            # 人员队伍明细
            if per_items:
                lines.append("  【人员队伍】")
                teams_dict = {}
                for p in per_items:
                    t = p.get("team", "其他")
                    if t not in teams_dict:
                        teams_dict[t] = []
                    teams_dict[t].append(p.get("name", ""))
                for team, members in teams_dict.items():
                    lines.append(f"    {team}：{len(members)}人（{'、'.join(members[:5])}" +
                                 (f" 等）" if len(members) > 5 else "）"))

            # 车辆明细
            if veh_items:
                lines.append("  【出动车辆】")
                for v in veh_items[:8]:
                    plate = v.get("plate_number", "")
                    vtype = v.get("type", "")
                    driver = v.get("driver", "")
                    parts = [plate]
                    if vtype:
                        parts.append(vtype)
                    if driver:
                        parts.append(f"驾驶员：{driver}")
                    lines.append(f"    - {'，'.join(parts)}")
                if len(veh_items) > 8:
                    lines.append(f"    ...共{len(veh_items)}辆")

            # 物资装备明细
            if mat_items:
                lines.append("  【物资装备】")
                for m in mat_items[:8]:
                    name = m.get("name", "")
                    qty = m.get("quantity", "")
                    unit = m.get("unit", "")
                    loc = m.get("location", "")
                    line = f"    - {name}"
                    if qty:
                        line += f" {qty}{unit}"
                    if loc:
                        line += f"（{loc}）"
                    lines.append(line)
                if len(mat_items) > 8:
                    lines.append(f"    ...共{len(mat_items)}类物资")

            # 应急场所明细
            if fac_items:
                lines.append("  【启用场所】")
                for f in fac_items[:5]:
                    fname = f.get("name", "")
                    ftype = f.get("type", "")
                    cap = f.get("capacity", "")
                    dist = f.get("distance_km")
                    parts = [fname]
                    if ftype:
                        parts.append(ftype)
                    if cap:
                        parts.append(f"容纳{cap}人")
                    if dist is not None:
                        parts.append(f"距离{dist}km")
                    lines.append(f"    - {'，'.join(parts)}")

            lines.append("")
            section_idx += 1

    # 经验教训与建议
    lines.append(f"{CN_NUMBERS[section_idx]}、经验教训与工作建议")
    lines.append("-" * 40)

    lessons = []
    # 根据实际数据生成有针对性的经验教训
    if max_score >= 70:
        lessons.append("本次响应达到极高风险等级，建议完善极端天气情况下的应急预案，确保各环节响应及时。")
    elif max_score >= 50:
        lessons.append("本次响应达到高风险等级，建议加强重点区域的常态化巡查和隐患排查。")
    elif max_score >= 30:
        lessons.append("本次响应为中等风险，建议持续关注气象变化，做好预防性部署。")

    if "隧道/下穿通道倒灌" in all_risk_types or any("隧道" in n for n in all_hazard_names):
        lessons.append("涉及隧道/下穿通道风险，建议完善隧道积水监测预警设备，确保封闭措施可快速执行。")

    if "城市内涝" in "、".join(all_risk_types):
        lessons.append("存在城市内涝风险，建议检查排水管网运行状态，清理易堵塞节点，提升排涝能力。")

    if len(judge_records) >= 3:
        lessons.append(f"本次响应共进行{count}次研判跟踪，持续研判对掌握态势变化起到重要作用，建议保持动态研判机制。")

    if trend == "上升":
        lessons.append("响应期间风险持续升高，建议提前建立风险等级升级联动机制，在风险上升初期即加大资源投入。")
    elif trend == "下降":
        lessons.append("响应期间风险逐步回落，说明应对措施有效，建议总结有效做法形成标准化流程。")
    elif trend == "先升后降":
        lessons.append("响应期间风险经历了先升后降的过程，说明应急响应及时有效，建议复盘高峰期的应对措施并固化为预案。")

    if not lessons:
        lessons.append("建议定期开展应急演练，提升各部门协同配合能力。")
        lessons.append("建议完善值班值守制度，确保预警信息第一时间传达到位。")

    for i, lesson in enumerate(lessons, 1):
        lines.append(f"  {i}. {lesson}")

    lines.append("")
    lines.append("=" * 60)
    lines.append("本报告由三防应急处置指挥决策辅助系统自动生成")
    lines.append(f"生成时间：{now_str}")
    lines.append("=" * 60)

    return "\n".join(lines)


def ai_comprehensive_judge_v2(weather_data, terrain_data, hazard_points, mode="hybrid"):
    """v2版本入口"""
    return ai_comprehensive_judge(weather_data, terrain_data, hazard_points)


# ==================== AI 智能风险点分析 ====================

# 各区域内置地理知识库 —— 基于真实地理信息的风险点种子数据
# 当AI不可用时作为兜底，同时也作为AI分析的参考基准
REGION_HAZARD_KNOWLEDGE = {
    "黄埔区": {
        "center": [23.1818, 113.4808],
        "hazards": [
            {"name": "大沙地下穿隧道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 6, "location": "黄埔区大沙地东路", "lat": 23.1058, "lng": 113.4548,
             "description": "大沙地东路下穿隧道，地势低洼，暴雨易积水，历史上多次发生淹浸"},
            {"name": "丰乐北路下穿通道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 8, "location": "黄埔区丰乐北路", "lat": 23.1082, "lng": 113.4612,
             "description": "丰乐北路铁路下穿通道，排水能力不足，暴雨时水深可达0.5-1米"},
            {"name": "南岗河黄埔段", "type": "河道", "level": "重大", "历史淹水": False,
             "elevation": 5, "location": "黄埔区南岗河沿线", "lat": 23.0926, "lng": 113.4735,
             "description": "南岗河流经城区段，两岸低洼，洪水期水位上涨快，威胁周边居民区"},
            {"name": "乌涌黄埔段", "type": "河道", "level": "较大", "历史淹水": False,
             "elevation": 3, "location": "黄埔区乌涌沿线", "lat": 23.1145, "lng": 113.4420,
             "description": "乌涌城区段，潮汐影响明显，暴雨叠加天文大潮时排水受阻"},
            {"name": "文冲街旧村低洼区", "type": "易涝点", "level": "较大", "历史淹水": True,
             "elevation": 4, "location": "黄埔区文冲街道", "lat": 23.1002, "lng": 113.4875,
             "description": "文冲旧村地势低于周边道路，暴雨时内涝严重，影响数百户居民"},
            {"name": "鱼珠地铁站周边", "type": "地下空间", "level": "重大", "历史淹水": False,
             "elevation": 7, "location": "黄埔区鱼珠", "lat": 23.1030, "lng": 113.4348,
             "description": "地铁五号线鱼珠站出入口及周边地下商业空间，暴雨倒灌风险高"},
            {"name": "黄埔东路立交桥底", "type": "桥下", "level": "较大", "历史淹水": True,
             "elevation": 9, "location": "黄埔区黄埔东路", "lat": 23.1068, "lng": 113.4680,
             "description": "黄埔东路立交桥底凹陷路段，排水泵站故障时积水可达0.3-0.8米"},
            {"name": "长洲岛沿江低洼带", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 2, "location": "黄埔区长洲岛", "lat": 23.0838, "lng": 113.4250,
             "description": "长洲岛珠江沿岸，洪水期加天文大潮极易漫堤，威胁军校旧址等文保单位"},
            {"name": "科学城开泰大道低洼段", "type": "易涝点", "level": "一般", "历史淹水": True,
             "elevation": 15, "location": "黄埔区科学城", "lat": 23.1625, "lng": 113.4680,
             "description": "开泰大道部分路段地势较低，暴雨时路面积水影响交通"},
            {"name": "永和街凤凰山边坡", "type": "边坡", "level": "较大", "历史淹水": False,
             "elevation": 45, "location": "黄埔区永和街道", "lat": 23.2105, "lng": 113.5120,
             "description": "凤凰山南侧人工边坡，坡度陡峭，暴雨时有滑坡崩塌风险"},
            {"name": "联和街暹岗旧村危房", "type": "危房", "level": "较大", "历史淹水": False,
             "elevation": 22, "location": "黄埔区联和街道暹岗村", "lat": 23.1785, "lng": 113.4538,
             "description": "暹岗旧村部分砖混结构老旧房屋，台风暴雨时存在倒塌风险"},
            {"name": "知识城九龙大道涵洞", "type": "隧道", "level": "一般", "历史淹水": True,
             "elevation": 18, "location": "黄埔区知识城", "lat": 23.3042, "lng": 113.4780,
             "description": "九龙大道铁路涵洞，新建区域排水系统尚在完善中"},
        ]
    },
    "天河区": {
        "center": [23.1248, 113.3613],
        "hazards": [
            {"name": "岗顶BRT隧道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 12, "location": "天河区中山大道岗顶段", "lat": 23.1368, "lng": 113.3488,
             "description": "中山大道岗顶隧道段，暴雨时排水不及，历史上多次严重积水"},
            {"name": "沙河涌棠下段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 8, "location": "天河区棠下", "lat": 23.1350, "lng": 113.3650,
             "description": "沙河涌棠下段河道窄，两岸城中村密集，洪水威胁大"},
            {"name": "猎德涌珠江汇入口", "type": "河道", "level": "较大", "历史淹水": False,
             "elevation": 4, "location": "天河区猎德", "lat": 23.1100, "lng": 113.3280,
             "description": "猎德涌汇入珠江处，受潮汐顶托影响明显"},
            {"name": "石牌东路低洼区", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 15, "location": "天河区石牌东", "lat": 23.1320, "lng": 113.3410,
             "description": "石牌东路地下通道及周边低洼路段，暴雨积水频发"},
            {"name": "暨南花园地下车库", "type": "地下空间", "level": "重大", "历史淹水": True,
             "elevation": 18, "location": "天河区黄埔大道", "lat": 23.1280, "lng": 113.3520,
             "description": "暨南花园地下停车场，暴雨时雨水倒灌风险极高"},
            {"name": "车陂涌天河段", "type": "河道", "level": "较大", "历史淹水": True,
             "elevation": 6, "location": "天河区车陂", "lat": 23.1188, "lng": 113.3880,
             "description": "车陂涌流经密集城区段，暴雨时水位暴涨"},
            {"name": "广州东站下穿通道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 20, "location": "天河区林和西路", "lat": 23.1488, "lng": 113.3248,
             "description": "广州东站南北下穿通道，暴雨时积水严重影响铁路交通"},
            {"name": "龙洞水库下游", "type": "河道", "level": "较大", "历史淹水": False,
             "elevation": 30, "location": "天河区龙洞", "lat": 23.1680, "lng": 113.3720,
             "description": "龙洞水库下游泄洪通道，暴雨时洪水威胁下游居民区"},
            {"name": "天河公园南门低洼区", "type": "易涝点", "level": "一般", "历史淹水": True,
             "elevation": 10, "location": "天河区天河公园", "lat": 23.1258, "lng": 113.3688,
             "description": "天河公园南门及黄埔大道辅道低洼路段"},
            {"name": "珠江新城地下空间群", "type": "地下空间", "level": "重大", "历史淹水": False,
             "elevation": 12, "location": "天河区珠江新城", "lat": 23.1185, "lng": 113.3218,
             "description": "珠江新城大面积地下商业空间及地铁换乘站，洪涝倒灌后果极其严重"},
        ]
    },
    "越秀区": {
        "center": [23.1292, 113.2665],
        "hazards": [
            {"name": "岗贝隧道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 10, "location": "越秀区岗贝路", "lat": 23.1388, "lng": 113.2720,
             "description": "岗贝路下穿隧道，地势低洼排水差，暴雨必淹"},
            {"name": "火车站下穿通道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 12, "location": "越秀区环市西路", "lat": 23.1480, "lng": 113.2560,
             "description": "广州火车站南北下穿通道，客流密集区暴雨积水风险极高"},
            {"name": "广园立交桥底", "type": "桥下", "level": "重大", "历史淹水": True,
             "elevation": 15, "location": "越秀区广园路", "lat": 23.1450, "lng": 113.2780,
             "description": "广园路立交桥底低洼处，每逢暴雨必严重积水"},
            {"name": "大沙头旧楼群", "type": "危房", "level": "重大", "历史淹水": False,
             "elevation": 8, "location": "越秀区大沙头路", "lat": 23.1200, "lng": 113.2800,
             "description": "大沙头路片区老旧房屋群，房龄超50年，台风暴雨倒塌风险高"},
            {"name": "东濠涌越秀段", "type": "河道", "level": "较大", "历史淹水": True,
             "elevation": 6, "location": "越秀区东濠涌", "lat": 23.1308, "lng": 113.2738,
             "description": "东濠涌城区段，暴雨时河水暴涨，沿岸低洼区域易受灾"},
            {"name": "小北路下穿通道", "type": "隧道", "level": "较大", "历史淹水": True,
             "elevation": 14, "location": "越秀区小北路", "lat": 23.1385, "lng": 113.2658,
             "description": "小北路铁路下穿通道，排水能力有限"},
            {"name": "六榕街老旧社区", "type": "危房", "level": "一般", "历史淹水": False,
             "elevation": 18, "location": "越秀区六榕街", "lat": 23.1342, "lng": 113.2608,
             "description": "六榕街片区部分老旧房屋需重点关注"},
        ]
    },
    "白云区": {
        "center": [23.2644, 113.2731],
        "hazards": [
            {"name": "石井河白云段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 5, "location": "白云区石井河沿线", "lat": 23.1828, "lng": 113.2348,
             "description": "石井河流经白云城区段，河道窄洪水位高，两岸内涝频发"},
            {"name": "新市墟低洼片区", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 8, "location": "白云区新市墟", "lat": 23.1810, "lng": 113.2720,
             "description": "新市墟片区地势低洼密集，排水管网老旧，暴雨内涝严重"},
            {"name": "机场路下穿隧道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 12, "location": "白云区机场路", "lat": 23.1920, "lng": 113.2638,
             "description": "机场路铁路下穿隧道，暴雨时积水严重影响交通"},
            {"name": "同和立交桥底", "type": "桥下", "level": "较大", "历史淹水": True,
             "elevation": 20, "location": "白云区广州大道北", "lat": 23.2058, "lng": 113.3078,
             "description": "同和立交桥底凹陷路段积水"},
            {"name": "白云山南麓边坡", "type": "边坡", "level": "较大", "历史淹水": False,
             "elevation": 65, "location": "白云区白云山", "lat": 23.1728, "lng": 113.2988,
             "description": "白云山南麓多处人工切坡建房区域，暴雨滑坡风险高"},
            {"name": "景泰涌白云段", "type": "河道", "level": "较大", "历史淹水": True,
             "elevation": 7, "location": "白云区景泰涌", "lat": 23.1748, "lng": 113.2628,
             "description": "景泰涌流经城中村段，河道被挤占严重"},
            {"name": "永泰地铁站周边", "type": "地下空间", "level": "一般", "历史淹水": False,
             "elevation": 18, "location": "白云区永泰", "lat": 23.2138, "lng": 113.2788,
             "description": "永泰地铁站出入口及地下通道，暴雨倒灌风险"},
        ]
    },
    "番禺区": {
        "center": [22.9370, 113.3843],
        "hazards": [
            {"name": "市桥河番禺段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 2, "location": "番禺区市桥河", "lat": 22.9428, "lng": 113.3648,
             "description": "市桥河穿越城区，地势极低，暴雨叠加潮汐时两岸严重内涝"},
            {"name": "大石涌大石段", "type": "河道", "level": "较大", "历史淹水": True,
             "elevation": 3, "location": "番禺区大石", "lat": 22.9888, "lng": 113.3188,
             "description": "大石涌流经密集城区，排水受珠江潮位顶托影响大"},
            {"name": "大学城南亭村", "type": "易涝点", "level": "较大", "历史淹水": True,
             "elevation": 4, "location": "番禺区大学城", "lat": 23.0408, "lng": 113.3828,
             "description": "南亭村地势低洼，暴雨时村内道路严重积水"},
            {"name": "汉溪长隆地铁站", "type": "地下空间", "level": "重大", "历史淹水": False,
             "elevation": 8, "location": "番禺区汉溪大道", "lat": 22.9988, "lng": 113.3228,
             "description": "汉溪长隆地铁站大型地下换乘空间，暴雨倒灌后果严重"},
            {"name": "洛浦街沿江低洼带", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 2, "location": "番禺区洛浦街", "lat": 23.0188, "lng": 113.3108,
             "description": "洛浦街珠江沿岸地势极低，洪水叠加大潮极易漫堤"},
            {"name": "石碁镇铁路涵洞", "type": "隧道", "level": "较大", "历史淹水": True,
             "elevation": 6, "location": "番禺区石碁镇", "lat": 22.9068, "lng": 113.3938,
             "description": "石碁镇广深铁路涵洞，暴雨积水影响南北交通"},
        ]
    },
    "海珠区": {
        "center": [23.0833, 113.2620],
        "hazards": [
            {"name": "黄埔涌海珠段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 3, "location": "海珠区黄埔涌", "lat": 23.0938, "lng": 113.3258,
             "description": "黄埔涌海珠段，受珠江潮汐影响严重，暴雨时排水极困难"},
            {"name": "赤岗塔地下通道", "type": "地下空间", "level": "重大", "历史淹水": True,
             "elevation": 5, "location": "海珠区赤岗", "lat": 23.0978, "lng": 113.3178,
             "description": "赤岗塔附近地下通道及珠江沿岸低洼区"},
            {"name": "南洲路低洼段", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 3, "location": "海珠区南洲路", "lat": 23.0548, "lng": 113.3068,
             "description": "南洲路近珠江后航道段地势极低，暴雨必涝"},
            {"name": "海珠湿地公园周边", "type": "易涝点", "level": "较大", "历史淹水": False,
             "elevation": 2, "location": "海珠区湿地公园", "lat": 23.0628, "lng": 113.3548,
             "description": "海珠湿地周边地势低洼，洪水期蓄洪压力大"},
            {"name": "客村立交桥底", "type": "桥下", "level": "较大", "历史淹水": True,
             "elevation": 8, "location": "海珠区客村", "lat": 23.0858, "lng": 113.3028,
             "description": "客村立交桥底凹陷路段，暴雨积水影响交通"},
        ]
    },
    "荔湾区": {
        "center": [23.1260, 113.2440],
        "hazards": [
            {"name": "花地涌荔湾段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 3, "location": "荔湾区花地涌", "lat": 23.0808, "lng": 113.2288,
             "description": "花地涌荔湾段河道窄，暴雨时水位暴涨威胁两岸居民"},
            {"name": "芳村下穿隧道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 6, "location": "荔湾区芳村大道", "lat": 23.0748, "lng": 113.2188,
             "description": "芳村大道铁路下穿隧道，暴雨严重积水"},
            {"name": "西关老城危房群", "type": "危房", "level": "重大", "历史淹水": False,
             "elevation": 8, "location": "荔湾区西关", "lat": 23.1228, "lng": 113.2378,
             "description": "西关老城区大量砖木结构老屋，台风暴雨倒塌风险极高"},
            {"name": "坦尾地铁站周边", "type": "地下空间", "level": "较大", "历史淹水": False,
             "elevation": 5, "location": "荔湾区坦尾", "lat": 23.1068, "lng": 113.2368,
             "description": "坦尾地铁站临近珠江，地势低洼，暴雨倒灌风险高"},
            {"name": "大坦沙岛沿江地带", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 2, "location": "荔湾区大坦沙", "lat": 23.1108, "lng": 113.2278,
             "description": "大坦沙岛四面环水，洪水期极易受灾"},
        ]
    },
    "南沙区": {
        "center": [22.8016, 113.5253],
        "hazards": [
            {"name": "万顷沙围垦区", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 1, "location": "南沙区万顷沙", "lat": 22.6618, "lng": 113.5628,
             "description": "万顷沙围垦区地势极低，海平面以下区域，风暴潮威胁极大"},
            {"name": "南沙港区沿海堤段", "type": "易涝点", "level": "重大", "历史淹水": False,
             "elevation": 2, "location": "南沙区南沙港", "lat": 22.7388, "lng": 113.5868,
             "description": "南沙港区海堤段，台风风暴潮直接威胁区域"},
            {"name": "蕉门水道沿岸", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 2, "location": "南沙区蕉门河", "lat": 22.7828, "lng": 113.5228,
             "description": "蕉门水道沿岸地势低，洪水叠加风暴潮时风险极高"},
            {"name": "黄阁镇下穿通道", "type": "隧道", "level": "较大", "历史淹水": True,
             "elevation": 5, "location": "南沙区黄阁镇", "lat": 22.8128, "lng": 113.4728,
             "description": "黄阁镇铁路下穿通道，暴雨积水"},
        ]
    },
    "花都区": {
        "center": [23.4040, 113.2200],
        "hazards": [
            {"name": "花都湖上游河段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 12, "location": "花都区花都湖", "lat": 23.3938, "lng": 113.2158,
             "description": "花都湖上游新街河段，洪水期水位暴涨，威胁周边居民区"},
            {"name": "新华街低洼片区", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 8, "location": "花都区新华街", "lat": 23.3988, "lng": 113.2218,
             "description": "新华街老城区地势低洼，排水管网老旧"},
            {"name": "芙蓉嶂山体边坡", "type": "边坡", "level": "较大", "历史淹水": False,
             "elevation": 120, "location": "花都区芙蓉嶂", "lat": 23.4618, "lng": 113.2508,
             "description": "芙蓉嶂景区周边山体边坡，暴雨滑坡泥石流风险"},
            {"name": "花东镇铁路涵洞", "type": "隧道", "level": "较大", "历史淹水": True,
             "elevation": 15, "location": "花都区花东镇", "lat": 23.4188, "lng": 113.3208,
             "description": "花东镇广深铁路涵洞，暴雨积水"},
            {"name": "秀全街危旧房屋", "type": "危房", "level": "一般", "历史淹水": False,
             "elevation": 18, "location": "花都区秀全街", "lat": 23.4028, "lng": 113.2128,
             "description": "秀全街部分老旧房屋结构安全隐患"},
        ]
    },
    "增城区": {
        "center": [23.2629, 113.8108],
        "hazards": [
            {"name": "增江河城区段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 6, "location": "增城区增江河", "lat": 23.2628, "lng": 113.8108,
             "description": "增江河流经增城城区段，洪水期水位猛涨"},
            {"name": "荔城街低洼区", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 8, "location": "增城区荔城街", "lat": 23.2588, "lng": 113.8148,
             "description": "荔城街老城区地势低洼，暴雨内涝频发"},
            {"name": "新塘镇下穿隧道", "type": "隧道", "level": "重大", "历史淹水": True,
             "elevation": 10, "location": "增城区新塘镇", "lat": 23.1308, "lng": 113.6048,
             "description": "新塘镇铁路下穿隧道积水点"},
            {"name": "派潭镇山洪沟", "type": "河道", "level": "较大", "历史淹水": True,
             "elevation": 35, "location": "增城区派潭镇", "lat": 23.4628, "lng": 113.8508,
             "description": "派潭镇北部山区山洪沟，暴雨山洪风险高"},
            {"name": "正果镇边坡隐患", "type": "边坡", "level": "较大", "历史淹水": False,
             "elevation": 55, "location": "增城区正果镇", "lat": 23.4058, "lng": 113.9108,
             "description": "正果镇山区道路边坡地质灾害隐患点"},
        ]
    },
    "从化区": {
        "center": [23.5489, 113.5862],
        "hazards": [
            {"name": "流溪河从化城区段", "type": "河道", "level": "重大", "历史淹水": True,
             "elevation": 15, "location": "从化区流溪河", "lat": 23.5488, "lng": 113.5858,
             "description": "流溪河穿城而过，洪水期威胁两岸城区"},
            {"name": "街口街低洼片区", "type": "易涝点", "level": "重大", "历史淹水": True,
             "elevation": 12, "location": "从化区街口街", "lat": 23.5518, "lng": 113.5828,
             "description": "街口街道老城区排水系统能力不足"},
            {"name": "良口镇山洪隐患", "type": "河道", "level": "较大", "历史淹水": True,
             "elevation": 50, "location": "从化区良口镇", "lat": 23.6748, "lng": 113.6288,
             "description": "良口镇山区溪流山洪暴发风险"},
            {"name": "温泉镇滑坡隐患点", "type": "边坡", "level": "较大", "历史淹水": False,
             "elevation": 80, "location": "从化区温泉镇", "lat": 23.5078, "lng": 113.6308,
             "description": "温泉镇山体滑坡地质灾害隐患"},
        ]
    },
}


# ==================== OSM 真实地理数据获取 ====================

_osm_cache = {}  # 缓存 OSM 结果，key = "lat,lng,radius"

def _fetch_osm_features(center_lat: float, center_lng: float, radius_km: float = 5) -> list:
    """
    通过 OpenStreetMap Overpass API 获取指定区域内的真实地理要素。
    返回包含名称、类型、坐标的要素列表，用于AI风险分析。
    """
    cache_key = f"{center_lat:.2f},{center_lng:.2f},{radius_km:.0f}"
    if cache_key in _osm_cache:
        return _osm_cache[cache_key]

    lat_offset = radius_km / 111.0
    lng_offset = radius_km / (111.0 * abs(math.cos(math.radians(center_lat))))
    south = center_lat - lat_offset
    north = center_lat + lat_offset
    west = center_lng - lng_offset
    east = center_lng + lng_offset
    bbox = f"{south:.4f},{west:.4f},{north:.4f},{east:.4f}"

    query = f"""
[out:json][timeout:20];
(
  way["tunnel"="yes"]({bbox});
  way["bridge"="yes"]({bbox});
  way["waterway"]({bbox});
  relation["waterway"]({bbox});
  node["railway"="subway_entrance"]({bbox});
  way["parking"="underground"]({bbox});
  node["parking"="underground"]({bbox});
  way["location"="underground"]({bbox});
  way["waterway"="dam"]({bbox});
  node["waterway"="dam"]({bbox});
  way["waterway"="weir"]({bbox});
  way["man_made"="embankment"]({bbox});
  way["man_made"="dyke"]({bbox});
  node["natural"="cliff"]({bbox});
  way["amenity"="school"]({bbox});
  node["amenity"="school"]({bbox});
  way["amenity"="hospital"]({bbox});
  node["amenity"="hospital"]({bbox});
  way["shop"="mall"]({bbox});
  node["shop"="mall"]({bbox});
  way["shop"="supermarket"]({bbox});
  way["building"]["name"]({bbox});
  node["building"]["name"]({bbox});
  way["natural"="wetland"]({bbox});
  node["natural"="wetland"]({bbox});
  node["landuse"="construction"]({bbox});
  way["landuse"="construction"]({bbox});
);
out center 200;
"""

    try:
        resp = requests.post(
            'https://overpass-api.de/api/interpreter',
            data={'data': query},
            timeout=25
        )
        if resp.status_code != 200:
            _safe_log(f"[OSM] Overpass API 返回 {resp.status_code}")
            return []

        data = resp.json()
        elements = data.get('elements', [])
        _safe_log(f"[OSM] bbox={bbox}, 获取到 {len(elements)} 个地理要素")

        features = []
        seen_names = set()

        for e in elements:
            tags = e.get('tags', {})
            name = tags.get('name:zh', tags.get('name', ''))
            lat = e.get('lat') or (e.get('center', {}) or {}).get('lat')
            lng = e.get('lon') or (e.get('center', {}) or {}).get('lon')

            if not lat or not lng:
                continue

            feat_type = ''
            feat_category = ''

            if tags.get('tunnel') == 'yes':
                feat_type = '隧道/下穿通道'
                feat_category = '隧道'
                if not name:
                    road_name = tags.get('name', tags.get('ref', ''))
                    name = f"{road_name}隧道" if road_name else ''
            elif tags.get('bridge') == 'yes':
                feat_type = '桥梁'
                feat_category = '桥梁'
                if not name:
                    road_name = tags.get('name', tags.get('ref', ''))
                    name = f"{road_name}桥" if road_name else ''
            elif 'waterway' in tags:
                wt = tags['waterway']
                wt_names = {'river': '河流', 'canal': '运河', 'stream': '溪流',
                            'drain': '排水渠', 'ditch': '沟渠', 'dam': '水坝', 'weir': '水闸'}
                feat_type = wt_names.get(wt, f'水系({wt})')
                feat_category = '河道'
            elif tags.get('railway') == 'subway_entrance':
                feat_type = '地铁出入口'
                feat_category = '地下空间'
            elif tags.get('parking') == 'underground' or tags.get('location') == 'underground':
                feat_type = '地下空间'
                feat_category = '地下空间'
            elif tags.get('man_made') in ('embankment', 'dyke'):
                feat_type = '堤坝/护坡'
                feat_category = '边坡'
            elif tags.get('natural') == 'cliff':
                feat_type = '陡坡/悬崖'
                feat_category = '边坡'
            elif tags.get('amenity') == 'school':
                feat_type = '学校'
                feat_category = '人员密集场所'
            elif tags.get('amenity') == 'hospital':
                feat_type = '医院'
                feat_category = '人员密集场所'
            elif tags.get('shop') in ('mall', 'supermarket'):
                feat_type = '商场/超市'
                feat_category = '人员密集场所'
            elif tags.get('natural') == 'wetland':
                feat_type = '湿地/低洼地'
                feat_category = '易涝点'
            elif tags.get('landuse') == 'construction':
                feat_type = '建设工地'
                feat_category = '危房'
            elif tags.get('building'):
                btype = tags['building']
                bt_names = {'residential': '住宅', 'commercial': '商业', 'industrial': '工业',
                            'office': '办公', 'retail': '商铺', 'yes': '建筑'}
                feat_type = bt_names.get(btype, f'建筑({btype})')
                feat_category = '建筑'
            else:
                continue

            if not name:
                continue

            dedup_key = f"{name}_{feat_category}"
            if dedup_key in seen_names:
                continue
            seen_names.add(dedup_key)

            features.append({
                'name': name,
                'type': feat_type,
                'category': feat_category,
                'lat': round(lat, 6),
                'lng': round(lng, 6),
            })

        # 限制数量，按类型均衡分配
        if len(features) > 80:
            by_cat = {}
            for f in features:
                cat = f['category']
                if cat not in by_cat:
                    by_cat[cat] = []
                by_cat[cat].append(f)
            features = []
            for cat, items in by_cat.items():
                features.extend(items[:15])

        _safe_log(f"[OSM] 最终筛选 {len(features)} 个有名地理要素")
        # 存入缓存
        if features:
            _osm_cache[cache_key] = features
        return features

    except requests.exceptions.Timeout:
        _safe_log("[OSM] Overpass API 请求超时")
        return []
    except Exception as e:
        _safe_log(f"[OSM] 获取地理数据异常: {e}")
        _safe_log(traceback.format_exc())
        return []


def _find_region_hazards(region_name: str, center_lat: float = None, center_lng: float = None) -> list:
    """根据区域名称从知识库中查找匹配的风险点数据"""
    # 按名称匹配（region_name 不能为空）
    if region_name and region_name.strip():
        for key, data in REGION_HAZARD_KNOWLEDGE.items():
            if key in region_name or region_name in key:
                return data["hazards"]

    # 通过坐标匹配最近的区域
    if center_lat and center_lng:
        best_key = None
        best_dist = float('inf')
        for key, data in REGION_HAZARD_KNOWLEDGE.items():
            c = data["center"]
            dist = (c[0] - center_lat) ** 2 + (c[1] - center_lng) ** 2
            if dist < best_dist:
                best_dist = dist
                best_key = key
        if best_key and best_dist < 0.1:  # 约10km范围内
            return REGION_HAZARD_KNOWLEDGE[best_key]["hazards"]

    return []


def analyze_local_hazards(region_name: str, center_lat: float, center_lng: float,
                          radius_km: float = 10, client=None) -> dict:
    """
    AI智能分析本地风险点（基于真实地理数据）
    策略：
    1. 通过 Overpass API 获取区域内真实地理要素（建筑、水系、隧道等）
    2. 将真实要素列表传给AI，让AI分析哪些是三防风险点
    3. 如果 Overpass 失败，回退到知识库 + AI 兜底
    """
    hazards = []
    ai_enhanced = False
    ai_summary = ""

    # ========== 第1步：获取真实地理数据 ==========
    osm_features = _fetch_osm_features(center_lat, center_lng, radius_km)
    _safe_log(f"[风险分析] 区域={region_name}, 中心=({center_lat:.4f},{center_lng:.4f}), "
          f"半径={radius_km}km, OSM要素={len(osm_features)}个")

    # ========== 第2步：基于真实地理数据进行AI分析 ==========
    if osm_features and client:
        try:
            # 按类别整理要素清单
            cat_groups = {}
            for f in osm_features:
                cat = f['category']
                if cat not in cat_groups:
                    cat_groups[cat] = []
                cat_groups[cat].append(f)

            feature_text = ""
            for cat, items in cat_groups.items():
                feature_text += f"\n【{cat}】共{len(items)}个：\n"
                for i, item in enumerate(items[:20], 1):
                    feature_text += f"  {i}. {item['name']}（{item['type']}）坐标: {item['lat']},{item['lng']}\n"

            prompt = f"""你是三防应急管理专家（防风、防汛、防旱）。我通过地理信息系统获取了以下圈定区域内的真实地理要素数据，请分析哪些地点在暴雨、台风、洪水等灾害场景下存在安全风险。

圈定区域：{region_name}
中心坐标：纬度{center_lat:.6f}，经度{center_lng:.6f}
分析范围：半径约{radius_km}公里（只分析此范围内的要素）

该圈定区域内的真实地理要素：
{feature_text}

请严格从以上圈定范围内的真实地理要素中，筛选出存在三防风险隐患的点位，并分析风险原因。
要求：
1. 只使用上面提供的真实地名和坐标，不要编造，不要引入范围外的地点
2. 筛选出5-12个最有风险的点位
3. 对每个点位给出具体的风险类型和原因
4. 重点关注：低洼易涝区、地下空间进水风险、河道/水系溢出风险、隧道积水、老旧建筑抗风能力、边坡滑坡、桥梁洪水冲击等

严格按以下JSON格式输出，不要有任何其他文字：
{{
  "summary": "该区域三防风险概况（2-3句话）",
  "hazards": [
    {{
      "name": "真实地名/建筑名",
      "type": "隧道/河道/易涝点/地下空间/危房/边坡/桥梁/人员密集",
      "level": "重大/较大/一般",
      "lat": 实际纬度数值,
      "lng": 实际经度数值,
      "location": "所在位置描述",
      "description": "具体风险原因(30字内)",
      "risk_score": 0到100的风险评分
    }}
  ]
}}"""
            messages = [
                {"role": "system", "content": "你是一位资深三防应急管理专家。基于真实地理数据分析区域风险。只输出JSON格式结果，不要有其他文字。"},
                {"role": "user", "content": prompt}
            ]
            resp = client._call_api(messages, temperature=0.3, max_tokens=4000)
            if resp:
                resp_clean = resp.strip()
                if resp_clean.startswith("```"):
                    resp_clean = resp_clean.split("\n", 1)[-1]
                if resp_clean.endswith("```"):
                    resp_clean = resp_clean.rsplit("```", 1)[0]
                resp_clean = resp_clean.strip()

                ai_result = json.loads(resp_clean)
                hazards = ai_result.get("hazards", [])
                ai_summary = ai_result.get("summary", "")
                ai_enhanced = True

                # 按风险评分排序
                hazards.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
                _safe_log(f"[风险分析] AI基于真实地理数据分析出 {len(hazards)} 个风险点")
        except Exception as e:
            _safe_log(f"[风险分析] AI分析真实地理数据异常: {e}")
            _safe_log(traceback.format_exc())

    # ========== 第3步：如果OSM有数据但AI失败，直接将高风险类别要素作为风险点 ==========
    if not hazards and osm_features:
        # 所有类别都纳入，按风险程度分级
        high_risk = {'隧道', '河道', '易涝点'}
        mid_risk = {'地下空间', '边坡', '桥梁'}
        low_risk = {'人员密集场所', '建筑'}

        # 合并同一地铁站的多个出入口
        station_map = {}  # station_name -> first feature
        other_features = []
        for f in osm_features:
            if f['category'] == '地下空间' and '站' in f['name']:
                # 提取站名（如 "越秀公园站 B1出入口" -> "越秀公园站"）
                station = f['name'].split('站')[0] + '站'
                if station not in station_map:
                    station_map[station] = {
                        "name": station,
                        "type": "地下空间",
                        "level": "较大",
                        "lat": f['lat'],
                        "lng": f['lng'],
                        "location": f"{region_name} 地铁站地下空间",
                        "description": "地铁站地下空间，暴雨期间存在倒灌进水风险",
                    }
            else:
                other_features.append(f)

        # 添加合并后的地铁站
        hazards.extend(station_map.values())

        # 添加其他要素
        for f in other_features:
            cat = f['category']
            if cat in high_risk:
                level = "重大"
            elif cat in mid_risk:
                level = "较大"
            else:
                level = "一般"

            desc_map = {
                '隧道': '隧道低洼处，暴雨易积水导致交通中断',
                '河道': '暴雨期间水位上涨，存在溢出风险',
                '易涝点': '低洼地带，排水能力不足易发生内涝',
                '边坡': '强降雨可能引发滑坡地质灾害',
                '桥梁': '暴雨期间桥下易积水，桥面可能受洪水冲击',
                '人员密集场所': '人员密集，灾害时疏散压力大',
                '建筑': '建筑设施，台风暴雨时需关注结构安全',
                '地下空间': '地下空间，暴雨期间存在进水风险',
            }

            hazards.append({
                "name": f['name'],
                "type": cat if cat not in ('人员密集场所',) else '人员密集',
                "level": level,
                "lat": f['lat'],
                "lng": f['lng'],
                "location": f"{region_name} {f['type']}",
                "description": desc_map.get(cat, f"{f['type']}，暴雨期间存在安全风险"),
            })

        # 限制数量，优先保留高风险
        if len(hazards) > 15:
            hazards.sort(key=lambda h: (
                0 if h.get('level') == '重大' else 1 if h.get('level') == '较大' else 2
            ))
            hazards = hazards[:15]

        if hazards:
            ai_summary = f"已通过地理信息系统识别{region_name}范围内{len(hazards)}个潜在风险点（未经AI增强分析）"
            _safe_log(f"[风险分析] 无AI，直接输出 {len(hazards)} 个高风险类别要素")

    # ========== 第4步：回退到知识库（如果OSM也没数据） ==========
    if not hazards:
        base_hazards = _find_region_hazards(region_name, center_lat, center_lng)
        if base_hazards:
            filtered = []
            for h in base_hazards:
                dlat = (h["lat"] - center_lat) * 111
                dlng = (h["lng"] - center_lng) * 111 * abs(
                    math.cos(center_lat * math.pi / 180))
                dist = (dlat ** 2 + dlng ** 2) ** 0.5
                # 严格只取圈定范围内的点
                if dist <= radius_km:
                    hc = dict(h)
                    hc["distance_km"] = round(dist, 1)
                    filtered.append(hc)
            filtered.sort(key=lambda x: x["distance_km"])
            hazards = filtered
            if hazards:
                ai_summary = f"使用预置知识库数据（仅保留圈定范围{radius_km}km内的{len(hazards)}个点）"
            _safe_log(f"[风险分析] 回退到知识库，严格过滤后 {len(hazards)} 个风险点在范围内")

    # ========== 第5步：最后兜底 - 让AI凭区域名生成 ==========
    if not hazards and client:
        lat_offset = radius_km / 111.0
        lng_offset = radius_km / (111.0 * abs(math.cos(math.radians(center_lat))))
        try:
            prompt = f"""你是三防应急管理专家。请分析以下圈定区域内可能存在的三防风险点（防风、防汛、防旱）。

区域：{region_name}
中心坐标：纬度{center_lat:.6f}，经度{center_lng:.6f}
分析范围：半径约{radius_km}公里
坐标范围：纬度 {center_lat - lat_offset:.4f} ~ {center_lat + lat_offset:.4f}，经度 {center_lng - lng_offset:.4f} ~ {center_lng + lng_offset:.4f}

请基于该圈定区域内的地理特征，识别可能的风险隐患点。
严格按以下JSON格式输出，不要有任何其他文字：
{{
  "summary": "该圈定区域风险概况(2-3句)",
  "hazards": [
    {{
      "name": "风险点名称（必须使用该区域内真实存在的地名）",
      "type": "隧道/河道/易涝点/地下空间/危房/边坡/桥下",
      "level": "重大/较大/一般",
      "lat": 纬度值(必须在{center_lat - lat_offset:.4f}到{center_lat + lat_offset:.4f}之间),
      "lng": 经度值(必须在{center_lng - lng_offset:.4f}到{center_lng + lng_offset:.4f}之间),
      "location": "详细位置",
      "description": "风险描述(30字内)"
    }},
    ...列出5-8个风险点
  ]
}}

严格要求：
1. 所有坐标必须在上述坐标范围内，不要超出
2. 使用该区域内真实存在的建筑物、道路、河流名称
3. 风险点类型要多样化"""
            messages = [
                {"role": "system", "content": "你是一位三防应急管理专家。只分析指定圈定范围内的风险点。只输出JSON格式结果。"},
                {"role": "user", "content": prompt}
            ]
            resp = client._call_api(messages, temperature=0.5, max_tokens=3000)
            if resp:
                resp_clean = resp.strip()
                if resp_clean.startswith("```"):
                    resp_clean = resp_clean.split("\n", 1)[-1]
                if resp_clean.endswith("```"):
                    resp_clean = resp_clean.rsplit("```", 1)[0]
                resp_clean = resp_clean.strip()

                ai_result = json.loads(resp_clean)
                hazards = ai_result.get("hazards", [])
                ai_summary = ai_result.get("summary", "")
                ai_enhanced = True
        except Exception as e:
            _safe_log(f"[风险分析] AI生成风险点异常: {e}")
            _safe_log(traceback.format_exc())

    # ========== 最终验证：严格过滤掉圈定范围外的点 ==========
    if hazards:
        verified = []
        for h in hazards:
            hlat = h.get("lat")
            hlng = h.get("lng")
            if hlat is None or hlng is None:
                continue
            dlat = (hlat - center_lat) * 111
            dlng = (hlng - center_lng) * 111 * abs(math.cos(math.radians(center_lat)))
            dist = (dlat ** 2 + dlng ** 2) ** 0.5
            if dist <= radius_km * 1.05:  # 允许5%容差
                h["distance_km"] = round(dist, 1)
                verified.append(h)
            else:
                _safe_log(f"[风险分析] 过滤掉范围外的点: {h.get('name')} 距离{dist:.1f}km > {radius_km}km")
        if len(verified) < len(hazards):
            _safe_log(f"[风险分析] 范围验证: {len(hazards)} -> {len(verified)} (过滤了{len(hazards)-len(verified)}个范围外的点)")
        hazards = verified

    # 生成统计
    type_count = {}
    for h in hazards:
        t = h.get("type", "其他")
        type_count[t] = type_count.get(t, 0) + 1

    return {
        "hazards": hazards,
        "ai_enhanced": ai_enhanced,
        "osm_features_count": len(osm_features),
        "summary": ai_summary or f"已识别{region_name}范围内{len(hazards)}个三防风险隐患点",
        "统计": {
            "易涝点": type_count.get("易涝点", 0) + type_count.get("桥下", 0),
            "危房": type_count.get("危房", 0),
            "地下空间": type_count.get("地下空间", 0),
            "河道": type_count.get("河道", 0),
            "隧道": type_count.get("隧道", 0),
            "边坡": type_count.get("边坡", 0),
            "桥梁": type_count.get("桥梁", 0),
            "人员密集": type_count.get("人员密集", 0),
            "总计": len(hazards),
        },
        "region": region_name,
    }
