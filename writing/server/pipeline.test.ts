import { mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import assert from "node:assert/strict";
import type { TaskInput } from "../shared/types";
import { DEFAULT_USER_VALUE_DEMAND } from "../shared/defaults";

process.env.LLM_MOCK = "true";
process.env.DATA_DIR = await mkdtemp(path.join(os.tmpdir(), "writing-agent-test-"));
process.env.RESEARCH_PROVIDERS = "mock";

const { createTask, loadTask, saveTask } = await import("./store");
const { getDataDir } = await import("./store");
const { renderFinalPackageMarkdown, runTask } = await import("./pipeline");
const { runMaterialResearch } = await import("./researchSkill");
const { normalizeScoreValue } = await import("../shared/scoring");

const baseInput: TaskInput = {
  topic: "自动化文章写作系统",
  celebrityVoiceModel: "抽象声线：重视第一性原理、短句、克制、强调系统能力。",
  userValueDemand: "帮助内容团队稳定生产高质量文章。",
  promotionGoal: "吸引自媒体团队试用本地工具。",
  targetPlatforms: ["wechat", "xiaohongshu", "toutiao"],
  sourceMaterials: [
    {
      id: "user-1",
      title: "内部需求文档",
      content: "系统包含写手、编辑、运营三层Agent，并以7分为准入线。",
      origin: "user"
    }
  ],
  searchEnabled: true
};

const approvedTask = await createTask(baseInput);
const approvedState = await runTask(approvedTask.id);
assert.equal(approvedState.status, "approved");
assert.equal(approvedState.finalPackage?.platforms.length, 3);
assert.ok(approvedState.scoreReports[0].totalScore >= 7);
assert.equal(approvedState.input.userValueDemand, DEFAULT_USER_VALUE_DEMAND);
assert.deepEqual(
  approvedState.finalPackage?.platforms.map((item) => item.platform),
  ["wechat", "xiaohongshu", "toutiao"]
);
assert.ok(approvedState.finalPackage?.platforms.every((item) => item.images.length > 0));
assert.ok(approvedState.finalPackage?.platforms.every((item) => item.imagePrompts.length >= 3));
assert.ok(approvedState.outputs.some((output) => output.sources.some((source) => source.id === "research-no-results")));

const restored = await loadTask(approvedTask.id);
assert.equal(restored.id, approvedTask.id);
assert.ok(restored.outputs.length > 0);
assert.equal(restored.status, "approved");

const exportMarkdown = await readFile(
  path.join(getDataDir(), approvedTask.id, "final-package.md"),
  "utf8"
);
assert.ok(exportMarkdown.includes("## 公众号"));
assert.ok(exportMarkdown.includes("## 小红书"));
assert.ok(exportMarkdown.includes("## 今日头条"));
assert.ok(renderFinalPackageMarkdown(approvedState).includes("严反馈终审"));

const lowScoreTask = await createTask({
  ...baseInput,
  topic: "低分回流测试：自动化文章写作系统"
});
const lowScoreState = await runTask(lowScoreTask.id);
assert.equal(lowScoreState.status, "approved");
assert.ok(lowScoreState.scoreReports[0].totalScore < 7);
assert.ok(lowScoreState.scoreReports.some((report) => report.totalScore >= 7));
assert.equal(lowScoreState.feedbackRecords.length, 1);
assert.ok(lowScoreState.feedbackRecords[0].assignedIssues.every((issue) => Boolean(issue.ownerAgentId)));
assert.ok(lowScoreState.outputs.some((output) => output.stage === "editor-supervisor"));
assert.ok(lowScoreState.outputs.some((output) => output.stage === "writer-supervisor"));
assert.deepEqual(lowScoreState.feedbackRecords[0].rerunStages, [
  "review-positioning",
  "review-material",
  "rewrite-draft",
  "review-humanize",
  "review-voice-polish"
]);
assert.ok(
  ["review-positioning", "review-material", "rewrite-draft", "review-humanize", "review-voice-polish"].every(
    (stage) => lowScoreState.outputs.some((output) => output.round === 2 && output.stage === stage)
  )
);
assert.ok(
  lowScoreState.outputs
    .flatMap((output) => output.issues)
    .some((issue) => issue.ownerAgentId === "zhang_material" || issue.ownerAgentId === "qian_human")
);

const failedPartialTask = await createTask({
  ...baseInput,
  topic: "半轮失败恢复测试：自动化文章写作系统"
});
await saveTask({
  ...failedPartialTask,
  status: "failed",
  error: "terminated",
  currentRound: 1,
  outputs: [
    {
      id: "stale-partial-editor-output",
      round: 1,
      agentId: "wu_fact_check",
      stage: "fact-check",
      status: "completed",
      content: "旧的半轮失败残留产物",
      issues: [],
      score: 1,
      normalizedScore: 1,
      rawScore: 1,
      maxScore: 3,
      sources: baseInput.sourceMaterials,
      createdAt: new Date().toISOString()
    }
  ],
  scoreReports: [],
  feedbackRecords: []
});
const recoveredPartialState = await runTask(failedPartialTask.id);
assert.equal(recoveredPartialState.status, "approved");
assert.equal(recoveredPartialState.currentRound, 1);
assert.equal(recoveredPartialState.scoreReports.length, 1);
assert.ok(!recoveredPartialState.outputs.some((output) => output.id === "stale-partial-editor-output"));

const percentageScoreTask = await createTask({
  ...baseInput,
  topic: "百分制评分测试：自动化文章写作系统"
});
const percentageScoreState = await runTask(percentageScoreTask.id);
assert.equal(percentageScoreState.status, "needs_human");
assert.equal(percentageScoreState.currentRound, 5);
assert.equal(percentageScoreState.scoreReports.length, 5);
assert.equal(percentageScoreState.feedbackRecords.length, 4);
assert.ok(percentageScoreState.scoreReports.every((report) => report.totalScore < 7));
assert.ok(percentageScoreState.scoreReports.every((report) => report.totalScore <= 10));
assert.ok(
  percentageScoreState.feedbackRecords.every((feedback) =>
    feedback.assignedIssues.every((issue) => Boolean(issue.ownerAgentId))
  )
);
assert.ok(
  percentageScoreState.outputs
    .filter((output) => output.maxScore)
    .every(
      (output) =>
        typeof output.rawScore === "number" &&
        typeof output.normalizedScore === "number" &&
        output.normalizedScore <= output.maxScore!
    )
);
assert.equal(normalizeScoreValue(78, 3), 2.3);
assert.equal(normalizeScoreValue(70, 3), 2.1);
assert.equal(normalizeScoreValue(62, 4), 2.5);

const singlePlatformTask = await createTask({
  ...baseInput,
  topic: "单平台发布包测试",
  targetPlatforms: ["wechat"],
  searchEnabled: false
});
const singlePlatformState = await runTask(singlePlatformTask.id);
assert.equal(singlePlatformState.status, "approved");
assert.deepEqual(singlePlatformState.finalPackage?.platforms.map((item) => item.platform), ["wechat"]);
assert.ok(singlePlatformState.finalPackage?.platforms[0].imagePrompts.length);

const noMaterialTask = await createTask({
  ...baseInput,
  topic: "无素材阻断测试",
  sourceMaterials: [],
  searchEnabled: true
});
const noMaterialState = await runTask(noMaterialTask.id);
assert.equal(noMaterialState.status, "needs_material");
assert.equal(noMaterialState.outputs.length, 0);
assert.match(noMaterialState.error ?? "", /未取得可用于写作的真实素材/);

const originalFetch = globalThis.fetch;
process.env.RESEARCH_PROVIDERS = "wikipedia,hn";
globalThis.fetch = async (input: string | URL | Request) => {
  const url = input.toString();
  if (url.includes("wikipedia.org")) {
    return new Response(
      JSON.stringify({
        query: {
          search: [
            {
              title: "AI writing",
              snippet: "AI writing tools help with <b>drafting</b> and editing.",
              pageid: 123
            }
          ]
        }
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }
  if (url.includes("hn.algolia.com")) {
    return new Response(
      JSON.stringify({
        hits: [
          {
            objectID: "456",
            title: "Show HN: Writing agents",
            url: "https://news.ycombinator.com/item?id=456",
            points: 321,
            num_comments: 45
          }
        ]
      }),
      { status: 200, headers: { "Content-Type": "application/json" } }
    );
  }
  return new Response("{}", { status: 404 });
};
const researchedSources = await runMaterialResearch("AI writing");
assert.ok(researchedSources.some((source) => source.id === "wikipedia-123"));
assert.ok(researchedSources.some((source) => source.id === "hn-456"));
assert.ok(researchedSources.every((source) => source.url && source.url !== "about:blank"));
globalThis.fetch = originalFetch;
process.env.RESEARCH_PROVIDERS = "mock";

process.env.LLM_MOCK = "false";
delete process.env.LLM_API_KEY;
const missingConfigTask = await createTask({
  ...baseInput,
  topic: "缺少模型配置测试",
  searchEnabled: false
});
const missingConfigState = await runTask(missingConfigTask.id);
assert.equal(missingConfigState.status, "needs_config");
assert.match(missingConfigState.error ?? "", /LLM_API_KEY|LLM_MODEL/);
process.env.LLM_MOCK = "true";

console.log("pipeline tests passed");
