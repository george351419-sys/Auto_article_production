import { AGENTS, ISSUE_OWNER_MAP, PLATFORM_LABELS } from "../config/agents";
import type {
  AgentId,
  AgentIssue,
  AgentOutput,
  FeedbackRecord,
  FinalPackage,
  ImageAsset,
  IssueType,
  Platform,
  PlatformPackage,
  ScoreReport,
  SourceMaterial,
  TaskState
} from "../shared/types";
import { normalizeScoreValue } from "../shared/scoring";
import { collectSources } from "./search";
import { createLlmClient } from "./llm";
import { buildPlatformImagePrompts, PLATFORM_VISUAL_SPECS, preparePlatformImages } from "./imageGeneration";
import { loadTask, saveAgentOutput, saveExportMarkdown, saveFinalPackage, saveTask } from "./store";
import fs from "node:fs";
import path from "node:path";

const MAX_ROUNDS = 5;
const EDITOR_PASS_SCORE = 7;

export async function runTask(taskId: string): Promise<TaskState> {
  let state = await loadTask(taskId);
  const startRound = getStartRoundForRun(state);
  state = prepareStateForRun(state, startRound);
  await saveTask(state);

  try {
    createLlmClient();
    const sources = await collectSources(
      state.input.topic,
      state.input.sourceMaterials,
      state.input.searchEnabled
    );
    const usableSources = sources.filter(isUsableSource);
    if (usableSources.length === 0) {
      state.status = "needs_material";
      state.error =
        "未取得可用于写作的真实素材。请补充用户资料，或开启/配置更多检索源后重新运行；系统已阻止生成空泛立意和文章。";
      await saveTask(state);
      return state;
    }

    for (let round = startRound; round <= MAX_ROUNDS; round += 1) {
      state.currentRound = round;
      await saveTask(state);

      await runWriterPass(taskId, state, sources, round);
      const report = await runEditorPass(taskId, state, sources, round);
      state.scoreReports.push(report);
      await saveTask(state);

      if (report.passed) {
        const finalPackage = await runOperatorPass(taskId, state, sources, round);
        state.finalPackage = finalPackage;
        state.status = "approved";
        await saveFinalPackage(taskId, finalPackage);
        await saveExportMarkdown(taskId, renderFinalPackageMarkdown(state));
        await saveTask(state);
        return state;
      }

      if (round < MAX_ROUNDS) {
        const feedback = await runFeedbackPass(taskId, state, sources, round, report);
        state.feedbackRecords.push(feedback);
        await saveTask(state);
      }
    }

    state.status = "needs_human";
    state.error = `已达到默认 5 轮回流上限，仍未达到 ${EDITOR_PASS_SCORE} 分准入线，需要人工处理。`;
    await saveTask(state);
    return state;
  } catch (error) {
    state.status = error instanceof Error && error.message.includes("LLM_API_KEY") ? "needs_config" : "failed";
    state.error = error instanceof Error ? error.message : "未知错误";
    await saveTask(state);
    return state;
  }
}

function getStartRoundForRun(state: TaskState) {
  const completedRound = Math.max(0, ...state.scoreReports.map((report) => report.round));
  const latestCurrentRoundReport = state.scoreReports.find((report) => report.round === state.currentRound);
  const shouldRecoverCurrentRound = state.status === "failed" || state.status === "running";

  if (shouldRecoverCurrentRound && state.currentRound > completedRound) {
    return Math.max(1, completedRound + 1);
  }

  if (shouldRecoverCurrentRound && latestCurrentRoundReport?.passed && !state.finalPackage) {
    return Math.max(1, latestCurrentRoundReport.round);
  }

  return Math.max(1, state.currentRound + 1);
}

function prepareStateForRun(state: TaskState, startRound: number): TaskState {
  return {
    ...state,
    status: "running",
    error: undefined,
    finalPackage: undefined,
    currentRound: Math.min(state.currentRound, startRound - 1),
    outputs: state.outputs.filter((output) => output.round < startRound),
    scoreReports: state.scoreReports.filter((report) => report.round < startRound),
    feedbackRecords: state.feedbackRecords.filter((feedback) => feedback.round < startRound)
  };
}

function isUsableSource(source: SourceMaterial) {
  return Boolean(source.content.trim()) && !source.url?.startsWith("local://research/no-results");
}

