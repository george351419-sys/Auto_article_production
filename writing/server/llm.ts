import { AGENTS, GLOBAL_GUARDRAILS } from "../config/agents";
import type { AgentId, AgentIssue, Platform, SourceMaterial, TaskInput } from "../shared/types";

export interface GenerateRequest {
  agentId: AgentId;
  stage: string;
  taskInput: TaskInput;
  round: number;
  previousContext: string;
  sources: SourceMaterial[];
  platform?: Platform;
  maxScore?: number;
}

export interface GenerateResult {
  content: string;
  issues?: AgentIssue[];
  score?: number;
}

export interface LlmClient {
  generate(request: GenerateRequest): Promise<GenerateResult>;
}

class OpenAiCompatibleClient implements LlmClient {
  protected baseURL = process.env.LLM_BASE_URL ?? "https://api.openai.com/v1";
  protected model = process.env.LLM_MODEL ?? "gpt-5.2";
  protected apiKey = process.env.LLM_API_KEY ?? "";

  async generate(request: GenerateRequest): Promise<GenerateResult> {
    const agent = AGENTS[request.agentId];
    const payload = JSON.stringify({
      model: this.model,
      temperature: 0.7,
      messages: [
        {
          role: "system",
          content: [
            agent.systemPrompt,
            ...GLOBAL_GUARDRAILS,
            request.maxScore
              ? `本阶段评分上限是 ${request.maxScore}，score 必须在 0 到 ${request.maxScore} 之间；不得输出百分制或超过上限的数字。`
              : "本阶段不需要评分时，score 必须返回 null。",
            "你必须返回严格 JSON：{\"content\":\"...\",\"issues\":[],\"score\":数字或null}。issues 中字段为 id、issueType、severity、location、description、suggestion。"
          ].join("\n")
        },
        {
          role: "user",
          content: buildUserPrompt(request)
        }
      ]
    });

    const attempts = getEnvNumber("LLM_RETRIES", 2) + 1;
    let lastError: unknown;

    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        const response = await this.postCompletion(payload);

        if (!response.ok) {
          const detail = truncateText(await response.text(), 1200);
          const error = new Error(`LLM 调用失败：${response.status} ${detail}`);
          if (attempt < attempts && isRetryableStatus(response.status)) {
            lastError = error;
            await waitBeforeRetry(attempt);
            continue;
          }
          throw error;
        }

        const data = (await response.json()) as {
          choices?: Array<{ message?: { content?: string } }>;
        };
        const raw = data.choices?.[0]?.message?.content ?? "";
        return parseJsonResult(raw);
      } catch (error) {
        lastError = error;
        if (attempt < attempts && isRetryableLlmError(error)) {
          await waitBeforeRetry(attempt);
          continue;
        }
        throw formatLlmError(error, request.agentId, request.stage, attempt);
      }
    }

    throw formatLlmError(lastError, request.agentId, request.stage, attempts);
  }

  private async postCompletion(payload: string): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), getEnvNumber("LLM_TIMEOUT_MS", 120000));
    try {
      return await fetch(`${this.baseURL.replace(/\/$/, "")}/chat/completions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${this.apiKey}`
        },
        body: payload,
        signal: controller.signal
      });
    } finally {
      clearTimeout(timeout);
    }
  }
}







class QwenClient extends OpenAiCompatibleClient {
  constructor() {
    super();
    this.baseURL = process.env.QWEN_BASE_URL?.replace(/\/$/, "") ?? "https://dashscope.aliyuncs.com/compatible-mode/v1";
    this.model = process.env.QWEN_MODEL ?? "qwen3.5-flash";
    this.apiKey = process.env.QWEN_API_KEY ?? process.env.ALI_BAILIAN_API_KEY ?? process.env.DASHSCOPE_API_KEY ?? "";
  }
}

class DeepSeekClient extends OpenAiCompatibleClient {
  constructor() {
    super();
  }
}

class FallbackLlmClient implements LlmClient {
  private qwen: QwenClient;
  private deepseek: DeepSeekClient;

  constructor() {
    this.qwen = new QwenClient();
    this.deepseek = new DeepSeekClient();
  }

  async generate(request: GenerateRequest): Promise<GenerateResult> {
    const qwenRetries = getEnvNumber("QWEN_RETRIES", 2) + 1;
    let lastError: unknown;

    for (let attempt = 1; attempt <= qwenRetries; attempt += 1) {
      try {
        return await this.qwen.generate(request);
      } catch (error) {
        lastError = error;
        if (attempt < qwenRetries && isRetryableLlmError(error)) {
          await waitBeforeRetry(attempt);
          continue;
        }
        break;
      }
    }

    // Qwen failed, fall back to DeepSeek
    return await this.deepseek.generate(request);
  }
}

export function createLlmClient(): LlmClient {
  if (isMockMode()) {
    return new MockLlmClient();
  }
  if (!hasLlmConfig()) {
    throw new Error("缺少 LLM_API_KEY 或 LLM_MODEL。请配置 .env，或设置 LLM_MOCK=true 进入演示模式。");
  }
  return new FallbackLlmClient();
}


