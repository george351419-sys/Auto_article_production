import { execFile } from "node:child_process";
import { promisify } from "node:util";
import type { ImageAsset, SourceMaterial } from "../shared/types";

const execFileAsync = promisify(execFile);

export interface ResearchProvider {
  id: string;
  label: string;
  run(topic: string): Promise<SourceMaterial[]>;
}

const DEFAULT_PROVIDER_IDS = [
  "claw-search",
  "serper",
  "tavily",
  "firecrawl",
  "bing-web",
  "bing-news",
  "duckduckgo-api",
  "duckduckgo",
  "wikipedia",
  "hn",
  "reddit",
  "arxiv",
  "semantic-scholar",
  "gdelt"
];
const MAX_RESULTS_PER_PROVIDER = 3;
const REQUEST_TIMEOUT_MS = 4500;
const MAX_SOURCE_CONTENT_CHARS = 1200;

export async function runMaterialResearch(topic: string): Promise<SourceMaterial[]> {
  const providers = enabledProviders();
  const queries = buildResearchQueries(topic);
  const settled = await Promise.allSettled(
    providers.flatMap((provider) => queries.map((query) => provider.run(query)))
  );
  const sources = settled.flatMap((result) => (result.status === "fulfilled" ? result.value : []));
  const relevantSources = sources.filter((source) => isRelevantSource(source, topic));

  if (relevantSources.length > 0) {
    return dedupeSources(relevantSources);
  }

  return [
    {
      id: "research-no-results",
      title: "默认素材检索未取得结果",
      content:
        "已尝试无密钥公开检索源，但没有取得可用结果。可以补充用户资料，或配置 LAST30DAYS_COMMAND / LAST30DAYS_CN_COMMAND / SEARCH_API_KEY 增强检索。",
      origin: "web",
      url: "local://research/no-results"
    }
  ];
}

function buildResearchQueries(topic: string) {
  const year = new Date().getFullYear();
  const cleaned = topic
    .replace(/今年/g, String(year))
    .replace(/如何/g, "")
    .replace(/怎么/g, "")
    .replace(/怎样/g, "")
    .replace(/怎么办/g, "")
    .replace(/\s+/g, " ")
    .trim();

  const queries = [topic];
  if (cleaned && cleaned !== topic) {
    queries.push(cleaned);
  }
  if (/高考|志愿|填报/.test(topic)) {
    queries.push(`${year} 高考志愿填报 指南 政策 批次 平行志愿`);
  } else if (/[\u4e00-\u9fa5]/.test(topic)) {
    queries.push(`${cleaned || topic} 最新 经验 指南 常见误区`);
  } else {
    queries.push(`${topic} guide analysis latest`);
  }

  return [...new Set(queries)].slice(0, 3);
}

export function enabledProviders(): ResearchProvider[] {
  const configuredIds = (process.env.RESEARCH_PROVIDERS || DEFAULT_PROVIDER_IDS.join(","))
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  const providerMap: Record<string, ResearchProvider> = {
    "claw-search": clawSearchProvider,
    serper: serperProvider,
    tavily: tavilyProvider,
    firecrawl: firecrawlProvider,
    "bing-web": bingWebProvider,
    "bing-news": bingNewsProvider,
    "duckduckgo-api": duckDuckGoApiProvider,
    duckduckgo: duckDuckGoProvider,
    wikipedia: wikipediaProvider,
    hn: hackerNewsProvider,
    reddit: redditProvider,
    arxiv: arxivProvider,
    "semantic-scholar": semanticScholarProvider,
    gdelt: gdeltProvider,
    github: githubProvider,
    crossref: crossrefProvider,
    openalex: openAlexProvider,
    brave: braveProvider,
    serpapi: serpApiProvider,
    "google-cse": googleCseProvider,
    last30days: last30DaysProvider("LAST30DAYS_COMMAND", "last30days"),
    "last30days-cn": last30DaysProvider("LAST30DAYS_CN_COMMAND", "last30days-cn")
  };

  return configuredIds.map((id) => providerMap[id]).filter((provider): provider is ResearchProvider => Boolean(provider));
}

