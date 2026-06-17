---
name: material-research
description: Use when preparing article material packs that need credible sources, user-interaction signals, recent discourse, citations, and differentiated insights before writing.
---

# Material Research

Use this skill before article drafting when the topic needs depth beyond user-provided notes.

## Workflow

1. Start with user materials as the highest-trust source.
2. Run default no-key research providers for broad public context:
   - DuckDuckGo for general web discovery
   - Wikipedia for entity/background grounding
   - Hacker News for developer/community interaction signals
   - arXiv for research/technical papers
   - GDELT for global news coverage
3. If configured, run engagement-first providers:
   - `LAST30DAYS_COMMAND` for international sources such as Reddit, HN, Polymarket, GitHub, YouTube, X, and web
   - `LAST30DAYS_CN_COMMAND` for Chinese sources such as 微博、小红书、B站、知乎、抖音、微信、百度、头条
4. Deduplicate by URL, cap each source summary, and keep URLs for fact checking.
5. Build a structured material pack:
   - baseline facts
   - recent changes
   - high-engagement user opinions
   - expert/research evidence
   - conflicting viewpoints
   - quotable observations
   - claims requiring human verification

## Quality Rules

- Prefer sources with explicit URLs, timestamps, engagement counts, or provenance.
- Treat social engagement as a signal, not truth.
- Do not let SEO articles dominate the pack when user-interaction sources exist.
- Flag unsupported claims instead of turning them into facts.
- Keep Chinese and international signals separate until synthesis, then compare what each side uniquely reveals.

## Integration Notes

In this project, the runtime implementation lives in `server/researchSkill.ts`.

Configure providers with:

```bash
RESEARCH_PROVIDERS=duckduckgo,wikipedia,hn,arxiv,gdelt
LAST30DAYS_COMMAND=
LAST30DAYS_CN_COMMAND=
```

Optional providers `github` and `crossref` are available but not enabled by default because generic topics can return noisy results.