async function runWriterPass(
  taskId: string,
  state: TaskState,
  sources: SourceMaterial[],
  round: number
) {
  const stages: Array<[AgentId, string]> = [
    ...(round === 1 ? ([["zhang_material", "base-material"]] as Array<[AgentId, string]>) : []),
    ["zhao_position", round === 1 ? "positioning" : "review-positioning"],
    ["zhang_material", round === 1 ? "deep-material" : "review-material"],
    ["li_article", round === 1 ? "draft" : "rewrite-draft"],
    ["qian_human", round === 1 ? "humanize" : "review-humanize"],
    ["liu_style", round === 1 ? "voice-polish" : "review-voice-polish"]
  ];

  for (const [agentId, stage] of stages) {
    const output = await generateOutput(taskId, state, sources, round, agentId, stage);
    state.outputs.push(output);
    await saveTask(state);
  }
}

async function runEditorPass(
  taskId: string,
  state: TaskState,
  sources: SourceMaterial[],
  round: number
): Promise<ScoreReport> {
  const editorStages: Array<[AgentId, string, number]> = [
    ["wu_fact_check", "fact-check", 2],
    ["sun_compliance", "compliance-check", 1],
    ["zhou_challenge", "challenge-review", 7]
  ];

  const outputs: AgentOutput[] = [];
  for (const [agentId, stage, maxScore] of editorStages) {
    const output = await generateOutput(taskId, state, sources, round, agentId, stage, undefined, maxScore);
    output.maxScore = maxScore;
    output.issues = output.issues.map(assignIssueOwner);
    state.outputs.push(output);
    outputs.push(output);
    await saveTask(state);
  }

  const totalScore = Number(
    Math.min(10, outputs.reduce((sum, output) => sum + (output.normalizedScore ?? output.score ?? 0), 0)).toFixed(1)
  );
  return {
    round,
    totalScore,
    passed: totalScore >= EDITOR_PASS_SCORE,
    maxScore: 10,
    outputs,
    createdAt: new Date().toISOString()
  };
}

async function runFeedbackPass(
  taskId: string,
  state: TaskState,
  sources: SourceMaterial[],
  round: number,
  report: ScoreReport
): Promise<FeedbackRecord> {
  const assignedIssues = buildAssignedIssues(report);
  const editorSummary = await generateOutput(
    taskId,
    state,
    sources,
    round,
    "editor_supervisor",
    "editor-supervisor",
    undefined,
    undefined,
    assignedIssues,
    "editor"
  );
  editorSummary.issues = assignedIssues;
  state.outputs.push(editorSummary);
  await saveTask(state);

  const writerDispatch = await generateOutput(
    taskId,
    state,
    sources,
    round,
    "writer_supervisor",
    "writer-supervisor",
    undefined,
    undefined,
    assignedIssues,
    "writer"
  );
  writerDispatch.issues = assignedIssues;
  state.outputs.push(writerDispatch);
  await saveTask(state);

  return {
    round,
    editorSummary,
    writerDispatch,
    assignedIssues,
    rerunStages: [
      "review-positioning",
      "review-material",
      "rewrite-draft",
      "review-humanize",
      "review-voice-polish"
    ],
    createdAt: new Date().toISOString()
  };
}

const OPERATOR_MAX_ROUNDS = 3;
const OPERATOR_PASS_SCORE = 8;

async function downloadImagesToLocal(
  images: ImageAsset[],
  taskId: string,
  dataDir: string = process.env.DATA_DIR || "data"
): Promise<ImageAsset[]> {
  /** Download all images with HTTP URLs to local files and set localPath. */
  const assetsDir = path.join(dataDir, "assets", taskId);
  await fs.promises.mkdir(assetsDir, { recursive: true });
  return Promise.all(
    images.map(async (img) => {
      if (!img.url || !img.url.startsWith("http") || img.url.startsWith("prompt://") || img.localPath) return img;
      try {
        const resp = await fetch(img.url);
        if (!resp.ok) return img;
        const buf = Buffer.from(await resp.arrayBuffer());
        const ct = resp.headers.get("content-type") || "";
        let ext = "jpg";
        if (ct.includes("png")) ext = "png";
        else if (ct.includes("webp")) ext = "webp";
        else if (ct.includes("gif")) ext = "gif";
        else if (ct.includes("jpeg")) ext = "jpg";
        const fname = `${img.id || Date.now()}.${ext}`;
        const fp = path.join(assetsDir, fname);
        await fs.promises.writeFile(fp, buf);
        return { ...img, localPath: fp };
      } catch (e) {
        console.warn(`[downloadImages] Failed ${img.url}: ${e}`);
        return img;
      }
    })
  );
}