const clawSearchProvider: ResearchProvider = {
  id: "claw-search",
  label: "Claw Search",
  async run(topic) {
    const url = new URL("https://www.claw-search.com/api/search");
    url.search = new URLSearchParams({ q: topic }).toString();
    const data = await fetchJson<unknown>(url.toString());
    return extractGenericSearchResults(data).slice(0, MAX_RESULTS_PER_PROVIDER).map((item, index) => ({
      id: `claw-search-${index + 1}-${hash(item.url || item.title || item.content)}`,
      title: `Claw Search：${item.title || `搜索结果 ${index + 1}`}`,
      content: item.content,
      origin: "web",
      url: item.url,
      images: imageAssetsFromUrls(item.images, "Claw Search", item.url)
    }));
  }
};

const serperProvider: ResearchProvider = {
  id: "serper",
  label: "Serper.dev",
  async run(topic) {
    const apiKey = process.env.SERPER_API_KEY;
    if (!apiKey) {
      return [];
    }
    const data = await fetchJson<{
      organic?: Array<{ title?: string; link?: string; snippet?: string; date?: string; source?: string }>;
      news?: Array<{ title?: string; link?: string; snippet?: string; date?: string; source?: string }>;
      peopleAlsoAsk?: Array<{ question?: string; snippet?: string; title?: string; link?: string }>;
    }>("https://google.serper.dev/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-KEY": apiKey
      },
      body: JSON.stringify({
        q: topic,
        num: MAX_RESULTS_PER_PROVIDER,
        gl: /[\u4e00-\u9fa5]/.test(topic) ? "cn" : "us",
        hl: /[\u4e00-\u9fa5]/.test(topic) ? "zh-cn" : "en"
      })
    });

    const results: Array<{ title?: string; question?: string; link?: string; snippet?: string; date?: string; source?: string }> = [
      ...(data.organic ?? []),
      ...(data.news ?? []),
      ...(data.peopleAlsoAsk ?? [])
    ];
    return results.slice(0, MAX_RESULTS_PER_PROVIDER).map((item, index) => {
      const imageUrl = stringValue((item as Record<string, unknown>).imageUrl) || stringValue((item as Record<string, unknown>).thumbnail);
      return {
        id: `serper-${index + 1}-${hash(item.link || item.title || item.question || "")}`,
        title: `Serper：${item.title || item.question || `搜索结果 ${index + 1}`}`,
        content: `${item.snippet || ""} source=${"source" in item ? item.source || "unknown" : "peopleAlsoAsk"}; date=${
          "date" in item ? item.date || "unknown" : "unknown"
        }.`,
        origin: "web",
        url: item.link,
        images: imageAssetsFromUrls(imageUrl ? [imageUrl] : [], "Serper", item.link)
      };
    });
  }
};

const tavilyProvider: ResearchProvider = {
  id: "tavily",
  label: "Tavily",
  async run(topic) {
    const apiKey = process.env.TAVILY_API_KEY || process.env.SEARCH_API_KEY;
    if (!apiKey) {
      return [];
    }
    const data = await fetchJson<{
      results?: Array<{ title?: string; content?: string; raw_content?: string; url?: string; score?: number }>;
    }>("https://api.tavily.com/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        api_key: apiKey,
        query: topic,
        max_results: MAX_RESULTS_PER_PROVIDER,
        search_depth: "basic",
        include_answer: false,
        include_raw_content: false
      })
    });
    return (data.results ?? []).map((item, index) => ({
      id: `tavily-${index + 1}-${hash(item.url || item.title || "")}`,
      title: `Tavily：${item.title || `搜索结果 ${index + 1}`}`,
      content: `${item.content || item.raw_content || ""} score=${item.score ?? "unknown"}.`,
      origin: "web",
      url: item.url
    }));
  }
};

const firecrawlProvider: ResearchProvider = {
  id: "firecrawl",
  label: "Firecrawl",
  async run(topic) {
    const apiKey = process.env.FIRECRAWL_API_KEY;
    if (!apiKey) {
      return [];
    }
    const data = await fetchJson<unknown>("https://api.firecrawl.dev/v1/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        query: topic,
        limit: MAX_RESULTS_PER_PROVIDER,
        scrapeOptions: {
          formats: ["markdown"]
        }
      })
    });
    return extractGenericSearchResults(data).slice(0, MAX_RESULTS_PER_PROVIDER).map((item, index) => ({
      id: `firecrawl-${index + 1}-${hash(item.url || item.title || item.content)}`,
      title: `Firecrawl：${item.title || `搜索结果 ${index + 1}`}`,
      content: item.content,
      origin: "web",
      url: item.url,
      images: imageAssetsFromUrls(item.images, "Firecrawl", item.url)
    }));
  }
};

