# -*- coding: utf-8 -*-
"""
通义千问大模型集成测试
测试三种模式（rule/llm/hybrid）+ 降级机制 + 智能对话
"""
import sys
import os

# Windows GBK 控制台兼容
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env（指定路径）
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    load_dotenv(_env_path)
except ImportError:
    pass

# ==================== 测试数据 ====================
weather = {
    "rain_24h": 85,
    "warning_level": 3,
    "forecast": "暴雨"
}

terrain = {
    "最低高程": 28,
    "平均高程": 45,
    "低洼易涝点": 3,
    "可能淹没面积": "0.8km²",
    "最大积水深度": "0.5-1.2米",
    "是否沿河": True
}

hazards = [
    {"name": "XX隧道", "type": "隧道", "level": "高风险", "历史淹水": True, "elevation": 25, "location": "XX路段"},
    {"name": "XX桥洞", "type": "桥下", "level": "高风险", "历史淹水": True, "elevation": 30, "location": "XX大桥"},
    {"name": "XX地下车库", "type": "地下空间", "level": "高风险", "elevation": 28, "location": "XX小区"},
    {"name": "XX沿河路段", "type": "河道", "level": "中风险", "elevation": 35, "location": "XX街道"},
    {"name": "XX老旧小区", "type": "易涝点", "level": "中风险", "历史淹水": True, "elevation": 32, "location": "XX社区"},
]

passed = 0
failed = 0

def test(name, func):
    global passed, failed
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print('='*60)
    try:
        func()
        passed += 1
        print(f"  -> PASS")
    except Exception as e:
        failed += 1
        print(f"  -> FAIL: {e}")
        import traceback
        traceback.print_exc()


# ==================== 测试 1: API 连通性 ====================
def test_connection():
    from qwen_client import QwenClient
    client = QwenClient()
    ok = client.test_connection()
    assert ok, "API 连接失败"

test("1. 通义千问 API 连通性", test_connection)


# ==================== 测试 2: 纯规则模式 ====================
def test_rule_mode():
    from ai_judge import ai_comprehensive_judge_v2
    result = ai_comprehensive_judge_v2(weather, terrain, hazards, mode='rule')
    assert "1_综合风险等级" in result, "缺少风险等级字段"
    assert "5_指挥建议" in result, "缺少指挥建议字段"
    assert "_fallback" not in result, "rule 模式不应有 fallback 标记"
    level = result["1_综合风险等级"]["等级"]
    print(f"  规则引擎判定: {level}")

test("2. 纯规则模式 (mode=rule)", test_rule_mode)


# ==================== 测试 3: 纯大模型模式 ====================
def test_llm_mode():
    from ai_judge import ai_comprehensive_judge_v2
    result = ai_comprehensive_judge_v2(weather, terrain, hazards, mode='llm')
    assert "1_综合风险等级" in result, "缺少风险等级字段"
    assert "3_Top5危险点位" in result, "缺少Top5字段"
    assert "6_领导汇报" in result, "缺少领导汇报字段"
    source = result.get("_source", result.get("_fallback", "unknown"))
    print(f"  结果来源: {source}")
    print(f"  风险等级: {result['1_综合风险等级'].get('等级', '?')}")
    suggestions = result.get("5_指挥建议", [])
    print(f"  建议条数: {len(suggestions)}")

test("3. 纯大模型模式 (mode=llm)", test_llm_mode)


# ==================== 测试 4: 混合模式 ====================
def test_hybrid_mode():
    from ai_judge import ai_comprehensive_judge_v2
    result = ai_comprehensive_judge_v2(weather, terrain, hazards, mode='hybrid')
    assert "1_综合风险等级" in result, "缺少风险等级字段"
    enhanced = result.get("_llm_enhanced", False)
    fallback = result.get("_fallback", False)
    print(f"  LLM增强: {enhanced}")
    print(f"  降级标记: {fallback}")
    print(f"  建议条数: {len(result.get('5_指挥建议', []))}")
    leader = result.get("6_领导汇报", "")
    print(f"  汇报话术长度: {len(leader)}字")

test("4. 混合模式 (mode=hybrid)", test_hybrid_mode)


# ==================== 测试 5: 智能对话 ====================
def test_chat():
    from qwen_client import QwenClient
    client = QwenClient()

    # 构造上下文
    context = {
        "风险等级": "高风险",
        "响应等级": "II级响应",
        "Top5点位": ["XX隧道", "XX桥洞", "XX地下车库"],
        "主要风险": ["城市内涝", "隧道淹水"],
    }

    # 第一轮对话
    reply1 = client.chat("哪个点位最需要优先处置？", context=context, history=[])
    assert reply1 and len(reply1) > 10, f"回复太短: {reply1}"
    print(f"  Q: 哪个点位最需要优先处置？")
    print(f"  A: {reply1[:100]}...")

    # 第二轮对话（带历史）
    history = [
        {"role": "user", "content": "哪个点位最需要优先处置？"},
        {"role": "assistant", "content": reply1},
    ]
    reply2 = client.chat("那里需要调派多少人？", context=context, history=history)
    assert reply2 and len(reply2) > 10, f"回复太短: {reply2}"
    print(f"  Q: 那里需要调派多少人？")
    print(f"  A: {reply2[:100]}...")

test("5. 智能对话（多轮）", test_chat)


# ==================== 测试 6: Flask 路由集成 ====================
def test_flask_routes():
    # 使用 Flask test client
    from app import app as flask_app
    client = flask_app.test_client()

    # 测试 /api/ai/judge (rule 模式)
    resp = client.post('/api/ai/judge', json={
        'weather': weather,
        'terrain': terrain,
        'hazards': hazards,
        'mode': 'rule',
    })
    assert resp.status_code == 200, f"judge 返回 {resp.status_code}"
    data = resp.get_json()
    assert "1_综合风险等级" in data, "judge 缺少风险等级"
    print(f"  /api/ai/judge (rule): {data['1_综合风险等级']['等级']}")

    # 测试 /api/ai/chat
    resp2 = client.post('/api/ai/chat', json={
        'message': '当前最危险的是哪个点位？',
        'context': {"风险等级": "高风险", "Top5": ["XX隧道"]},
    })
    assert resp2.status_code == 200, f"chat 返回 {resp2.status_code}"
    chat_data = resp2.get_json()
    assert "reply" in chat_data, "chat 缺少 reply"
    assert "session_id" in chat_data, "chat 缺少 session_id"
    print(f"  /api/ai/chat: session={chat_data['session_id']}, reply={chat_data['reply'][:80]}...")

    # 测试带 session_id 的追问
    resp3 = client.post('/api/ai/chat', json={
        'message': '需要多少抢险人员？',
        'session_id': chat_data['session_id'],
    })
    assert resp3.status_code == 200, f"chat follow-up 返回 {resp3.status_code}"
    data3 = resp3.get_json()
    print(f"  追问: reply={data3['reply'][:80]}...")

test("6. Flask 路由集成测试", test_flask_routes)


# ==================== 汇总 ====================
print(f"\n{'='*60}")
print(f"测试完成: {passed} 通过, {failed} 失败, 共 {passed+failed} 项")
print(f"{'='*60}")

if failed > 0:
    sys.exit(1)