async function runOperatorPass(
  taskId: string,
  state: TaskState,
  sources: SourceMaterial[],
  round: number
): Promise<FinalPackage> {
  const platforms: PlatformPackage[] = [];

  // Collect all available images from sources before operator phase
  const sourceImages = collectAllSourceImages(sources);

  for (const platform of state.input.targetPlatforms) {
    const imagePrompts = buildPlatformImagePrompts(state.input.topic, platform);
    let images = await preparePlatformImages(state.input.topic, platform, sources, imagePrompts);
    images = await downloadImagesToLocal(images, taskId);

    // Merge source images with generated images for the LLM context
    const platformImages = [
      ...sourceImages.filter((img) => img.url),
      ...images
    ].slice(0, 5);

    const layout = await generateOutput(
      taskId, state, platformImages.length > 0 ? injectPlatformImages(sources, platformImages) : sources,
      round, "chen_layout", "platform-layout", platform
    );
    const metadata = await generateOutput(
      taskId, state, platformImages.length > 0 ? injectPlatformImages(sources, platformImages) : sources,
      round, "zhang_publish", "platform-metadata", platform
    );
    state.outputs.push(layout, metadata);
    await saveTask(state);

    // 标题大师根据排版成品和元数据生成优化标题
    const titleMasterSources = sources;
    const titleOutput = await generateOutput(
      taskId, state, titleMasterSources,
      round, "title_master", "title-optimization", platform
    );
    state.outputs.push(titleOutput);
    await saveTask(state);

    platforms.push(buildPlatformPackage(platform, layout.content, metadata.content, state.input.topic, images, imagePrompts, titleOutput.content));
  }

  // Yan_final loop: up to OPERATOR_MAX_ROUNDS with scoring
  let operatorRound = 1;
  let finalReview: AgentOutput | undefined;

  while (operatorRound <= OPERATOR_MAX_ROUNDS) {
    finalReview = await generateOutput(
      taskId, state, sources,
      round, "yan_final",
      operatorRound === 1 ? "final-review" : "review-operator-round-" + operatorRound
    );
    finalReview.subRound = operatorRound;
    state.outputs.push(finalReview);
    await saveTask(state);

    const reviewScore = extractOperatorScore(finalReview);
    const reviewIssues = finalReview.issues;

    if (reviewScore >= OPERATOR_PASS_SCORE || reviewIssues.length === 0) {
      // Passed
      break;
    }

    if (operatorRound >= OPERATOR_MAX_ROUNDS) {
      state.status = "needs_human";
      state.error = "运营侧已循环 " + operatorRound + " 轮仍未达到 " + OPERATOR_PASS_SCORE + " 分准入线，需要人工处理排版和元数据问题。";
      break;
    }

    // Route issues back to specific operators
    const layoutIssues = reviewIssues.filter(
      (issue) => issue.ownerAgentId === "chen_layout" || (issue.issueType as string) === "layout" || (issue.issueType as string) === "image"
    );
    const metadataIssues = reviewIssues.filter(
      (issue) => issue.ownerAgentId === "zhang_publish" || (issue.issueType as string) === "metadata"
    );
    const titleIssues = reviewIssues.filter(
      (issue) => issue.ownerAgentId === "title_master" || issue.ownerAgentId === "zhang_publish" || (issue.issueType as string) === "title" || (issue.issueType as string) === "appeal"
    );

    for (let pi = 0; pi < platforms.length; pi++) {
      const platform = state.input.targetPlatforms[pi];
      const platformPkg = platforms[pi];

      if (layoutIssues.length > 0) {
        const relayout = await generateOutput(
          taskId, state, sources,
          round, "chen_layout",
          "relayout-round-" + operatorRound + "-" + platform,
          platform, undefined, layoutIssues
        );
        relayout.subRound = operatorRound;
        state.outputs.push(relayout);
        platformPkg.formattedArticle = relayout.content;
      }

      if (metadataIssues.length > 0) {
        const remeta = await generateOutput(
          taskId, state, sources,
          round, "zhang_publish",
          "remetadata-round-" + operatorRound + "-" + platform,
          platform, undefined, metadataIssues
        );
        remeta.subRound = operatorRound;
        state.outputs.push(remeta);
        const imagePrompts = buildPlatformImagePrompts(state.input.topic, platform);
        const images = await preparePlatformImages(state.input.topic, platform, sources, imagePrompts);
        const article = layoutIssues.length > 0
          ? (state.outputs.find(o => o.stage === "relayout-round-" + operatorRound + "-" + platform)?.content ?? platformPkg.formattedArticle)
          : platformPkg.formattedArticle;
        // 标题大师同步优化标题
        const retitle = await generateOutput(
          taskId, state, sources,
          round, "title_master",
          "retitle-round-" + operatorRound + "-" + platform,
          platform
        );
        retitle.subRound = operatorRound;
        state.outputs.push(retitle);
        platforms[pi] = buildPlatformPackage(platform, article, remeta.content, state.input.topic, images, imagePrompts, retitle.content);
      }

      await saveTask(state);
    }

    operatorRound++;
  }

  return {
    platforms,
    finalReview: finalReview ?? await generateOutput(taskId, state, sources, round, "yan_final", "final-review"),
    createdAt: new Date().toISOString()
  };
}