const bingWebProvider: ResearchProvider = {
  id: "bing-web",
  label: "Bing Web RSS",
  async run(topic) {
    const url = new URL("https://www.bing.com/search");
    url.search = new URLSearchParams({ q: topic, format: "rss", setlang: inferLanguage(topic) }).toString();
    return parseRssSources(await fetchText(url.toString()), "bing-web", "Bing网页");
  }
};

const bingNewsProvider: ResearchProvider = {
  id: "bing-news",
  label: "Bing News RSS",
  async run(topic) {
    const url = new URL("https://www.bing.com/news/search");
    url.search = new URLSearchParams({ q: topic, format: "rss", setlang: inferLanguage(topic) }).toString();
    return parseRssSources(await fetchText(url.toString()), "bing-news", "Bing新闻");
  }
};

const duckDuckGoApiProvider: ResearchProvider = {
  id: "duckduckgo-api",
  label: "DuckDuckGo Instant Answer API",
  async run(topic) {
    const url = new URL("https://api.duckduckgo.com/");
    url.search = new URLSearchParams({
      q: topic,
      format: "json",
      no_html: "1",
      no_redirect: "1",
      skip_disambig: "0"
    }).toString();
    const data = await fetchJson<{
      Heading?: string;
      AbstractText?: string;
      AbstractURL?: string;
      Image?: string;
      Answer?: string;
      AnswerType?: string;
      RelatedTopics?: Array<
        | { Text?: string; FirstURL?: string; Result?: string }
        | { Name?: string; Topics?: Array<{ Text?: string; FirstURL?: string; Result?: string }> }
      >;
    }>(url.toString());
    const related: Array<{ Text?: string; FirstURL?: string; Result?: string }> = [];
    for (const item of data.RelatedTopics ?? []) {
      if ("Topics" in item) {
        related.push(...(item.Topics ?? []));
      } else if (isDuckDuckGoTopic(item)) {
        related.push(item);
      }
    }
    const results: Array<{ title?: string; content: string; url?: string; imageUrl?: string }> = [
      {
        title: data.Heading,
        content: [data.AbstractText, data.Answer ? `${data.AnswerType || "answer"}=${data.Answer}` : ""]
          .filter(Boolean)
          .join("\n"),
        url: data.AbstractURL,
        imageUrl: data.Image
      },
      ...related.map((item) => ({
        title: item.Text?.split(" - ")[0],
        content: item.Text || stripHtml(item.Result || ""),
        url: item.FirstURL,
        imageUrl: undefined
      }))
    ].filter((item) => item.content);

    return results.slice(0, MAX_RESULTS_PER_PROVIDER).map((item, index) => ({
      id: `duckduckgo-api-${index + 1}-${hash(item.url || item.title || item.content)}`,
      title: `DuckDuckGo API：${item.title || `即时答案 ${index + 1}`}`,
      content: item.content,
      origin: "web",
      url: item.url,
      images: imageAssetsFromUrls(item.imageUrl ? [item.imageUrl] : [], "DuckDuckGo API", item.url)
    }));
  }
};

const duckDuckGoProvider: ResearchProvider = {
  id: "duckduckgo",
  label: "DuckDuckGo",
  async run(topic) {
    const url = new URL("https://html.duckduckgo.com/html/");
    url.search = new URLSearchParams({ q: topic }).toString();
    const html = await fetchText(url.toString(), {
      headers: {
        "User-Agent": "Mozilla/5.0 auto-writing-agent-system",
        Accept: "text/html"
      }
    });
    return [...html.matchAll(/<a rel="nofollow" class="result__a" href="([\s\S]*?)">([\s\S]*?)<\/a>[\s\S]*?<a class="result__snippet"[\s\S]*?>([\s\S]*?)<\/a>/g)]
      .slice(0, MAX_RESULTS_PER_PROVIDER)
      .map((match, index) => {
        const href = decodeDuckDuckGoUrl(decodeHtml(match[1]));
        return {
          id: `duckduckgo-${index + 1}-${hash(href)}`,
          title: `DuckDuckGo：${decodeHtml(stripHtml(match[2]))}`,
          content: decodeHtml(stripHtml(match[3])),
          origin: "web" as const,
          url: href
        };
      });
  }
};

