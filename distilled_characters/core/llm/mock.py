"""Mock LLM backend for offline development and testing."""
from __future__ import annotations

from core.llm.base import AbstractLLMBackend


class MockBackend(AbstractLLMBackend):
    """Returns canned responses for every step. No API key needed.

    Useful for:
    - Frontend development without a configured API
    - Integration testing the pipeline end-to-end
    - Demonstrating the system without incurring API costs
    """

    def __init__(self, model: str = "mock-model") -> None:
        self._model = model

    async def send_prompt(
        self,
        user_prompt: str,
        system_message: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        # Route to the right mock response based on prompt content
        prompt_lower = user_prompt.lower()

        if "step 1" in system_message.lower() or "置信度" in user_prompt:
            return self._mock_step1_response()
        if "step 2" in system_message.lower() or "思维链三元组" in user_prompt:
            return self._mock_step2_response()
        if "step 3" in system_message.lower() or "中层蒸馏" in user_prompt:
            return self._mock_step3_response()
        if "step 4" in system_message.lower() or "深层蒸馏" in user_prompt:
            return self._mock_step4_response()
        if "step 5" in system_message.lower() or "边界补全" in user_prompt:
            return self._mock_step5_response()
        if "step 6" in system_message.lower() or "交叉验证" in user_prompt:
            return self._mock_step6_response()

        # Fallback: return generic JSON
        return '{"status": "ok", "message": "Mock response"}'

    async def test_connection(self) -> bool:
        return True

    @property
    def backend_type(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model

    # ── Step-specific mock responses ───────────────────────────────

    def _mock_step1_response(self) -> str:
        return """
[
  {
    "material_id": "m1",
    "source_type": "systematic_output",
    "confidence": "S",
    "cleaned_content": "样本清洁文本内容...",
    "tags": ["方法论", "认知"],
    "rationale": "来源于正式出版的著作，属于最高置信度素材。"
  },
  {
    "material_id": "m2",
    "source_type": "improv_expression",
    "confidence": "A",
    "cleaned_content": "样本访谈清洁文本...",
    "tags": ["对话", "实践"],
    "rationale": "正式媒体深度访谈，内容完整可供交叉验证。"
  }
]
        """.strip()

    def _mock_step2_response(self) -> str:
        return """
{
  "triples": [
    {
      "material_id": "m1",
      "problem_scenario": "面对复杂问题时如何拆解",
      "thinking_path": "先识别核心变量，再分析变量间关系，最后寻找杠杆点",
      "conclusion": "系统性思考优于线性拆解",
      "tags": ["方法论", "系统思维"]
    }
  ],
  "expression_dna_draft": {
    "language_tone": "理性、犀利、善用比喻",
    "sentence_rhythm": "长短句交替，先用短句定调，再用长句展开",
    "rhetorical_habits": [
      {"pattern": "战争比喻", "description": "常用战场、攻防等军事隐喻描述商业竞争"}
    ],
    "catchphrases": [
      {"phrase": "stay hungry, stay foolish", "frequency": 5, "context": "激励他人时使用"}
    ],
    "high_freq_words": [
      {"word": "创新", "count": 42},
      {"word": "专注", "count": 28}
    ]
  }
}
        """.strip()

    def _mock_step3_response(self) -> str:
        return """
{
  "thinking_tools": {
    "analysis_frameworks": [
      {
        "name": "三维分析法",
        "description": "从成本-收益-风险三个维度分析任何商业决策",
        "dimensions": ["成本", "收益", "风险"],
        "usage_scenarios": ["商业决策", "项目评估"],
        "source_material_ids": ["m1"]
      }
    ],
    "attribution_logic": {
      "direction": "mixed",
      "layers": "multi",
      "time_perspective": "long-term"
    },
    "reasoning_paradigms": ["归纳法", "系统性思维", "类比推理"],
    "common_theories": ["第一性原理", "复利思维", "奥卡姆剃刀"]
  },
  "decision_rules": {
    "priority_rules": [
      {
        "rule": "长期价值优先于短期利益",
        "explanation": "做决策时始终以十年以上的时间尺度来衡量",
        "source_material_ids": ["m1", "m2"]
      }
    ],
    "tradeoff_principles": ["宁缺毋滥", "质量优于速度"],
    "risk_tolerance": "可接受可控风险，厌恶不可逆风险",
    "evaluation_thresholds": [
      {"criterion": "产品质量", "threshold": "必须达到能让自己骄傲的水平", "context": "产品发布决策"}
    ],
    "heuristics": [
      {
        "name": "反向思考",
        "description": "先想清楚什么会导致失败，然后规避它",
        "when_to_use": "面对重大决策时",
        "when_it_fails": "需要快速反应的场景"
      }
    ]
  }
}
        """.strip()

    def _mock_step4_response(self) -> str:
        return """
{
  "worldview": {
    "attention_focus": "别人看结果，他看过程和机制；别人看表象，他看本质结构",
    "fundamental_assumptions": {
      "human_nature": "人有无限潜力，但需要正确的环境和激励",
      "world_nature": "世界是可以被理解和改变的，而非混沌不可知的",
      "time_orientation": "极度关注长远未来，牺牲当下换取未来"
    },
    "value_hierarchy": ["创新", "卓越", "自由", "效率"],
    "unique_perspective": "用第一性原理拆解一切，拒绝类比思维带来的平庸",
    "cognitive_blind_spots": ["容易低估人际关系和情感因素的重要性", "倾向于认为所有人都应该追求卓越"]
  }
}
        """.strip()

    def _mock_step5_response(self) -> str:
        return """
{
  "boundaries_evolution": {
    "anti_patterns": [
      {"pattern": "从众思维", "explanation": "强烈反对因为'别人都这样做'而做决策"},
      {"pattern": "抄袭模仿", "explanation": "视抄袭为创造力最大的敌人"}
    ],
    "value_red_lines": ["不做有违道德的产品", "不牺牲隐私换便利"],
    "capability_boundaries": ["公开承认不懂时尚", "不懂传统制造业"],
    "expression_taboos": ["不使用官僚语言", "不写空洞的套话"],
    "cognitive_evolution": [
      {
        "phase": "早期",
        "time_period": "1976-1985",
        "key_views": ["技术至上", "理想主义"],
        "trigger_events": ["创办Apple", "Macintosh项目"]
      },
      {
        "phase": "成熟期",
        "time_period": "1997-2011",
        "key_views": ["人文与技术的交叉", "简洁即终极的复杂"],
        "trigger_events": ["回归Apple", "iPhone发布"]
      }
    ]
  }
}
        """.strip()

    def _mock_step6_response(self) -> str:
        return """
{
  "verification": {
    "cross_consistency": {"passed": true, "issues": [], "coverage_rate": 0.85},
    "back_testing": {"passed": true, "match_rate": 0.9, "test_cases": []},
    "boundary_compliance": {"passed": true, "issues": []}
  },
  "layers": {}
}
        """.strip()
