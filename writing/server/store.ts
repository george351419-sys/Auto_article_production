import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { DEFAULT_USER_VALUE_DEMAND } from "../shared/defaults";
import type { AgentOutput, FinalPackage, TaskInput, TaskState } from "../shared/types";

const rootDir = process.cwd();

export function getDataDir() {
  return path.resolve(rootDir, process.env.DATA_DIR ?? "data/tasks");
}

function taskDir(taskId: string) {
  return path.join(getDataDir(), taskId);
}

function statePath(taskId: string) {
  return path.join(taskDir(taskId), "state.json");
}

export async function ensureStore() {
  await mkdir(getDataDir(), { recursive: true });
}

export async function createTask(input: TaskInput): Promise<TaskState> {
  await ensureStore();
  const normalizedInput: TaskInput = {
    ...input,
    userValueDemand: DEFAULT_USER_VALUE_DEMAND
  };
  const id = `task-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const now = new Date().toISOString();
  const state: TaskState = {
    id,
    input: normalizedInput,
    status: "draft",
    createdAt: now,
    updatedAt: now,
    currentRound: 0,
    outputs: [],
    scoreReports: [],
    feedbackRecords: []
  };
  await mkdir(taskDir(id), { recursive: true });
  await saveTask(state);
  await writeFile(path.join(taskDir(id), "input.json"), JSON.stringify(normalizedInput, null, 2), "utf8");
  return state;
}

export async function listTasks(): Promise<TaskState[]> {
  await ensureStore();
  const entries = await readdir(getDataDir(), { withFileTypes: true });
  const tasks = await Promise.all(
    entries
      .filter((entry) => entry.isDirectory())
      .map(async (entry) => {
        try {
          return await loadTask(entry.name);
        } catch {
          return undefined;
        }
      })
  );
  return tasks
    .filter((task): task is TaskState => Boolean(task))
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function loadTask(taskId: string): Promise<TaskState> {
  const raw = await readFile(statePath(taskId), "utf8");
  const parsed = JSON.parse(raw) as TaskState;
  return {
    ...parsed,
    feedbackRecords: parsed.feedbackRecords ?? []
  };
}

export async function saveTask(state: TaskState): Promise<void> {
  await mkdir(taskDir(state.id), { recursive: true });
  const nextState = { ...state, updatedAt: new Date().toISOString() };
  await writeFile(statePath(state.id), JSON.stringify(nextState, null, 2), "utf8");
}

export async function saveAgentOutput(taskId: string, output: AgentOutput): Promise<void> {
  const dir = path.join(taskDir(taskId), `round-${output.round}`);
  await mkdir(dir, { recursive: true });
  await writeFile(
    path.join(dir, `${output.stage}-${output.agentId}.json`),
    JSON.stringify(output, null, 2),
    "utf8"
  );
}

export async function saveFinalPackage(taskId: string, finalPackage: FinalPackage): Promise<void> {
  await writeFile(
    path.join(taskDir(taskId), "final-package.json"),
    JSON.stringify(finalPackage, null, 2),
    "utf8"
  );
}

export async function saveExportMarkdown(taskId: string, markdown: string): Promise<void> {
  await writeFile(path.join(taskDir(taskId), "final-package.md"), markdown, "utf8");
}
