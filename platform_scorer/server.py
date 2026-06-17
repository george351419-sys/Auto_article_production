"""Platform Scorer — independent scoring agent per LLD §3.7.

Evaluates a final package across wechat/xiaohongshu/toutiao dimensions.
Mock mode returns fixed scores; real mode calls DeepSeek (OpenAI-compatible).

Start: python3 server.py --host 127.0.0.1 --port 8789
Toggle real LLM:  PLATFORM_SCORER_MOCK=0 python3 server.py
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from adapters.contract import router as contract_router

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("platform_scorer")

START_TIME = time.time()
MOCK_MODE = os.environ.get("PLATFORM_SCORER_MOCK", "1") not in ("0", "false", "False", "")

_ENV_VAR_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _load_llm_config() -> dict:
    """Read shared_config.json's llm.deepseek section with env interpolation."""
    cfg_path = ROOT / "shared_config.json"
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    block = raw.get("llm", {}).get("deepseek", {}) or {}

    def sub(v):
        if isinstance(v, str):
            return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), v)
        return v

    return {k: sub(v) for k, v in block.items()}


_load_dotenv()
_LLM_CFG = _load_llm_config()


def create_app() -> FastAPI:
    app = FastAPI(title="平台评分 Agent", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(contract_router)

    @app.post("/api/score")
    async def score_article(body: dict):
        """Score a final package across 3 platforms.

        Request per LLD §3.7:
        {
          "article_id": "uuid",
          "topic_brief": "...",
          "platforms": ["wechat","xiaohongshu","toutiao"],
          "package_summary": { "platforms": [...] }
        }
        """
        article_id = body.get("article_id", "")
        platforms = body.get("platforms", ["wechat", "xiaohongshu", "toutiao"])
        topic_brief = body.get("topic_brief", "")
        package_summary = body.get("package_summary", {})

        if not article_id:
            raise HTTPException(400, detail={
                "error": {"code": "SCORE.INPUT.EMPTY_PACKAGE",
                          "message": "article_id is required"}})

        used_model = "mock"
        if MOCK_MODE:
            scores = _mock_scores(platforms)
        else:
            scores, used_model = await _real_scores(topic_brief, package_summary, platforms)

        return {
            "scores": scores,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": used_model,
        }

    return app


def _mock_scores(platforms: list[str]) -> dict:
    """Fixed mock scores for M1-M4 testing."""
    defaults = {
        "wechat": {"score": 80, "reason": "深度长文契合公众号读者偏好，话题时效性强"},
        "xiaohongshu": {"score": 70, "reason": "内容质量可，图片占比适中，标题风格适配"},
        "toutiao": {"score": 60, "reason": "时效性强适合头条推荐，但深度偏长"},
    }
    return {p: defaults.get(p, {"score": 50, "reason": "未识别平台"}) for p in platforms}


_PLATFORM_LABEL_CN = {
    "wechat": "微信公众号",
    "xiaohongshu": "小红书",
    "toutiao": "今日头条",
}

_SCORING_RUBRIC_CN = {
    "wechat": "适合深度长文、专业洞察、行业分析；标题宜稳重，摘要要点要清晰",
    "xiaohongshu": "适合短平快、生活化、强人设、强情绪、强种草；标题要有钩子，emoji 可加分",
    "toutiao": "适合时效性话题、争议点、社会新闻、易读流畅；标题要有冲突或反差",
}


def _package_for_platform(pkg: dict, platform: str) -> dict:
    """Pick the platform-specific block from final_package.platforms[*]."""
    platforms = pkg.get("platforms")
    if not isinstance(platforms, list):
        return {}
    for pp in platforms:
        if isinstance(pp, dict) and pp.get("platform") == platform:
            return pp
    return {}


def _excerpt(text: str, n: int = 800) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    return text if len(text) <= n else text[:n] + "..."


def _build_prompt(topic_brief: str, package_summary: dict, platforms: list[str]) -> str:
    blocks = []
    for p in platforms:
        pp = _package_for_platform(package_summary, p)
        titles = pp.get("titles", [])
        if isinstance(titles, list):
            titles_str = " / ".join(str(t) for t in titles if t)
        else:
            titles_str = str(titles or "")
        body = pp.get("formattedArticle") or pp.get("formatted_article") or ""
        summary = pp.get("summary") or ""
        blocks.append(
            f"### {_PLATFORM_LABEL_CN.get(p, p)} ({p})\n"
            f"- 适配标准: {_SCORING_RUBRIC_CN.get(p, '无')}\n"
            f"- 候选标题: {titles_str or '(空)'}\n"
            f"- 摘要: {summary or '(空)'}\n"
            f"- 正文节选: {_excerpt(body)}"
        )
    schema_inner = ",\n    ".join(
        f'"{p}": {{ "score": 0~100 的整数, "reason": "30字以内中文" }}' for p in platforms
    )
    return (
        "你是一名资深内容平台编辑，请根据下面的「选题简述」和各平台「文章包」，"
        "对每个平台从 0-100 给出一个发布合适度分数，并用一句中文写出最关键的判断依据。"
        "评分维度：标题吸引力、内容与平台调性的契合度、读者匹配度、时效与差异化。\n\n"
        f"## 选题简述\n{_excerpt(topic_brief, 400) or '(空)'}\n\n"
        "## 各平台文章包\n"
        + "\n\n".join(blocks)
        + "\n\n## 输出要求\n"
        "严格按下面的 JSON 结构返回，**不要有任何其他文字**：\n"
        "{\n"
        '  "scores": {\n'
        f"    {schema_inner}\n"
        "  }\n"
        "}"
    )


def _coerce_scores(raw: dict, platforms: list[str]) -> dict:
    """Validate + clamp LLM output into the contract shape."""
    src = raw.get("scores") if isinstance(raw, dict) else None
    if not isinstance(src, dict):
        src = raw if isinstance(raw, dict) else {}
    result: dict = {}
    for p in platforms:
        item = src.get(p) or {}
        try:
            score = int(round(float(item.get("score", 50))))
        except (TypeError, ValueError):
            score = 50
        score = max(0, min(100, score))
        reason = str(item.get("reason") or "").strip() or "LLM 未给出理由"
        if len(reason) > 60:
            reason = reason[:60]
        result[p] = {"score": score, "reason": reason}
    return result


async def _real_scores(topic_brief: str, package_summary: dict, platforms: list[str]) -> tuple[dict, str]:
    """Call DeepSeek LLM (OpenAI-compatible) for real scoring.

    Falls back to mock on any error so the pipeline never blocks here.
    Returns (scores, model_name).
    """
    api_key = _LLM_CFG.get("api_key") or ""
    base_url = (_LLM_CFG.get("base_url") or "https://api.deepseek.com/v1").rstrip("/")
    model = _LLM_CFG.get("model") or "deepseek-chat"
    if not api_key:
        logger.warning("DEEPSEEK_API_KEY missing — falling back to mock scoring")
        return _mock_scores(platforms), "mock"

    prompt = _build_prompt(topic_brief, package_summary, platforms)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一名资深内容平台编辑，擅长评估文章在不同平台的发布合适度。只输出严格 JSON。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return _coerce_scores(parsed, platforms), model
    except httpx.HTTPStatusError as e:
        logger.warning("DeepSeek HTTP %s: %s — falling back to mock", e.response.status_code, e.response.text[:200])
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("DeepSeek parse error (%s) — falling back to mock", e)
    except Exception as e:
        logger.warning("DeepSeek call failed (%s: %s) — falling back to mock", type(e).__name__, e)
    return _mock_scores(platforms), "mock"


app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="平台评分 Agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--mock", action="store_true", default=False,
                        help="Force mock scoring (overrides PLATFORM_SCORER_MOCK env)")
    parser.add_argument("--real", action="store_true", default=False,
                        help="Force real LLM scoring (overrides PLATFORM_SCORER_MOCK env)")
    args = parser.parse_args()

    if args.mock:
        MOCK_MODE = True
    elif args.real:
        MOCK_MODE = False
    logger.info(
        "Starting platform_scorer on %s:%s (mock=%s, model=%s, key=%s)",
        args.host, args.port, MOCK_MODE,
        _LLM_CFG.get("model", "?"),
        "set" if _LLM_CFG.get("api_key") else "MISSING",
    )
    uvicorn.run(app, host=args.host, port=args.port)
