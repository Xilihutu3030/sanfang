# -*- coding: utf-8 -*-
"""
三防系统 - 通义千问大模型客户端
封装 DashScope API，提供三种能力：
1. judge_with_llm: 纯大模型研判（替代规则引擎）
2. enhance_suggestions: 混合模式（规则引擎+大模型增强）
3. chat: 智能对话（基于研判结果的问答）

支持两种 API 模式：
- 旧版 DashScope SDK（qwen-plus / qwen-max 等）
- OpenAI 兼容接口（qwen3.5-plus / qwen3-plus 等新模型）
"""

import json
import os
import re
import traceback
import logging as _logging
from typing import Dict, List, Optional

_logger = _logging.getLogger('sanfang.qwen_client')


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

# 需要走 OpenAI 兼容接口的模型前缀
_OPENAI_COMPAT_PREFIXES = ("qwen3", "qwen3.5")


def _is_openai_compat(model: str) -> bool:
    m = model.lower()
    return any(m.startswith(p) for p in _OPENAI_COMPAT_PREFIXES)


class QwenClient:
    """通义千问 API 客户端（自动适配新旧接口）"""

    OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.model = model or os.getenv("QWEN_MODEL", "qwen-plus")

        if not self.api_key:
            raise ValueError("未配置 DASHSCOPE_API_KEY")

        self._use_openai = _is_openai_compat(self.model)

        if self._use_openai:
            try:
                from openai import OpenAI
                self._openai_client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.OPENAI_BASE_URL,
                )
            except ImportError:
                raise ImportError("请安装 openai: pip install openai>=1.0.0")
        else:
            try:
                import dashscope
                dashscope.api_key = self.api_key
            except ImportError:
                raise ImportError("请安装 dashscope: pip install dashscope>=1.14.0")

    # ==================== 核心 API 调用 ====================

    def _call_api(self, messages: List[Dict], temperature: float = 0.3,
                  max_tokens: int = 2000) -> Optional[str]:
        """调用通义千问 API，返回回复文本，失败返回 None"""
        if self._use_openai:
            return self._call_openai_compat(messages, temperature, max_tokens)
        else:
            return self._call_dashscope_sdk(messages, temperature, max_tokens)

    def _call_openai_compat(self, messages: List[Dict], temperature: float,
                             max_tokens: int) -> Optional[str]:
        """OpenAI 兼容接口（qwen3.x / qwen3.5.x 系列）"""
        try:
            resp = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            msg = resp.choices[0].message
            # qwen3.5-plus 默认开启 thinking 模式，实际回复在 content
            content = msg.content or ""
            if not content and hasattr(msg, "reasoning_content"):
                content = msg.reasoning_content or ""
            return content
        except Exception as e:
            _safe_log(f"[QwenClient] OpenAI兼容接口异常: {e}")
            _safe_log(traceback.format_exc())
            return None

    def _call_dashscope_sdk(self, messages: List[Dict], temperature: float,
                             max_tokens: int) -> Optional[str]:
        """旧版 DashScope SDK（qwen-plus / qwen-max 等）"""
        from dashscope import Generation
        try:
            response = Generation.call(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                result_format='message',
            )
            if response.status_code == 200:
                return response.output.choices[0].message.content
            else:
                _safe_log(f"[QwenClient] DashScope调用失败: code={response.status_code}, "
                      f"msg={response.message}")
                return None
        except Exception as e:
            _safe_log(f"[QwenClient] DashScope SDK异常: {e}")
            _safe_log(traceback.format_exc())
            return None

    # ==================== 1. 纯大模型研判 ====================

    def judge_with_llm(self, weather_data: Dict, terrain_data: Dict,
                       hazard_points: List[Dict]) -> Optional[Dict]:
        """纯大模型研判 - 完全替代规则引擎"""
        system_prompt = """你是一位拥有20年经验的三防（防风、防汛、防旱）应急管理专家。
请根据提供的气象数据、地形数据和隐患点信息，进行综合风险研判。

你必须严格按照以下JSON格式输出，不要输出任何其他内容：

{
  "1_综合风险等级": {
    "等级": "极高风险/高风险/中风险/低风险",
    "得分": "XX/100",
    "颜色": "红色/橙色/黄色/蓝色",
    "响应等级": "I级响应/II级响应/III级响应/IV级响应",
    "风险因子": ["因子1", "因子2", "因子3"]
  },
  "2_主要风险类型": ["风险类型1", "风险类型2"],
  "3_Top5危险点位": [
    {"排名": 1, "名称": "XX", "类型": "XX", "风险分": 85, "位置": "XX", "原因": "具体原因"}
  ],
  "4_淹没预判": {
    "可能淹没面积": "XX km²",
    "最大积水深度": "X.X-X.X米",
    "灾害持续时间": "XX-XX小时"
  },
  "5_指挥建议": ["建议1", "建议2", "建议3"],
  "6_领导汇报": "一段完整的汇报话术"
}

要求：
1. 风险评估要保守，宁可高估不可低估
2. Top5危险点位必须从提供的隐患点中选取，给出具体排名理由
3. 指挥建议必须具体可操作，包含具体点位名称
4. 领导汇报话术要简洁专业，便于口头汇报
5. 只输出JSON，不要有任何前缀后缀或解释文字"""

        user_content = f"""当前数据如下：

【气象数据】
{json.dumps(weather_data, ensure_ascii=False, indent=2)}

【地形数据】
{json.dumps(terrain_data, ensure_ascii=False, indent=2)}

【隐患点列表】（共{len(hazard_points)}个）
{json.dumps(hazard_points, ensure_ascii=False, indent=2)}

请进行综合研判并输出结果。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        raw = self._call_api(messages, temperature=0.3, max_tokens=3000)
        if not raw:
            return None

        return self._parse_judge_result(raw)

    # ==================== 2. 混合模式增强 ====================

    def enhance_suggestions(self, rule_result: Dict, weather_data: Dict = None,
                            hazard_points: List[Dict] = None) -> Dict:
        """混合模式 - 保留规则引擎打分，用大模型优化建议和汇报"""
        system_prompt = """你是一位拥有20年经验的三防应急管理专家。