const wikipediaProvider: ResearchProvider = {
  id: "wikipedia",
  label: "Wikipedia",
  async run(topic) {
    const host = /[\u4e00-\u9fa5]/.test(topic) ? "zh.wikipedia.org" : "en.wikipedia.org";
    const url = new URL(`https://${host}/w/api.php`);
    url.search = new URLSearchParams({
      action: "query",
      list: "search",
      srsearch: topic,
      format: "json",
      origin: "*",
      srlimit: String(MAX_RESULTS_PER_PROVIDER)
    }).toString();
    const data = await fetchJson<{ query?: { search?: Array<{ title: string; snippet: string; pageid: number }> } }>(
      url.toString()
    );
    return (data.query?.search ?? []).map((item) => ({
      id: `wikipedia-${item.pageid}`,
      title: `Wikipedia：${item.title}`,
      content: stripHtml(item.snippet),
      origin: "web",
      url: `https://en.wikipedia.org/?curid=${item.pageid}`
    }));
  }
};

const hackerNewsProvider: ResearchProvider = {
  id: "hn",
  label: "Hacker News",
  async run(topic) {
    const url = new URL("https://hn.algolia.com/api/v1/search");
    url.search = new URLSearchParams({
      query: topic,
      tags: "story",
      hitsPerPage: String(MAX_RESULTS_PER_PROVIDER)
    }).toString();
    const data = await fetchJson<{
      hits?: Array<{ objectID: string; title?: string; url?: string; points?: number; num_comments?: number }>;
    }>(url.toString());
    return (data.hits ?? []).map((item) => ({
      id: `hn-${item.objectID}`,
      title: `Hacker News：${item.title || item.objectID}`,
      content: `points=${item.points ?? 0}; comments=${item.num_comments ?? 0}. 这是开发者社区互动信号，可用于判断技术圈关注度。`,
      origin: "web",
      url: item.url || `https://news.ycombinator.com/item?id=${item.objectID}`
    }));
  }
};

const redditProvider: ResearchProvider = {
  id: "reddit",
  label: "Reddit",
  async run(topic) {
    const url = new URL("https://www.reddit.com/search.json");
    url.search = new URLSearchParams({
      q: topic,
      sort: "relevance",
      t: "month",
      limit: String(MAX_RESULTS_PER_PROVIDER),
      raw_json: "1"
    }).toString();
    const data = await fetchJson<{
      data?: {
        children?: Array<{
          data?: {
            id?: string;
            title?: string;
            selftext?: string;
            subreddit?: string;
            permalink?: string;
            url?: string;
            score?: number;
            num_comments?: number;
            created_utc?: number;
          };
        }>;
      };
    }>(url.toString(), {
      headers: {
        "User-Agent": "auto-writing-agent-system/0.1 research"
      }
    });
    return (data.data?.children ?? []).map((child, index) => {
      const item = child.data ?? {};
      const permalink = item.permalink ? `https://www.reddit.com${item.permalink}` : item.url;
      return {
        id: `reddit-${item.id || index}`,
        title: `Reddit：${item.title || `讨论 ${index + 1}`}`,
        content: `${(item.selftext || "").slice(0, 500)} score=${item.score ?? 0}; comments=${
          item.num_comments ?? 0
        }; subreddit=${item.subreddit || "unknown"}. 这是社区讨论信号，不作为事实源单独使用。`,
        origin: "web",
        url: permalink
      };
    });
  }
};

const arxivProvider: ResearchProvider = {
  id: "arxiv",
  label: "arXiv",
  async run(topic) {
    const url = new URL("https://export.arxiv.org/api/query");
    url.search = new URLSearchParams({
      search_query: `all:${topic}`,
      start: "0",
      max_results: String(MAX_RESULTS_PER_PROVIDER),
      sortBy: "submittedDate",
      sortOrder: "descending"
    }).toString();
    const text = await fetchText(url.toString());
    return [...text.matchAll(/<entry>([\s\S]*?)<\/entry>/g)].slice(0, MAX_RESULTS_PER_PROVIDER).map((match, index) => {
      const entry = match[1];
      const title = xmlText(entry, "title") || `arXiv 论文 ${index + 1}`;
      const summary = xmlText(entry, "summary");
      const link = entry.match(/<id>(.*?)<\/id>/)?.[1];
      return {
        id: `arxiv-${index + 1}-${hash(title)}`,
        title: `arXiv：${title}`,
        content: summary,
        origin: "web" as const,
        url: link
      };
    });
  }
};

