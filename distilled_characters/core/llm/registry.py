"""LLM backend registry — factory + vendor presets with model→base_url mapping."""
from __future__ import annotations

from core.llm.base import AbstractLLMBackend
from core.llm.anthropic import AnthropicBackend
from core.llm.mock import MockBackend
from core.llm.openai_compatible import OpenAICompatibleBackend


def create_backend(config: dict) -> AbstractLLMBackend:
    t = config.get("type", "openai_compatible")
    timeout = float(config.get("timeout", 180))
    max_retries = int(config.get("max_retries", 2))
    if t == "mock":
        return MockBackend(model=config.get("model", "mock-model"))
    if t == "anthropic":
        return AnthropicBackend(
            api_key=config.get("api_key", ""),
            model=config.get("model", "claude-sonnet-4-6"),
            base_url=config.get("base_url", "https://api.anthropic.com"),
            timeout=timeout,
            max_retries=max_retries,
        )
    # "llm", "openai_compatible", or any unknown → OpenAI compatible
    return OpenAICompatibleBackend(
        base_url=config.get("base_url", "https://api.openai.com/v1"),
        api_key=config.get("api_key", ""),
        model=config.get("model", "gpt-4o"),
        timeout=timeout,
        max_retries=max_retries,
    )


BACKEND_TYPES = {
    "llm": "LLM (大语言模型)",
    "search": "搜索接口",
    "anthropic": "Anthropic Messages API",
    "mock": "Mock (offline)",
}

# ── Vendor presets ─────────────────────────────────────────────────
# Each vendor has a list of {id, label} models and a default base_url.
# When user picks a model, the base_url auto-fills from the vendor.