// ── Manual operator actions for needs_human state ──

export async function forceApproveTask(taskId: string): Promise<TaskState> {
  const state = await loadTask(taskId);
  state.status = "running";
  state.error = undefined;
  await saveTask(state);
  forceApproveTaskAsync(taskId).catch((err) => {
    console.error(`[task ${taskId}] force-approve failed:`, err);
  });
  return state;
}

async function forceApproveTaskAsync(taskId: string): Promise<void> {
  const state = await loadTask(taskId);
  try {
    createLlmClient();
    const sources = await collectSources(
      state.input.topic,
      state.input.sourceMaterials,
      state.input.searchEnabled
    );
    const round = Math.max(1, state.currentRound);
    const finalPackage = await runOperatorPass(taskId, state, sources, round);
    state.finalPackage = finalPackage;
    state.status = "approved";
    state.error = undefined;
    await saveFinalPackage(taskId, finalPackage);
    await saveExportMarkdown(taskId, renderFinalPackageMarkdown(state));
    await saveTask(state);
  } catch (err) {
    state.status = "needs_human";
    state.error = `强制通过失败：${err instanceof Error ? err.message : String(err)}`;
    await saveTask(state);
    throw err;
  }
}

export async function resetTask(taskId: string): Promise<TaskState> {
  const state = await loadTask(taskId);
  state.status = "running";
  state.currentRound = 0;
  state.outputs = [];
  state.scoreReports = [];
  state.feedbackRecords = [];
  state.finalPackage = undefined;
  state.error = undefined;
  await saveTask(state);
  runTask(taskId).catch((err) => {
    console.error(`[task ${taskId}] reset run failed:`, err);
  });
  return state;
}

export async function discardTask(taskId: string): Promise<TaskState> {
  const state = await loadTask(taskId);
  state.status = "discarded";
  state.error = "已被人工放弃";
  await saveTask(state);
  return state;
}

function collectAllSourceImages(sources: SourceMaterial[]): ImageAsset[] {
  const seen = new Set<string>();
  return sources.flatMap((s) => s.images ?? []).filter((img) => {
    if (!img.url || seen.has(img.url)) return false;
    seen.add(img.url);
    return true;
  });
}

function injectPlatformImages(sources: SourceMaterial[], platformImages: ImageAsset[]): SourceMaterial[] {
  if (platformImages.length === 0) return sources;
  return [
    ...sources,
    {
      id: "__platform_images__",
      title: "可用图片资产（供排版和封面使用）",
      content: platformImages.map((img) =>
        "图片：" + (img.title || "未命名") + " - ![" + (img.title || "图片") + "](" + img.url + ")" + (img.placement ? "（" + img.placement + "）" : "")
      ).join("\n"),
      origin: "web" as const,
      images: platformImages
    }
  ];
}

function extractOperatorScore(output: AgentOutput): number {
  if (typeof output.score === "number" && Number.isFinite(output.score) && output.score <= 10) {
    return output.score;
  }
  if (typeof output.normalizedScore === "number" && Number.isFinite(output.normalizedScore)) {
    return output.normalizedScore;
  }
  if (output.issues.length > 0) {
    const penalty = output.issues.reduce((sum, issue) => {
      if (issue.severity === "high") return sum + 2.5;
      if (issue.severity === "medium") return sum + 1.5;
      return sum + 0.8;
    }, 0);
    return Math.max(0, Math.min(10, 10 - penalty));
  }
  return 10;
}