const semanticScholarProvider: ResearchProvider = {
  id: "semantic-scholar",
  label: "Semantic Scholar",
  async run(topic) {
    const url = new URL("https://api.semanticscholar.org/graph/v1/paper/search");
    url.search = new URLSearchParams({
      query: topic,
      limit: String(MAX_RESULTS_PER_PROVIDER),
      fields: "title,abstract,year,url,citationCount,publicationTypes,authors"
    }).toString();
    const headers: Record<string, string> = {};
    if (process.env.SEMANTIC_SCHOLAR_API_KEY) {
      headers["x-api-key"] = process.env.SEMANTIC_SCHOLAR_API_KEY;
    }
    const data = await fetchJson<{
      data?: Array<{
        paperId?: string;
        title?: string;
        abstract?: string;
        year?: number;
        url?: string;
        citationCount?: number;
        publicationTypes?: string[];
        authors?: Array<{ name?: string }>;
      }>;
    }>(url.toString(), { headers });
    return (data.data ?? []).map((item, index) => ({
      id: `semantic-scholar-${item.paperId || index}`,
      title: `Semantic Scholar：${item.title || `论文 ${index + 1}`}`,
      content: `${item.abstract || "无摘要"} year=${item.year ?? "unknown"}; citations=${
        item.citationCount ?? 0
      }; authors=${(item.authors ?? []).map((author) => author.name).filter(Boolean).slice(0, 3).join(", ") || "unknown"}.`,
      origin: "web",
      url: item.url
    }));
  }
};

const gdeltProvider: ResearchProvider = {
  id: "gdelt",
  label: "GDELT",
  async run(topic) {
    const url = new URL("https://api.gdeltproject.org/api/v2/doc/doc");
    url.search = new URLSearchParams({
      query: topic,
      mode: "artlist",
      format: "json",
      maxrecords: String(MAX_RESULTS_PER_PROVIDER),
      sort: "hybridrel"
    }).toString();
    const data = await fetchJson<{
      articles?: Array<{ title?: string; url?: string; seendate?: string; domain?: string; sourcecountry?: string }>;
    }>(url.toString());
    return (data.articles ?? []).map((item, index) => ({
      id: `gdelt-${index + 1}-${hash(item.url || item.title || "")}`,
      title: `GDELT：${item.title || "新闻素材"}`,
      content: `source=${item.domain || "unknown"}; seen=${item.seendate || "unknown"}; country=${item.sourcecountry || "unknown"}. 这是全球新闻公开索引素材。`,
      origin: "web",
      url: item.url
    }));
  }
};

const githubProvider: ResearchProvider = {
  id: "github",
  label: "GitHub",
  async run(topic) {
    const url = new URL("https://api.github.com/search/repositories");
    url.search = new URLSearchParams({
      q: topic,
      sort: "updated",
      order: "desc",
      per_page: String(MAX_RESULTS_PER_PROVIDER)
    }).toString();
    const data = await fetchJson<{
      items?: Array<{
        id: number;
        full_name?: string;
        html_url?: string;
        description?: string;
        stargazers_count?: number;
        open_issues_count?: number;
      }>;
    }>(url.toString(), { headers: { "User-Agent": "auto-writing-agent-system" } });
    return (data.items ?? []).map((item) => ({
      id: `github-${item.id}`,
      title: `GitHub：${item.full_name || item.id}`,
      content: `${item.description || "无描述"} stars=${item.stargazers_count ?? 0}; issues=${item.open_issues_count ?? 0}.`,
      origin: "web",
      url: item.html_url
    }));
  }
};

const crossrefProvider: ResearchProvider = {
  id: "crossref",
  label: "Crossref",
  async run(topic) {
    const url = new URL("https://api.crossref.org/works");
    url.search = new URLSearchParams({
      query: topic,
      rows: String(MAX_RESULTS_PER_PROVIDER),
      sort: "published",
      order: "desc"
    }).toString();
    const data = await fetchJson<{
      message?: {
        items?: Array<{ DOI?: string; title?: string[]; abstract?: string; URL?: string; published?: { "date-parts"?: number[][] } }>;
      };
    }>(url.toString());
    return (data.message?.items ?? []).map((item, index) => ({
      id: `crossref-${item.DOI || index}`,
      title: `Crossref：${item.title?.[0] || item.DOI || `文献 ${index + 1}`}`,
      content: stripHtml(item.abstract || `published=${item.published?.["date-parts"]?.[0]?.join("-") || "unknown"}`),
      origin: "web",
      url: item.URL
    }));
  }
};