VENDOR_PRESETS = {
    "xunfei": {
        "name": "讯飞星火 Spark (Lite)",
        "type": "llm",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "models": [
            {"id": "4.0Ultra", "label": "Spark 4.0 Ultra"},
            {"id": "generalv3.5", "label": "Spark Max"},
            {"id": "generalv3", "label": "Spark Pro"},
            {"id": "lite", "label": "Spark Lite"},
        ],
        "desc": "讯飞星火大模型（Lite 免费通道）— APIPassword 认证，格式 appid:apisecret",
        "docs": "https://www.xfyun.cn/doc/spark/",
        "auth_hint": "APIPassword = APPID:APISecret（控制台位置D）。Spark Lite 有免费额度。",
    },
    "xunfei_maas": {
        "name": "讯飞星辰 MaaS",
        "type": "llm",
        "base_url": "https://maas-api.cn-huabei-1.xf-yun.com/v2",
        "models": [
            {"id": "4.0Ultra", "label": "Spark 4.0 Ultra"},
            {"id": "generalv3.5", "label": "Spark Max"},
            {"id": "generalv3", "label": "Spark Pro"},
        ],
        "desc": "讯飞星辰 MaaS 平台（华北1区 OpenAI 兼容接口）— 需在 maas.xfyun.cn 订阅模型后获取独立 API Key",
        "docs": "https://maas.xfyun.cn/modelSquare",
        "auth_hint": "API Key 是在 MaaS 平台订阅模型后生成的独立 Key，不是控制台的 APIKey/APISecret。",
    },
    "deepseek": {
        "name": "DeepSeek 深度求索",
        "type": "llm",
        "base_url": "https://api.deepseek.com/v1",
        "models": [
            {"id": "deepseek-chat", "label": "DeepSeek-V3"},
            {"id": "deepseek-reasoner", "label": "DeepSeek-R1"},
        ],
        "desc": "DeepSeek 深度求索 — 国产高性价比大模型",
        "docs": "https://platform.deepseek.com/api-docs",
    },
    "aliyun": {
        "name": "阿里百炼 (通义千问)",
        "type": "llm",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": [
            {"id": "qwen-turbo", "label": "Qwen Turbo"},
            {"id": "qwen-plus", "label": "Qwen Plus"},
            {"id": "qwen-max", "label": "Qwen Max"},
        ],
        "desc": "阿里云百炼平台 — 通义千问系列模型",
        "docs": "https://help.aliyun.com/document_detail/2712195.html",
    },
    "zhipu": {
        "name": "智谱AI (GLM)",
        "type": "llm",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": [
            {"id": "glm-4-flash", "label": "GLM-4 Flash"},
            {"id": "glm-4-air", "label": "GLM-4 Air"},
            {"id": "glm-4-plus", "label": "GLM-4 Plus"},
        ],
        "desc": "智谱AI — GLM系列大模型",
        "docs": "https://open.bigmodel.cn/dev/api",
    },
    "moonshot": {
        "name": "月之暗面 Kimi",
        "type": "llm",
        "base_url": "https://api.moonshot.cn/v1",
        "models": [
            {"id": "moonshot-v1-8k", "label": "Moonshot v1 8K"},
            {"id": "moonshot-v1-32k", "label": "Moonshot v1 32K"},
            {"id": "moonshot-v1-128k", "label": "Moonshot v1 128K"},
        ],
        "desc": "月之暗面 — Kimi 大模型",
        "docs": "https://platform.moonshot.cn/docs",
    },
    "qianfan": {
        "name": "百度千帆 (文心)",
        "type": "llm",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": [
            {"id": "ernie-speed-8k", "label": "ERNIE Speed"},
            {"id": "ernie-3.5-8k", "label": "ERNIE 3.5"},
            {"id": "ernie-4.0-turbo-8k", "label": "ERNIE 4.0 Turbo"},
        ],
        "desc": "百度智能云千帆 — 文心一言系列模型",
        "docs": "https://cloud.baidu.com/doc/WENXINWORKSHOP/s/Fm2vrveyu",
    },
    "bytedance": {
        "name": "字节豆包 Doubao",
        "type": "llm",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": [
            {"id": "doubao-lite-32k", "label": "Doubao Lite"},
            {"id": "doubao-pro-32k", "label": "Doubao Pro"},
        ],
        "desc": "字节跳动 — 豆包大模型",
        "docs": "https://www.volcengine.com/docs/82379",
    },
    "minimax": {
        "name": "MiniMax 稀宇",
        "type": "llm",
        "base_url": "https://api.minimax.chat/v1",
        "models": [
            {"id": "abab6.5s-chat", "label": "ABAB 6.5s"},
            {"id": "MiniMax-Text-01", "label": "MiniMax Text 01"},
        ],
        "desc": "MiniMax 稀宇科技 — ABAB系列大模型",
        "docs": "https://platform.minimaxi.com/document/ChatCompletion",
    },
    "xiaomi": {
        "name": "小米 MiMo",
        "type": "llm",
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": [
            {"id": "mimo-v2.5-pro", "label": "MiMo 2.5 Pro（旗舰）"},
            {"id": "mimo-v2.5", "label": "MiMo 2.5（全能）"},
            {"id": "mimo-v2-pro", "label": "MiMo 2 Pro（Agent）"},
            {"id": "mimo-v2-flash", "label": "MiMo 2 Flash（轻量）"},
        ],
        "desc": "小米 MiMo 大模型 — OpenAI 兼容接口，支持文本/图像/视频/音频",
        "docs": "https://platform.xiaomimimo.com/",
    },
    "openai": {
        "name": "OpenAI",
        "type": "llm",
        "base_url": "https://api.openai.com/v1",
        "models": [
            {"id": "gpt-4o", "label": "GPT-4o"},
            {"id": "gpt-4o-mini", "label": "GPT-4o Mini"},
        ],
        "desc": "OpenAI — GPT系列模型",
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "type": "anthropic",
        "base_url": "https://api.anthropic.com",
        "models": [
            {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6"},
            {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5"},
            {"id": "claude-opus-4-7", "label": "Claude Opus 4.7"},
        ],
        "desc": "Anthropic — Claude系列模型",
        "docs": "https://console.anthropic.com/keys",
    },
}