async function generateOutput(
  taskId: string,
  state: TaskState,
  sources: SourceMaterial[],
  round: number,
  agentId: AgentId,
  stage: string,
  platform?: Platform,
  maxScore?: number,
  overrideIssues?: AgentIssue[],
  supervisorType?: "editor" | "writer"
): Promise<AgentOutput> {
  const client = createLlmClient();
  const context = buildContext(state, round, agentId, overrideIssues, sources);
  const result = await client.generate({
    agentId,
    stage,
    taskInput: state.input,
    round,
    previousContext: context,
    sources,
    platform,
    maxScore
  });
  const issues = normalizeIssues(overrideIssues ?? result.issues ?? []);
  const normalizedScore =
    maxScore === undefined ? undefined : normalizeScoreValue(result.score, maxScore, issues);

  const output: AgentOutput = {
    id: `${stage}-${agentId}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    round,
    agentId,
    stage,
    status: "completed",
    content: result.content,
    issues,
    rawScore: typeof result.score === "number" && Number.isFinite(result.score) ? result.score : undefined,
    normalizedScore,
    score: normalizedScore,
    maxScore,
    supervisorType,
    sources,
    createdAt: new Date().toISOString()
  };
  await saveAgentOutput(taskId, output);
  return output;
}

function buildContext(state: TaskState, round: number, agentId: AgentId, overrideIssues: AgentIssue[] = [], sources: SourceMaterial[] = []) {
  const recentOutputs = selectContextOutputs(state, round, agentId)
    .slice(-14)
    .map(renderContextOutput);

  const feedbackContext =
    overrideIssues.length > 0
      ? [
          "## 本轮统一退稿问题（只列出 TOP 3 阻塞性问题）",
          ...overrideIssues.map(
            (issue) =>
              `- ${issue.issueType}/${issue.severity}/${issue.ownerAgentId ?? "未分配"}：${issue.location} ${issue.description}；整改：${issue.suggestion}`
          )
        ].join("\n")
      : "";

  // Add image assets context for operator agents that place images into articles
  const imageContext = buildImageContext(agentId, sources);

  // Add scoring anchor for cross-round consistency
  const scoringAnchor = buildScoringAnchor(state, round, agentId);

  return [...recentOutputs, feedbackContext, imageContext, scoringAnchor].filter(Boolean).join("\n\n");
}

function buildScoringAnchor(state: TaskState, round: number, agentId: AgentId): string {
  if (round <= 1) return "";
  
  // For editors: show previous round's score breakdown as a reference anchor
  if (isEditorAgent(agentId)) {
    const prevRound = state.scoreReports.filter((r) => r.round === round - 1);
    if (prevRound.length === 0) return "";
    const prev = prevRound[prevRound.length - 1];
    const lines = [
      "## 上一轮评分参考（评分标准一致性参考）",
      "上一轮总分：" + prev.totalScore + "/" + prev.maxScore,
      ...prev.outputs.map((o) => {
        const agent = AGENTS[o.agentId];
        return "- " + (agent?.name ?? o.agentId) + "：" + (o.normalizedScore ?? o.score ?? "?") + "/" + o.maxScore + (o.issues.length > 0 ? "（问题：" + o.issues.map((i) => i.description).slice(0, 2).join("; ") + "）" : "");
      }),
      "注意：以上为上一轮分数参考。请在保持评分标准一致的前提下，对本轮内容独立评分。"
    ];
    return lines.join("\n");
  }
  
  // For writers (round 2+): show historical score breakdown to guide improvement direction
  if (AGENTS[agentId]?.group === "writer") {
    const prevReports = state.scoreReports.filter((r) => r.round < round);
    if (prevReports.length === 0) return "";
    const latest = prevReports[prevReports.length - 1];
    const lines = [
      "## 历史评分参考（指导本轮改进方向）",
      "最近一轮总分：" + latest.totalScore + "/" + latest.maxScore + "（需 >= 7 分通过）",
      ...latest.outputs.map((o) => {
        const agent = AGENTS[o.agentId];
        return "- " + (agent?.name ?? o.agentId) + "：" + (o.normalizedScore ?? o.score ?? "?") + "/" + o.maxScore + (o.issues.length > 0 ? " — " + o.issues.map((i) => i.description).join("; ") : " — 无问题");
      }),
      "本轮改进重点：优先修复以上低分维度暴露的问题。"
    ];
    return lines.join("\n");
  }
  
  return "";
}

function buildImageContext(agentId: AgentId, sources: SourceMaterial[]): string {
  if (agentId !== "chen_layout" && agentId !== "zhang_publish") {
    return "";
  }

  // 小黑配图技能 (xiaohei-article-illustrator) 配图源
  // 陈排版 Agent 应按照六步工作流中的步骤二（图片来源决策）和步骤四（图片插入）使用以下图片
  const allImages = sources
    .flatMap((source) => source.images ?? [])
    .filter((image) => image.url)
    .map((image, index) => `  ${index + 1}. ![${image.title || "图片" + (index + 1)}](${image.url})${image.placement ? "（用途：" + image.placement + "）" : ""}`)
    .join("\n");

  if (!allImages) {
    return "## 可用图片资产\n（无可用真实图片，请在排版稿中用图片提示词标记待生成图片位置）";
  }

  return ["## 可用图片资产（来自素材搜索结果）", "以下图片可用于排版插入和封面选择：", allImages, "", "使用规则：封面图放文章开头，正文每 2-3 个小节插入一张配图；如果真实图片不够，用 prompt:// 提示词补全。"].join("\n");
}

function selectContextOutputs(state: TaskState, round: number, agentId: AgentId) {
  if (agentId === "editor_supervisor" || agentId === "writer_supervisor") {
    return state.outputs.filter((output) => output.round === round && isEditorAgent(output.agentId));
  }

  if (isEditorAgent(agentId)) {
    return state.outputs.filter((output) => output.round === round && isWriterProductionAgent(output.agentId));
  }

  if (AGENTS[agentId].group === "writer") {
    const latestFeedbackRound = Math.max(0, ...state.feedbackRecords.map((feedback) => feedback.round));
    return state.outputs.filter(
      (output) =>
        output.round === round ||
        (latestFeedbackRound > 0 &&
          output.round === latestFeedbackRound &&
          (output.supervisorType === "editor" || output.supervisorType === "writer" || output.stage === "voice-polish"))
    );
  }

  // For operator agents: show other operator outputs (layout/metadata/titles)
  if (AGENTS[agentId]?.group === "operator") {
    return state.outputs.filter((output) => output.round === round && (output.agentId === "chen_layout" || output.agentId === "zhang_publish" || output.agentId === "title_master"));
  }

  return state.outputs.filter((output) => output.round === round && (isWriterProductionAgent(output.agentId) || isEditorAgent(output.agentId)));
}

function renderContextOutput(output: AgentOutput) {
  const scoreLine =
    typeof output.normalizedScore === "number"
      ? `\n评分：${output.normalizedScore}/${output.maxScore ?? ""}${
          typeof output.rawScore === "number" && output.rawScore !== output.normalizedScore
            ? `（原始：${output.rawScore}）`
            : ""
        }`
      : "";
  const issueLine =
    output.issues.length > 0
      ? `\n问题：${output.issues
          .map(
            (issue) =>
              `${issue.issueType}/${issue.severity}/${issue.ownerAgentId ?? "未分配"}：${issue.location} ${issue.description} -> ${issue.suggestion}`
          )
          .join("\n")}`
      : "";
  return `## ${AGENTS[output.agentId].name} / ${output.stage}${scoreLine}\n${output.content}${issueLine}`;
}

function isEditorAgent(agentId: AgentId) {
  return agentId === "wu_fact_check" || agentId === "sun_compliance" || agentId === "zhou_challenge";
}

function isWriterProductionAgent(agentId: AgentId) {
  return (
    agentId === "zhang_material" ||
    agentId === "zhao_position" ||
    agentId === "li_article" ||
    agentId === "qian_human" ||
    agentId === "liu_style"
  );
}

function assignIssueOwner(issue: AgentIssue): AgentIssue {
  const issueType = normalizeIssueType(issue.issueType);
  return {
    ...issue,
    issueType,
    ownerAgentId: isAgentId(issue.ownerAgentId) ? issue.ownerAgentId : ISSUE_OWNER_MAP[issueType]
  };
}

function buildAssignedIssues(report: ScoreReport): AgentIssue[] {
  const issues = report.outputs.flatMap((output) => output.issues).map(assignIssueOwner);
  const seen = new Set<string>();
  const deduped = issues.filter((issue) => {
    const key = `${issue.issueType}|${issue.location}|${issue.description}|${issue.ownerAgentId}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
  // 按严重度排序，只保留 TOP 3 阻塞性问题，避免写手过度修正
  const severityOrder: Record<string, number> = { high: 0, medium: 1, low: 2 };
  return deduped.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]).slice(0, 5);
}

function normalizeIssues(issues: AgentIssue[]): AgentIssue[] {
  return issues.map((issue, index) => {
    const issueType = normalizeIssueType(issue.issueType);
    return {
      ...issue,
      id: issue.id || `issue-${index + 1}`,
      issueType,
      severity: normalizeSeverity(issue.severity),
      location: issue.location || "未标注位置",
      description: issue.description || "未提供问题描述",
      suggestion: issue.suggestion || "请按对应 Agent 职责补充整改建议",
      ownerAgentId: isAgentId(issue.ownerAgentId) ? issue.ownerAgentId : ISSUE_OWNER_MAP[issueType]
    };
  });
}

function isAgentId(value: unknown): value is AgentId {
  return typeof value === "string" && value in AGENTS;
}

function normalizeIssueType(issueType: unknown): IssueType {
  const raw = String(issueType ?? "").toLowerCase();
  if (/compliance|risk|合规|风险|敏感|夸大|侵权|限流|引战|绝对化/.test(raw)) {
    return "compliance";
  }
  if (/title|click|appeal|标题|吸引|引流|爆款|有趣|interest|钩子|记忆点|分享/.test(raw)) {
    return "appeal";
  }
  if (/structure|logic|结构|逻辑|闭环|立意/.test(raw)) {
    return "structure";
  }
  if (/density|evidence|干货|空话|素材|论据|信息量|有用|useful|实用|价值|行动/.test(raw)) {
    return "density";
  }
  if (/readability|retention|阅读|留存|体验|节奏|可读|难懂|流畅/.test(raw)) {
    return "readability";
  }
  if (/style|voice|tone|风格|声线|调性|ip/.test(raw)) {
    return "style";
  }
  return "fact";
}

function normalizeSeverity(severity: unknown): AgentIssue["severity"] {
  const raw = String(severity ?? "").toLowerCase();
  if (/critical|严重|高|high/.test(raw)) {
    return "high";
  }
  if (/中|medium|moderate/.test(raw)) {
    return "medium";
  }
  return "low";
}

function buildPlatformPackage(
  platform: Platform,
  formattedArticle: string,
  metadata: string,
  topic: string,
  images: PlatformPackage["images"],
  imagePrompts: string[],
  titleMasterContent?: string
): PlatformPackage {
  // Defensive: ensure metadata is a string before .match() calls
  if (typeof metadata !== "string") { metadata = String(metadata ?? ""); }
  const label = PLATFORM_LABELS[platform];
  const spec = PLATFORM_VISUAL_SPECS[platform];

  // Extract cover image and titles - use title_master output if available
  const coverMatch = metadata.match(/cover_image:\s*!\[([^\]]*)\]\(([^)]+)\)/);
  const titlesFromMeta = titleMasterContent
    ? extractTitlesFromTitleMaster(titleMasterContent, platform, topic)
    : extractTitlesFromMetadata(metadata, topic, label);
  const summaryFromMeta = extractSummaryFromMetadata(metadata, topic, label);
  const tagsFromMeta = extractTagsFromMetadata(metadata, platform);
  const keywordsFromMeta = extractKeywordsFromMetadata(metadata);
  const pinnedFromMeta = extractPinnedFromMetadata(metadata);

  // Build cover plan with actual cover image
  const coverPlanParts = [
    metadata,
    "平台视觉规则：" + spec.styleGuide,
    "封面比例：" + spec.coverAspectRatio + "；正文图片比例：" + spec.inlineAspectRatio + "；建议图片数：" + spec.imageCount,
    "封面建议：强标题 + 明确主体 + 移动端缩略图可读，适合" + label + "。"
  ];

  if (coverMatch) {
    const coverImage = images.find((img) => img.url === coverMatch[2]);
    coverPlanParts.push("选定封面图：![" + coverMatch[1] + "](" + coverMatch[2] + ")" + (coverImage ? "（来源：" + coverImage.origin + "）" : ""));
  } else {
    const firstImage = images.find((img) => img.url);
    if (firstImage) {
      coverPlanParts.push("自动选用首张图片作为封面：![" + (firstImage.title || "封面") + "](" + firstImage.url + ")");
    } else if (images.find((img) => img.prompt)) {
      coverPlanParts.push("未取得真实图片，请按图片生成提示词生成并替换封面。");
    } else {
      coverPlanParts.push("未取得可用图片，请按图片生成提示词补图。");
    }
  }

  if (images.length > 0) {
    coverPlanParts.push(
      "可用图片：",
      ...images.map((image) => "  " + (image.placement || "image") + "=" + (image.url || image.prompt || "待生成"))
    );
  } else {
    coverPlanParts.push("未取得可用图片，请按图片生成提示词补图。");
  }

  return {
    platform,
    formattedArticle,
    titles: titlesFromMeta,
    summary: summaryFromMeta,
    keywords: keywordsFromMeta,
    tags: tagsFromMeta,
    images,
    coverPlan: coverPlanParts.join("\n"),
    imagePrompts,
    pinnedComment: pinnedFromMeta
  };
}

function extractTitlesFromMetadata(metadata: string, topic: string, label: string): string[] {
  // Try to extract titles marked with "title A:", "Title 1:", or "标题A:" patterns
  const titleMatches = [...metadata.matchAll(/(?:标题[1-9ABCDEFGH]?|Title\s*[1-9]?)[：:]\s*(.+)/g)];
  if (titleMatches.length >= 2) {
    return titleMatches.map((m) => m[1].trim());
  }
  if (titleMatches.length === 1) {
    return [
      titleMatches[0][1].trim(),
      "别再空谈趋势，" + label + "读者真正关心的是这个",
      topic + "不是效率问题，而是判断力问题"
    ];
  }
  return [
    topic + "：真正该抓住的3个变化",
    "别再空谈趋势，" + label + "读者真正关心的是这个",
    topic + "不是效率问题，而是判断力问题"
  ];
}

function extractTitlesFromTitleMaster(titleMasterContent: string, platform: Platform, topic: string): string[] {
  const label = PLATFORM_LABELS[platform];
  const sections = titleMasterContent.split("\n## ");
  const platformSection = sections.find((s) => s.includes(label));
  if (!platformSection) {
    const lines = titleMasterContent.split("\n").filter((line) => /^\d+\.\s*\S/.test(line.trim()));
    if (lines.length >= 2) {
      return lines.map((line) => line.replace(/^\d+\.\s*/, "").trim().split(/\s*-\s*公式/)[0].trim());
    }
    return [
      topic + "：真正该抓住的3个变化",
      "别再空谈趋势，" + label + "读者真正关心的是这个",
      topic + "不是效率问题，而是判断力问题"
    ];
  }
  const rawLines = platformSection.split("\n");
  const titleLines = rawLines
    .filter((line) => {
      const trimmed = line.trim();
      return /^\d+\./.test(trimmed);
    })
    .map((line) => {
      const trimmed = line.trim().replace(/^\d+\.\s*/, "");
      return trimmed.split(/\s*-\s*公式/)[0].trim();
    });
  if (titleLines.length >= 2) {
    return titleLines;
  }
  return [
    topic + "：真正该抓住的3个变化",
    "别再空谈趋势，" + label + "读者真正关心的是这个",
    topic + "不是效率问题，而是判断力问题"
  ];
}
function extractSummaryFromMetadata(metadata: string, topic: string, label: string): string {
  const summaryMatch = metadata.match(/(?:摘要|简介|summary|description)[：:]\s*(.+)/i);
  if (summaryMatch) {
    return summaryMatch[1].trim();
  }
  return label + "发布摘要：围绕\"" + topic + "\"提炼核心矛盾、关键方法和行动建议。";
}

function extractTagsFromMetadata(metadata: string, platform: Platform): string[] {
  const tagMatch = metadata.match(/(?:标签|话题|tags|hashtags)[：:]\s*(.+)/i);
  if (tagMatch) {
    const tags = tagMatch[1].split(/[#，,、\s]+/).filter(Boolean).map((t) => {
      const tag = t.trim().replace(/^#/, "");
      if (platform === "xiaohongshu") return "#" + tag;
      return tag;
    });
    if (tags.length > 0) return tags;
  }
  return platform === "xiaohongshu"
    ? ["#AI写作", "#内容创作", "#自媒体运营", "#效率工具"]
    : ["AI写作", "内容生产", "自动化", "IP"];
}

function extractKeywordsFromMetadata(metadata: string): string[] {
  const kwMatch = metadata.match(/(?:关键词|keyword)[：:]\s*(.+)/i);
  if (kwMatch) {
    return kwMatch[1].split(/[，,、\s]+/).map((k) => k.trim()).filter(Boolean);
  }
  return ["AI写作", "内容自动化", "IP运营", "对抗式Agent"];
}

function extractPinnedFromMetadata(metadata: string): string {
  const pinnedMatch = metadata.match(/(?:置顶|pinned|comment|评论)[：:]\s*(.+)/i);
  if (pinnedMatch) {
    return pinnedMatch[1].trim();
  }
  return "欢迎留言：你最想把哪一类内容交给自动化写作系统？";
}

export function renderFinalPackageMarkdown(state: TaskState) {
  const finalPackage = state.finalPackage;
  if (!finalPackage) {
    return "# 尚未生成最终发布包\n";
  }

  return [
    "# " + state.input.topic + " 发布包",
    "生成时间：" + finalPackage.createdAt,
    "",
    ...finalPackage.platforms.flatMap((item) => [
      "## " + PLATFORM_LABELS[item.platform],
      "",
      "### 标题",
      ...item.titles.map((title) => "- " + title),
      "",
      "### 摘要",
      item.summary,
      "",
      "### 关键词",
      item.keywords.join("、"),
      "",
      "### 标签",
      item.tags.join(" "),
      "",
      "### 封面图",
      (() => {
        const coverImage = item.images.find((img) => img.placement === "cover") || item.images[0];
        if (coverImage?.url) {
          return "![" + (coverImage.title || "封面") + "](" + coverImage.url + ")";
        }
        return "（待生成封面图）";
      })(),
      "",
      "### 排版稿（含图片）",
      item.formattedArticle,
      "",
      "### 图片资产",
      ...item.images.map((image) => "- " + (image.placement || "image") + "｜" + (image.aspectRatio || "") + "｜" + (image.url || image.prompt || "")),
      "",
      "### 封面/配图方案",
      item.coverPlan,
      "",
      "### 图片生成提示词",
      ...item.imagePrompts.map((prompt) => "- " + prompt),
      "",
      "### 置顶文案",
      item.pinnedComment,
      ""
    ]),
    "## 严反馈终审",
    finalPackage.finalReview.content
  ].join("\n");
}