const openAlexProvider: ResearchProvider = {
  id: "openalex",
  label: "OpenAlex",
  async run(topic) {
    const apiKey = process.env.OPENALEX_API_KEY;
    if (!apiKey) {
      return [];
    }
    const url = new URL("https://api.openalex.org/works");
    url.search = new URLSearchParams({
      search: topic,
      per_page: String(MAX_RESULTS_PER_PROVIDER),
      sort: "relevance_score:desc",
      api_key: apiKey,
      select: "id,display_name,publication_year,cited_by_count,abstract_inverted_index,primary_location"
    }).toString();
    const data = await fetchJson<{
      results?: Array<{
        id?: string;
        display_name?: string;
        publication_year?: number;
        cited_by_count?: number;
        abstract_inverted_index?: Record<string, number[]>;
        primary_location?: { landing_page_url?: string };
      }>;
    }>(url.toString());
    return (data.results ?? []).map((item, index) => ({
      id: `openalex-${hash(item.id || String(index))}`,
      title: `OpenAlex：${item.display_name || `学术作品 ${index + 1}`}`,
      content: `${restoreOpenAlexAbstract(item.abstract_inverted_index)} year=${
        item.publication_year ?? "unknown"
      }; citations=${item.cited_by_count ?? 0}.`,
      origin: "web",
      url: item.primary_location?.landing_page_url || item.id
    }));
  }
};

const braveProvider: ResearchProvider = {
  id: "brave",
  label: "Brave Search",
  async run(topic) {
    const apiKey = process.env.BRAVE_SEARCH_API_KEY;
    if (!apiKey) {
      return [];
    }
    const url = new URL("https://api.search.brave.com/res/v1/web/search");
    url.search = new URLSearchParams({
      q: topic,
      count: String(MAX_RESULTS_PER_PROVIDER),
      freshness: inferFreshness(topic),
      search_lang: inferLanguage(topic)
    }).toString();
    const data = await fetchJson<{
      web?: { results?: Array<{ title?: string; url?: string; description?: string; extra_snippets?: string[] }> };
      news?: { results?: Array<{ title?: string; url?: string; description?: string; age?: string }> };
    }>(url.toString(), {
      headers: {
        Accept: "application/json",
        "X-Subscription-Token": apiKey
      }
    });
    return [...(data.web?.results ?? []), ...(data.news?.results ?? [])]
      .slice(0, MAX_RESULTS_PER_PROVIDER)
      .map((item, index) => ({
        id: `brave-${index + 1}-${hash(item.url || item.title || "")}`,
        title: `Brave：${item.title || `搜索结果 ${index + 1}`}`,
        content: [
          item.description,
          ...("extra_snippets" in item && Array.isArray(item.extra_snippets) ? item.extra_snippets : [])
        ]
          .filter(Boolean)
          .join("\n"),
        origin: "web" as const,
        url: item.url
      }));
  }
};

const serpApiProvider: ResearchProvider = {
  id: "serpapi",
  label: "SerpApi",
  async run(topic) {
    const apiKey = process.env.SERPAPI_API_KEY;
    if (!apiKey) {
      return [];
    }
    const url = new URL("https://serpapi.com/search.json");
    url.search = new URLSearchParams({
      q: topic,
      api_key: apiKey,
      engine: "google",
      num: String(MAX_RESULTS_PER_PROVIDER),
      hl: /[\u4e00-\u9fa5]/.test(topic) ? "zh-cn" : "en"
    }).toString();
    const data = await fetchJson<{
      organic_results?: Array<{ title?: string; link?: string; snippet?: string; source?: string; date?: string }>;
      news_results?: Array<{ title?: string; link?: string; snippet?: string; source?: string; date?: string }>;
    }>(url.toString());
    return [...(data.organic_results ?? []), ...(data.news_results ?? [])]
      .slice(0, MAX_RESULTS_PER_PROVIDER)
      .map((item, index) => ({
        id: `serpapi-${index + 1}-${hash(item.link || item.title || "")}`,
        title: `SerpApi：${item.title || `搜索结果 ${index + 1}`}`,
        content: `${item.snippet || ""} source=${item.source || "unknown"}; date=${item.date || "unknown"}.`,
        origin: "web" as const,
        url: item.link
      }));
  }
};