class MockLlmClient implements LlmClient {
  async generate(request: GenerateRequest): Promise<GenerateResult> {
    const agent = AGENTS[request.agentId];
    const base = `【${agent.name}｜${request.stage}｜第${request.round}轮】\n选题：${request.taskInput.topic}\n\n`;

    if (request.agentId === "zhou_challenge") {
      return {
        content: base + "对抗质检报告：已从有用性、可读性和有趣性三个维度分析。",
        score: Math.random() * 4 + 3,  // 3-7 range
        issues: []
      };
    }

    if (request.agentId === "sun_compliance") {
      return { content: base + "合规审核：无高风险内容。", score: 0.8, issues: [] };
    }

    if (request.agentId === "wu_fact_check") {
      return { content: base + "事实核验：无重大事实错误。", score: 1.6, issues: [] };
    }

    if (request.agentId === "yan_final") {
      return { content: base + "终审：排版可通过。", score: 8, issues: [] };
    }

    return { content: base + "已完成。", issues: [] };
  }
}

export function isMockMode() {
  return process.env.LLM_MOCK === "true";
}

export function hasLlmConfig() {
  return Boolean(process.env.LLM_API_KEY && process.env.LLM_MODEL);
}

function buildUserPrompt(request: GenerateRequest) {
  const platformLine = request.platform ? `目标平台：${request.platform}` : "目标平台：全局";
  return [
    `阶段：${request.stage}`,
    `轮次：${request.round}`,
    platformLine,
    `选题：${request.taskInput.topic}`,
    `抽象声线模型：${truncateText(request.taskInput.celebrityVoiceModel, 8000)}`,
    `用户价值诉求：${truncateText(request.taskInput.userValueDemand, 3000)}`,
    `传播推广目标：${truncateText(request.taskInput.promotionGoal, 1200)}`,
    `资料来源：${formatSourcesForPrompt(request.sources)}`,
    `上游上下文：\n${truncateText(request.previousContext || "无", 18000)}`
  ].join("\n\n");
}

function formatSourcesForPrompt(sources: SourceMaterial[]) {
  const userSources = sources.filter((source) => source.origin === "user");
  const webSources = sources.filter((source) => source.origin === "web");
  const selectedSources = [...userSources, ...webSources].slice(0, getEnvNumber("LLM_MAX_SOURCES", 18));

  if (selectedSources.length === 0) {
    return "无";
  }

  return selectedSources
    .map((source) => {
      const imageLine =
        source.images && source.images.length > 0
          ? `\n图片链接：${source.images
              .slice(0, 3)
              .map((image) => image.url || image.sourceUrl)
              .filter(Boolean)
              .join("；")}`
          : "";
      return `- [${source.origin}] ${source.title}${source.url ? " " + source.url : ""}\n${truncateText(
        source.content,
        getEnvNumber("LLM_SOURCE_CHARS", 1200)
      )}${imageLine}`;
    })
    .join("\n");
}

function truncateText(value: string, maxChars: number) {
  if (value.length <= maxChars) {
    return value;
  }
  return `${value.slice(0, maxChars)}\n...[已截断 ${value.length - maxChars} 字，避免单次模型请求过长]`;
}

function getEnvNumber(name: string, fallback: number) {
  const parsed = Number(process.env[name]);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function isRetryableStatus(status: number) {
  return [408, 409, 425, 429, 500, 502, 503, 504].includes(status);
}

function isRetryableLlmError(error: unknown) {
  const message = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /terminated|timeout|abort|socket|network|fetch failed|econnreset|etimedout|undici/i.test(message);
}

function formatLlmError(error: unknown, agentId: AgentId, stage: string, attempts: number) {
  const detail = error instanceof Error ? error.message : String(error ?? "未知错误");
  const retryText = attempts > 1 ? `，已自动重试 ${attempts - 1} 次` : "";
  const agent = AGENTS[agentId];  // This uses a closed-over reference
  if (isRetryableLlmError(error)) {
    return new Error(
      `LLM 调用失败：${agent.name}/${stage} 请求连接中断或超时${retryText}仍未成功。原始错误：${truncateText(detail, 500)}`
    );
  }
  return new Error(`LLM 调用失败：${agent.name}/${stage}${retryText}。原始错误：${truncateText(detail, 500)}`);
}

async function waitBeforeRetry(attempt: number) {
  await new Promise((resolve) => setTimeout(resolve, Math.min(1500 * attempt, 5000)));
}

function parseJsonResult(raw: string): GenerateResult {
  const cleaned = raw.trim().replace(/^```json\s*/i, "").replace(/^```\s*/i, "").replace(/```$/i, "");
  try {
    const parsed = JSON.parse(cleaned) as GenerateResult;
    return {
      content: typeof parsed.content === "string" ? parsed.content : raw,
      issues: Array.isArray(parsed.issues) ? parsed.issues : [],
      score: typeof parsed.score === "number" ? parsed.score : undefined
    };
  } catch {
    return { content: raw, issues: [] };
  }
}
