import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import cors from "cors";
import dotenv from "dotenv";
import express from "express";
import { AGENTS, PLATFORM_LABELS } from "../config/agents";
import type { AgentDefinition } from "../config/agents";
import { DEFAULT_USER_VALUE_DEMAND } from "../shared/defaults";
import type { RuntimeConfig, TaskInput } from "../shared/types";
import { contractHandler, healthHandler } from "../adapters/contract";
import { hasLlmConfig, isMockMode } from "./llm";
import { discardTask, forceApproveTask, renderFinalPackageMarkdown, resetTask, runTask } from "./pipeline";
import { enabledProviders } from "./researchSkill";
import { createTask, ensureStore, listTasks, loadTask } from "./store";

dotenv.config();

const app = express();
const port = Number(process.env.PORT ?? 8787);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONFIG_DIR = path.resolve(__dirname, "../config");
const OVERRIDES_PATH = path.join(CONFIG_DIR, "agent-overrides.json");

// ── Agent override persistence ────────────────────────────────

function loadAgentOverrides(): Record<string, string> {
  try {
    if (fs.existsSync(OVERRIDES_PATH)) {
      return JSON.parse(fs.readFileSync(OVERRIDES_PATH, "utf-8"));
    }
  } catch (e) {
    console.warn("[agent-overrides] Failed to load overrides:", e);
  }
  return {};
}

function saveAgentOverride(agentId: string, systemPrompt: string): void {
  const overrides = loadAgentOverrides();
  overrides[agentId] = systemPrompt;
  fs.writeFileSync(OVERRIDES_PATH, JSON.stringify(overrides, null, 2), "utf-8");
}

function getMergedAgents(): Record<string, AgentDefinition> {
  const overrides = loadAgentOverrides();
  const merged: Record<string, AgentDefinition> = {};
  for (const [id, agent] of Object.entries(AGENTS)) {
    merged[id] = overrides[id]
      ? { ...agent, systemPrompt: overrides[id] }
      : agent;
  }
  return merged;
}

// ── Middleware ────────────────────────────────────────────────

app.use(cors());
app.use(express.json({ limit: "5mb" }));

// Contract endpoints per LLD §3
app.get("/health", healthHandler);
app.get("/contract", contractHandler);

app.get("/api/config", (_request, response) => {
  const researchProviders = enabledProviders().map((provider) => provider.id);
  const config: RuntimeConfig = {
    hasApiKey: hasLlmConfig(),
    mockMode: isMockMode(),
    model: process.env.LLM_MODEL ?? "未配置",
    baseURL: process.env.LLM_BASE_URL ?? "https://api.openai.com/v1",
    searchEnabled: researchProviders.length > 0,
    researchProviders
  };
  response.json({ config, agents: getMergedAgents(), platforms: PLATFORM_LABELS });
});

app.put("/api/config/agents/:agentId", (request, response) => {
  const { agentId } = request.params;
  const { systemPrompt } = request.body;

  if (!AGENTS[agentId as keyof typeof AGENTS]) {
    response.status(404).json({ error: 'Agent \'' + agentId + '\' not found' });
    return;
  }

  if (typeof systemPrompt !== "string" || !systemPrompt.trim()) {
    response.status(400).json({
      error: "systemPrompt is required and must be a non-empty string"
    });
    return;
  }

  try {
    saveAgentOverride(agentId, systemPrompt);
    const merged = getMergedAgents();
    response.json({ agent: merged[agentId] });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    response.status(500).json({ error: "Failed to save override: " + msg });
  }
});

app.get("/api/tasks", async (_request, response, next) => {
  try {
    response.json({ tasks: await listTasks() });
  } catch (error) {
    next(error);
  }
});

app.post("/api/tasks", async (request, response, next) => {
  try {
    const input = normalizeTaskInput(request.body as Partial<TaskInput>);
    const task = await createTask(input);
    response.status(201).json({ task });
  } catch (error) {
    next(error);
  }
});

app.get("/api/tasks/:taskId", async (request, response, next) => {
  try {
    response.json({ task: await loadTask(request.params.taskId) });
  } catch (error) {
    next(error);
  }
});

app.post("/api/tasks/:taskId/run", async (request, response, next) => {
  try {
    const task = await loadTask(request.params.taskId);
    runTask(request.params.taskId).catch((err) => {
      console.error(`[task ${request.params.taskId}] background run failed:`, err);
    });
    response.json({ task });
  } catch (error) {
    next(error);
  }
});

app.post("/api/tasks/:taskId/force-approve", async (request, response, next) => {
  try {
    const task = await forceApproveTask(request.params.taskId);
    response.json({ task });
  } catch (error) {
    next(error);
  }
});

app.post("/api/tasks/:taskId/reset", async (request, response, next) => {
  try {
    const task = await resetTask(request.params.taskId);
    response.json({ task });
  } catch (error) {
    next(error);
  }
});

app.post("/api/tasks/:taskId/discard", async (request, response, next) => {
  try {
    const task = await discardTask(request.params.taskId);
    response.json({ task });
  } catch (error) {
    next(error);
  }
});

app.get("/api/tasks/:taskId/export.md", async (request, response, next) => {
  try {
    const task = await loadTask(request.params.taskId);
    response.setHeader("Content-Type", "text/markdown; charset=utf-8");
    response.send(renderFinalPackageMarkdown(task));
  } catch (error) {
    next(error);
  }
});

app.use((error: unknown, _request: express.Request, response: express.Response, _next: express.NextFunction) => {
  const message = error instanceof Error ? error.message : "未知错误";
  response.status(400).json({ error: message });
});

(async () => {
  await ensureStore();
  app.listen(port, () => {
    console.log(`API server listening on http://localhost:${port}`);
  });
})();

function normalizeTaskInput(input: Partial<TaskInput>): TaskInput {
  if (!input.topic?.trim()) {
    throw new Error("选题不能为空");
  }
  if (!input.celebrityVoiceModel?.trim()) {
    throw new Error("抽象声线模型不能为空");
  }
  if (!input.promotionGoal?.trim()) {
    throw new Error("传播推广目标不能为空");
  }

  return {
    topic: input.topic.trim(),
    celebrityVoiceModel: input.celebrityVoiceModel.trim(),
    userValueDemand: DEFAULT_USER_VALUE_DEMAND,
    promotionGoal: input.promotionGoal.trim(),
    targetPlatforms: input.targetPlatforms?.length
      ? input.targetPlatforms
      : ["wechat", "xiaohongshu", "toutiao"],
    sourceMaterials: (input.sourceMaterials ?? []).map((source, index) => ({
      id: source.id || `user-${index + 1}`,
      title: source.title || `用户资料 ${index + 1}`,
      content: source.content || "",
      url: source.url,
      origin: "user"
    })),
    searchEnabled: Boolean(input.searchEnabled)
  };
}