系统的规则引擎已经完成了基础风险评分和隐患点排名。
你的任务是基于这些结果，优化以下两个部分：
1. 指挥建议：使建议更加具体、专业、可操作
2. 领导汇报：生成更加专业精练的口头汇报话术

请严格按照以下JSON格式输出，只包含这两个字段：
{
  "5_指挥建议": ["优化后的建议1", "优化后的建议2", ...],
  "6_领导汇报": "优化后的完整汇报话术"
}

要求：
1. 建议必须引用具体点位名称和数据
2. 建议数量5-8条，按紧急程度排序
3. 汇报话术控制在150字以内，适合口头汇报
4. 只输出JSON，不要有任何其他文字"""

        context_parts = [f"【规则引擎研判结果】\n{json.dumps(rule_result, ensure_ascii=False, indent=2)}"]
        if weather_data:
            context_parts.append(f"\n【原始气象数据】\n{json.dumps(weather_data, ensure_ascii=False, indent=2)}")
        if hazard_points:
            context_parts.append(f"\n【隐患点详情】\n{json.dumps(hazard_points, ensure_ascii=False, indent=2)}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(context_parts) + "\n\n请优化指挥建议和领导汇报。"},
        ]

        raw = self._call_api(messages, temperature=0.4, max_tokens=2000)
        if not raw:
            _safe_log("[QwenClient] enhance 失败，保留规则引擎原始结果")
            return rule_result

        try:
            enhanced = self._extract_json(raw)
            if enhanced:
                result = dict(rule_result)
                if "5_指挥建议" in enhanced:
                    result["5_指挥建议"] = enhanced["5_指挥建议"]
                if "6_领导汇报" in enhanced:
                    result["6_领导汇报"] = enhanced["6_领导汇报"]
                result["_llm_enhanced"] = True
                return result
        except Exception as e:
            _safe_log(f"[QwenClient] enhance 解析失败: {e}")

        return rule_result

    # ==================== 3. 智能对话 ====================

    def chat(self, message: str, context: Dict = None,
             history: List[Dict] = None) -> str:
        """智能对话 - 基于研判结果回答指挥官的追问"""
        system_prompt = """你是三防应急指挥系统的AI助手，正在协助指挥官进行应急决策。
你已经完成了一次综合研判，指挥官正在就研判结果向你提问。

回答要求：
1. 回答要专业、具体、简洁
2. 引用研判数据时要准确
3. 给出的建议必须可操作
4. 涉及人员安全时要保守判断
5. 如果问题超出当前数据范围，坦诚告知并给出建议方向
6. 回答控制在200字以内"""

        messages = [{"role": "system", "content": system_prompt}]

        if context:
            ctx_msg = f"【当前研判结果摘要】\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            messages.append({"role": "user", "content": ctx_msg})
            messages.append({"role": "assistant", "content": "好的，我已了解当前研判结果。请问您有什么需要进一步了解的？"})

        if history:
            for h in history[-8:]:
                messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": message})

        reply = self._call_api(messages, temperature=0.5, max_tokens=1000)
        if not reply:
            return "抱歉，AI助手暂时无法响应，请稍后再试。"

        return reply

    # ==================== 工具方法 ====================

    def _parse_judge_result(self, raw: str) -> Optional[Dict]:
        """解析大模型输出的研判结果JSON"""
        data = self._extract_json(raw)
        if not data:
            return None

        required_keys = ["1_综合风险等级", "2_主要风险类型", "3_Top5危险点位",
                         "4_淹没预判", "5_指挥建议", "6_领导汇报"]
        missing = [k for k in required_keys if k not in data]
        if missing:
            _safe_log(f"[QwenClient] 研判结果缺少字段: {missing}")
            return None

        data["_source"] = "llm"
        return data

    def _extract_json(self, text: str) -> Optional[Dict]:
        """从模型输出中提取JSON（容错处理）"""
        # 直接解析
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # 从 ```json ... ``` 中提取
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 找第一个 { 和最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

        _safe_log(f"[QwenClient] JSON 提取失败，原始文本前200字: {text[:200]}")
        return None

    def test_connection(self) -> bool:
        """测试 API 连通性"""
        messages = [{"role": "user", "content": "请回复'连接正常'四个字。"}]
        result = self._call_api(messages, max_tokens=100)
        if result:
            _safe_log(f"[QwenClient] API 连接测试通过，模型: {self.model}，接口: "
                  f"{'OpenAI兼容' if self._use_openai else 'DashScope SDK'}")
            return True
        _safe_log("[QwenClient] API 连接测试失败")
        return False