const googleCseProvider: ResearchProvider = {
  id: "google-cse",
  label: "Google Custom Search",
  async run(topic) {
    const apiKey = process.env.GOOGLE_CSE_API_KEY;
    const cx = process.env.GOOGLE_CSE_ID;
    if (!apiKey || !cx) {
      return [];
    }
    const url = new URL("https://www.googleapis.com/customsearch/v1");
    url.search = new URLSearchParams({
      key: apiKey,
      cx,
      q: topic,
      num: String(MAX_RESULTS_PER_PROVIDER)
    }).toString();
    const data = await fetchJson<{
      items?: Array<{ title?: string; link?: string; snippet?: string; displayLink?: string }>;
    }>(url.toString());
    return (data.items ?? []).map((item, index) => ({
      id: `google-cse-${index + 1}-${hash(item.link || item.title || "")}`,
      title: `Google CSE：${item.title || `搜索结果 ${index + 1}`}`,
      content: `${item.snippet || ""} domain=${item.displayLink || "unknown"}.`,
      origin: "web",
      url: item.link
    }));
  }
};

function last30DaysProvider(envName: string, sourceId: string): ResearchProvider {
  return {
    id: sourceId,
    label: sourceId,
    async run(topic) {
      const command = process.env[envName];
      if (!command) {
        return [];
      }
      const [bin, ...baseArgs] = command.split(/\s+/).filter(Boolean);
      const { stdout } = await execFileAsync(bin, [...baseArgs, topic, "--emit", "json"], {
        timeout: Number(process.env.LAST30DAYS_TIMEOUT_MS ?? 120000),
        maxBuffer: 1024 * 1024 * 5
      });
      return [
        {
          id: `${sourceId}-${hash(topic)}`,
          title: `${sourceId}：最近30天真实互动素材`,
          content: stdout.slice(0, 12000),
          origin: "web",
          url: `local://${sourceId}/${encodeURIComponent(topic)}`
        }
      ];
    }
  };
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithTimeout(url, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

async function fetchText(url: string, init?: RequestInit): Promise<string> {
  const response = await fetchWithTimeout(url, init);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.text();
}

async function fetchWithTimeout(url: string, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

function dedupeSources(sources: SourceMaterial[]) {
  const seen = new Set<string>();
  return sources
    .filter((source) => source.title.trim() && source.content.trim())
    .map((source) => ({
      ...source,
      title: source.title.slice(0, 180),
      content:
        source.content.length > MAX_SOURCE_CONTENT_CHARS
          ? `${source.content.slice(0, MAX_SOURCE_CONTENT_CHARS)}...`
          : source.content
    }))
    .filter((source) => {
      const key = source.url || `${source.title}:${source.content.slice(0, 80)}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
}

function extractGenericSearchResults(data: unknown): Array<{ title: string; content: string; url?: string; images: string[] }> {
  const candidates = collectSearchCandidates(data);
  return candidates
    .map((item): { title: string; content: string; url?: string; images: string[] } | undefined => {
      if (!isRecord(item)) {
        return undefined;
      }
      const title = stringValue(item.title) || stringValue(item.name) || stringValue(item.heading);
      const url = stringValue(item.url) || stringValue(item.link) || stringValue(item.href) || stringValue(item.sourceURL);
      const images = imageUrlsFromRecord(item);
      const content =
        stringValue(item.content) ||
        stringValue(item.snippet) ||
        stringValue(item.description) ||
        stringValue(item.markdown) ||
        stringValue(item.text) ||
        stringValue(item.summary);
      if (!title && !content) {
        return undefined;
      }
      const result: { title: string; content: string; url?: string; images: string[] } = {
        title: title || url || "搜索结果",
        content: content || title || "",
        images
      };
      if (url) {
        result.url = url;
      }
      return result;
    })
    .filter((item): item is { title: string; content: string; url?: string; images: string[] } => Boolean(item?.content));
}

function imageUrlsFromRecord(item: Record<string, unknown>) {
  const direct = [
    stringValue(item.image),
    stringValue(item.imageUrl),
    stringValue(item.thumbnail),
    stringValue(item.thumbnailUrl),
    stringValue(item.cover),
    stringValue(item.ogImage)
  ].filter(Boolean);
  const nested = ["images", "image_urls"].flatMap((key) =>
    Array.isArray(item[key]) ? item[key].map((value) => stringValue(value)).filter(Boolean) : []
  );
  return [...new Set([...direct, ...nested])].filter(isLikelyImageUrl).slice(0, 3);
}

function imageAssetsFromUrls(urls: string[], title: string, sourceUrl?: string): ImageAsset[] {
  return urls.filter(isLikelyImageUrl).slice(0, 3).map((url, index) => ({
    id: `image-${index + 1}-${hash(url)}`,
    title: `${title} 图片 ${index + 1}`,
    url,
    sourceUrl,
    origin: "web"
  }));
}

function isLikelyImageUrl(url: string) {
  return /^https?:\/\//i.test(url) && /\.(png|jpe?g|webp|gif|avif)(\?|#|$)/i.test(url);
}

function collectSearchCandidates(data: unknown): unknown[] {
  if (Array.isArray(data)) {
    return data;
  }
  if (!isRecord(data)) {
    return [];
  }

  const keys = ["results", "data", "items", "organic", "web", "news"];
  for (const key of keys) {
    const value = data[key];
    if (Array.isArray(value)) {
      return value;
    }
    if (isRecord(value)) {
      const nested = collectSearchCandidates(value);
      if (nested.length > 0) {
        return nested;
      }
    }
  }

  return [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown) {
  return typeof value === "string" ? stripHtml(value).trim() : "";
}

function isRelevantSource(source: SourceMaterial, topic: string) {
  const text = `${source.title} ${source.content}`.toLowerCase();
  const terms = extractKeyTerms(topic);
  if (terms.length === 0) {
    return true;
  }
  return terms.some((term) => text.includes(term.toLowerCase()));
}

function extractKeyTerms(topic: string) {
  if (/高考|志愿|填报/.test(topic)) {
    return ["高考", "志愿", "填报"];
  }
  if (/[\u4e00-\u9fa5]/.test(topic)) {
    const cleaned = topic.replace(/今年|如何|怎么|怎样|怎么办|什么|一个|这个|那个|的|了/g, " ");
    return [...cleaned.matchAll(/[\u4e00-\u9fa5]{2,}/g)].map((match) => match[0]).slice(0, 5);
  }
  return topic
    .split(/\W+/)
    .filter((term) => term.length > 3)
    .slice(0, 6);
}

function parseRssSources(xml: string, providerId: string, label: string): SourceMaterial[] {
  return [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)]
    .slice(0, MAX_RESULTS_PER_PROVIDER)
    .map((match, index) => {
      const item = match[1];
      const title = decodeHtml(xmlText(item, "title"));
      const link = decodeHtml(xmlText(item, "link"));
      const description = decodeHtml(stripHtml(xmlText(item, "description")));
      const pubDate = decodeHtml(xmlText(item, "pubDate"));
      return {
        id: `${providerId}-${index + 1}-${hash(link || title)}`,
        title: `${label}：${title || `结果 ${index + 1}`}`,
        content: [description, pubDate ? `发布时间：${pubDate}` : ""].filter(Boolean).join("\n"),
        origin: "web" as const,
        url: link
      };
    });
}

function inferLanguage(topic: string) {
  return /[\u4e00-\u9fa5]/.test(topic) ? "zh-CN" : "en-US";
}

function inferFreshness(topic: string) {
  if (/今天|今日|刚刚|最新|now|today|breaking/i.test(topic)) {
    return "pd";
  }
  if (/本周|最近|近7天|week/i.test(topic)) {
    return "pw";
  }
  if (/近30天|最近30天|月|month/i.test(topic)) {
    return "pm";
  }
  return "py";
}

function restoreOpenAlexAbstract(index?: Record<string, number[]>) {
  if (!index) {
    return "无摘要";
  }
  const words: string[] = [];
  for (const [word, positions] of Object.entries(index)) {
    for (const position of positions) {
      words[position] = word;
    }
  }
  return words.filter(Boolean).join(" ");
}

function isDuckDuckGoTopic(value: unknown): value is { Text?: string; FirstURL?: string; Result?: string } {
  return isRecord(value) && ("Text" in value || "FirstURL" in value || "Result" in value);
}

function stripHtml(value: string) {
  return value.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
}

function decodeHtml(value: string) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">");
}

function decodeDuckDuckGoUrl(value: string) {
  try {
    const parsed = new URL(value, "https://duckduckgo.com");
    const redirected = parsed.searchParams.get("uddg");
    return redirected ? decodeURIComponent(redirected) : parsed.toString();
  } catch {
    return value;
  }
}

function xmlText(entry: string, tag: string) {
  return stripHtml(entry.match(new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`))?.[1] || "");
}

function hash(value: string) {
  let result = 0;
  for (let index = 0; index < value.length; index += 1) {
    result = (result * 31 + value.charCodeAt(index)) >>> 0;
  }
  return result.toString(36);
}
