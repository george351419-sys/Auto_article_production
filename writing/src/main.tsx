import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import type {
  AgentOutput,
  Platform,
  RuntimeConfig,
  SourceMaterial,
  TaskInput,
  TaskState
} from "../shared/types";
import { normalizeScoreValue } from "../shared/scoring";
import { DEFAULT_PROMOTION_GOAL, DEFAULT_USER_VALUE_DEMAND } from "../shared/defaults";
import { DEFAULT_SIMULATION_TOPIC, DEFAULT_SIMULATION_VOICE_MODEL } from "../shared/simulationInput";
import "./styles.css";
import "./styles.css";
import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: "40px", fontFamily: "monospace", color: "red", whiteSpace: "pre-wrap" }}>
          {"React 渲染错误:\n" + (this.state.error?.stack ?? this.state.error?.message ?? "未知错误") + "\n\n请截图这个错误信息发给助手。"}
        </div>
      );
    }
    return this.props.children;
  }
}

const platformOptions: Array<{ id: Platform; label: string }> = [
  { id: "wechat", label: "公众号" },
  { id: "xiaohongshu", label: "小红书" },
  { id: "toutiao", label: "今日头条" }
];

const PASS_SCORE = 7;

function App() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [tasks, setTasks] = useState<TaskState[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) ?? tasks[0],
    [selectedTaskId, tasks]
  );

  async function refresh() {
    const [configResponse, tasksResponse] = await Promise.all([fetch("/api/config"), fetch("/api/tasks")]);
    const configData = (await configResponse.json()) as { config: RuntimeConfig };
    const tasksData = (await tasksResponse.json()) as { tasks: TaskState[] };
    setConfig(configData.config);
    setTasks(tasksData.tasks);
    if (!selectedTaskId && tasksData.tasks[0]) {
      setSelectedTaskId(tasksData.tasks[0].id);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(getErrorMessage(caught)));
    const interval = setInterval(() => {
      refresh().catch(() => {});
    }, 180000);
    return () => clearInterval(interval);
  }, []);

  async function handleCreate(input: TaskInput) {
    setError(null);
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input)
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error ?? "创建任务失败");
    }
    setSelectedTaskId(data.task.id);
    await refresh();
  }

  async function handleRun(taskId: string) {
    setIsRunning(true);
    setError(null);
    try {
      const response = await fetch(`/api/tasks/${taskId}/run`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error ?? "运行任务失败");
      }
      setSelectedTaskId(data.task.id);
      await refresh();
    } catch (caught) {
      setError(getErrorMessage(caught));
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <main className="appShell">
      <header className="topbar">
        <div>
          <p className="eyebrow">本地首版</p>
          <h1>自动化文章写作系统</h1>
        </div>
        <ConfigBadge config={config} />
      </header>

      {error && <div className="alert">{error}</div>}

      <section className="workspace">
        <aside className="leftPane">
          <TaskForm
            disabled={isRunning}
            config={config}
            onCreate={(input) => handleCreate(input).catch((caught) => setError(getErrorMessage(caught)))}
          />
          <TaskList tasks={tasks} selectedId={selectedTask?.id} onSelect={setSelectedTaskId} />
        </aside>

        <section className="rightPane">
          {selectedTask ? (
            <TaskDetail task={selectedTask} isRunning={isRunning} onRun={handleRun} />
          ) : (
            <div className="emptyState">创建第一篇文章任务后，流水线会显示在这里。</div>
          )}
        </section>
      </section>
    </main>
  );
}

function ConfigBadge({ config }: { config: RuntimeConfig | null }) {
  if (!config) {
    return <div className="statusBadge">加载配置中</div>;
  }
  const ready = config.mockMode || config.hasApiKey;
  return (
    <div className={`statusBadge ${ready ? "ok" : "warn"}`}>
      <span>{config.mockMode ? "Mock 模式" : ready ? "LLM 已配置" : "LLM 未配置"}</span>
      <small>
        {config.model} · 检索源 {config.researchProviders.length}
      </small>
    </div>
  );
}

function TaskForm({
  disabled,
  config,
  onCreate
}: {
  disabled: boolean;
  config: RuntimeConfig | null;
  onCreate: (input: TaskInput) => void;
}) {
  const [topic, setTopic] = useState(DEFAULT_SIMULATION_TOPIC);
  const [celebrityVoiceModel, setCelebrityVoiceModel] = useState(DEFAULT_SIMULATION_VOICE_MODEL);
  const [promotionGoal, setPromotionGoal] = useState(DEFAULT_PROMOTION_GOAL);
  const [sourceText, setSourceText] = useState("");
  const [searchEnabled, setSearchEnabled] = useState(true);
  const [targetPlatforms, setTargetPlatforms] = useState<Platform[]>(["wechat", "xiaohongshu", "toutiao"]);

  const ready = Boolean(config?.mockMode || config?.hasApiKey);

  function togglePlatform(platform: Platform) {
    setTargetPlatforms((current) =>
      current.includes(platform)
        ? current.filter((item) => item !== platform)
        : [...current, platform]
    );
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const sourceMaterials: SourceMaterial[] = sourceText.trim()
      ? [
          {
            id: "user-1",
            title: "用户资料",
            content: sourceText.trim(),
            origin: "user"
          }
        ]
      : [];

    onCreate({
      topic,
      celebrityVoiceModel,
      userValueDemand: DEFAULT_USER_VALUE_DEMAND,
      promotionGoal,
      targetPlatforms,
      sourceMaterials,
      searchEnabled
    });
  }

  return (
    <form className="panel formPanel" onSubmit={submit}>
      <div className="panelHeader">
        <h2>创建任务</h2>
        {!ready && <span className="pill warn">需配置 LLM</span>}
      </div>

      <label>
        选题
        <input value={topic} onChange={(event) => setTopic(event.target.value)} disabled={disabled} />
      </label>

      <label>
        名人抽象声线模型
        <textarea
          value={celebrityVoiceModel}
          onChange={(event) => setCelebrityVoiceModel(event.target.value)}
          disabled={disabled}
          rows={8}
        />
      </label>

      <label>
        传播推广目标
        <textarea
          value={promotionGoal}
          onChange={(event) => setPromotionGoal(event.target.value)}
          disabled={disabled}
          rows={2}
        />
      </label>

      <label>
        用户资料（可选）
        <textarea
          value={sourceText}
          onChange={(event) => setSourceText(event.target.value)}
          disabled={disabled}
          rows={5}
        />
      </label>

      <div className="fieldGroup">
        <span>目标平台</span>
        <div className="segmented">
          {platformOptions.map((platform) => (
            <button
              type="button"
              key={platform.id}
              className={targetPlatforms.includes(platform.id) ? "selected" : ""}
              onClick={() => togglePlatform(platform.id)}
              disabled={disabled}
            >
              {platform.label}
            </button>
          ))}
        </div>
      </div>

      <label className="checkRow">
        <input
          type="checkbox"
          checked={searchEnabled}
          onChange={(event) => setSearchEnabled(event.target.checked)}
          disabled={disabled}
        />
        同时尝试联网搜索
      </label>

      <button className="primaryButton" disabled={disabled || targetPlatforms.length === 0}>
        保存任务
      </button>
    </form>
  );
}

function TaskList({
  tasks,
  selectedId,
  onSelect
}: {
  tasks: TaskState[];
  selectedId?: string;
  onSelect: (taskId: string) => void;
}) {
  return (
    <section className="panel taskList">
      <div className="panelHeader">
        <h2>历史任务</h2>
        <span className="muted">{tasks.length}</span>
      </div>
      {tasks.map((task) => (
        <button
          key={task.id}
          className={`taskItem ${task.id === selectedId ? "active" : ""}`}
          onClick={() => onSelect(task.id)}
        >
          <strong>{task.input.topic}</strong>
          <span>{statusText(task.status)} · 第 {task.currentRound} 轮</span>
        </button>
      ))}
    </section>
  );
}

function TaskDetail({
  task,
  isRunning,
  onRun
}: {
  task: TaskState;
  isRunning: boolean;
  onRun: (taskId: string) => void;
}) {
  const latestScore = task.scoreReports.at(-1);
  const latestDisplayScore = latestScore ? getReportTotal(latestScore) : undefined;

  return (
    <div className="detailStack">
      <section className="heroPanel">
        <div>
          <p className="eyebrow">任务详情</p>
          <h2>{task.input.topic}</h2>
          <p>{task.input.promotionGoal}</p>
        </div>
        <div className="heroActions">
          <span className={`pill ${task.status}`}>{statusText(task.status)}</span>
          {latestScore && <span className="scorePill">{latestDisplayScore}/10</span>}
          <button className="primaryButton" disabled={isRunning || task.status === "running"} onClick={() => onRun(task.id)}>
            {isRunning ? "运行中" : task.status === "approved" ? "重新运行" : "运行流水线"}
          </button>
          {task.status === "approved" && task.finalPackage && (
            <a className="secondaryButton" href={`/api/tasks/${task.id}/export.md`} target="_blank">
              导出发布包
            </a>
          )}
        </div>
      </section>

      {task.error && <div className="alert">{task.error}</div>}

      <ScoreBoard task={task} />
      <OutputTimeline outputs={task.outputs} />
      {task.status === "approved" && task.finalPackage && <FinalPackageView task={task} />}
    </div>
  );
}

function ScoreBoard({ task }: { task: TaskState }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>评分与回流</h2>
        <span className="muted">{PASS_SCORE}分准入</span>
      </div>
      <div className="scoreGrid">
        {task.scoreReports.map((report) => (
          <div className="scoreCard" key={report.round}>
            <strong>第 {report.round} 轮</strong>
            <span className={getReportTotal(report) >= PASS_SCORE ? "passText" : "failText"}>{getReportTotal(report)}/10</span>
            <small>{getReportTotal(report) >= PASS_SCORE ? "进入运营包装" : "编辑主控汇总后回流写手主控"}</small>
            <div className="scoreBreakdown">
              {report.outputs.map((output) => (
                <span key={output.id}>
                  {agentName(output.agentId)} {getOutputScore(output)}/{output.maxScore}
                </span>
              ))}
            </div>
            {task.feedbackRecords
              .filter((feedback) => feedback.round === report.round)
              .map((feedback) => (
                <div className="feedbackBlock" key={`${feedback.round}-${feedback.createdAt}`}>
                  <strong>复审回流</strong>
                  <span>编辑汇总：{feedback.editorSummary.content.slice(0, 56)}...</span>
                  <span>写手派单：{feedback.writerDispatch.content.slice(0, 56)}...</span>
                  <span>
                    责任人：
                    {[...new Set(feedback.assignedIssues.map((issue) => issue.ownerAgentId ?? ownerByIssueType(issue.issueType)))]
                      .map((agentId) => agentName(agentId))
                      .join("、") || "未分配"}
                  </span>
                  <span>下轮复跑：{feedback.rerunStages.join(" -> ")}</span>
                </div>
              ))}
            {getReportTotal(report) < PASS_SCORE &&
              !task.feedbackRecords.some((feedback) => feedback.round === report.round) &&
              report.round < task.currentRound && (
                <div className="feedbackBlock">
                  <strong>历史轮次</strong>
                  <span>这轮没有主控记录，通常是旧流程运行产生；重新运行后会生成编辑主控和写手主控。</span>
                </div>
              )}
          </div>
        ))}
        {task.scoreReports.length === 0 && <p className="muted">尚未运行编辑评分。</p>}
      </div>
    </section>
  );
}

function OutputTimeline({ outputs }: { outputs: AgentOutput[] }) {
  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>Agent 产物</h2>
        <span className="muted">{outputs.length}</span>
      </div>
      <div className="timeline">
        {outputs.map((output) => (
          <details key={output.id} className="outputItem">
            <summary>
              <span>
                {agentName(output.agentId)} · {output.stage}
                {output.supervisorType && <em className="stageTag">{output.supervisorType === "editor" ? "编辑主控" : "写手主控"}</em>}
              </span>
              <span>
                {output.subRound ? (`第 ${output.round}.${output.subRound} 轮`) : (`第 ${output.round} 轮`)}
                {typeof output.maxScore === "number" ? ` · ${getOutputScore(output)}/${output.maxScore}` : ""}
                {typeof output.rawScore === "number" && output.rawScore !== getOutputScore(output)
                  ? `（原始 ${output.rawScore}）`
                  : ""}
              </span>
            </summary>
            <pre>{typeof output.content === "string" ? output.content : JSON.stringify(output.content, null, 2)}</pre>
            {output.issues.length > 0 && (
              <div className="issues">
                {output.issues.map((issue) => (
                  <div key={issue.id} className="issue">
                    <strong>{issue.issueType}</strong>
                    <span>{issue.location}：{issue.description}</span>
                    <small>整改：{issue.suggestion} · 责任：{agentName(issue.ownerAgentId ?? ownerByIssueType(issue.issueType))}</small>
                  </div>
                ))}
              </div>
            )}
          </details>
        ))}
        {outputs.length === 0 && <p className="muted">运行后会显示每个 Agent 的中间结果。</p>}
      </div>
    </section>
  );
}

function ReviewScoreCard({ content }: { content: string }) {
  // Parse structured review content
  const totalScore = content.match(/总分[：:]\s*([\d.]+)\s*\/\s*10/);
  const layoutScore = content.match(/排版呈现[：:]\s*([\d.]+)\s*\/\s*4/);
  const imageScore = content.match(/配图配置[：:]\s*([\d.]+)\s*\/\s*3/);
  const metaScore = content.match(/元数据质量[：:]\s*([\d.]+)\s*\/\s*3/);
  const conclusion = content.match(/审核结论[：:]\s*(通过|不通过)/);
  
  const hasStructured = totalScore && layoutScore && imageScore && metaScore;

  if (!hasStructured) {
    // Fallback for unstructured content
    return (
      <div className="reviewFallback">
        {content.split("\n").map((line, index) => (
          <p key={index}>{line || "\u00a0"}</p>
        ))}
      </div>
    );
  }

  return (
    <div className="reviewScoreCard">
      <div className="reviewSummary">
        <div className="reviewTotal">
          <span className="reviewTotalNum">{totalScore[1]}</span>
          <span className="reviewTotalLabel">/ 10</span>
        </div>
        <div className="reviewVerdict">
          <span className={"reviewBadge " + (conclusion && conclusion[1] === "通过" ? "pass" : "fail")}>
            {conclusion ? conclusion[1] : "待定"}
          </span>
        </div>
      </div>
      
      <div className="reviewBreakdown">
        <div className="reviewDimension">
          <span className="reviewDimLabel">排版呈现</span>
          <div className="reviewDimBar">
            <div className="reviewDimFill layout" style={{ width: (parseFloat(layoutScore[1]) / 4 * 100) + "%" }} />
          </div>
          <span className="reviewDimScore">{layoutScore[1]}/4</span>
        </div>
        <div className="reviewDimension">
          <span className="reviewDimLabel">配图配置</span>
          <div className="reviewDimBar">
            <div className="reviewDimFill image" style={{ width: (parseFloat(imageScore[1]) / 3 * 100) + "%" }} />
          </div>
          <span className="reviewDimScore">{imageScore[1]}/3</span>
        </div>
        <div className="reviewDimension">
          <span className="reviewDimLabel">元数据质量</span>
          <div className="reviewDimBar">
            <div className="reviewDimFill meta" style={{ width: (parseFloat(metaScore[1]) / 3 * 100) + "%" }} />
          </div>
          <span className="reviewDimScore">{metaScore[1]}/3</span>
        </div>
      </div>

      <div className="reviewComments">
        {content.split("\n").filter((line) => !/总分|排版呈现|配图配置|元数据质量|审核结论|^$/.test(line)).map((line, index) => (
          <p key={index}>{line}</p>
        ))}
      </div>
    </div>
  );
}

  
function FinalPackageView({ task }: { task: TaskState }) {
  const finalPackage = task.finalPackage;
  if (!finalPackage) return null;

  return (
    <section className="panel">
      <div className="panelHeader">
        <h2>最终发布包</h2>
        <span className="muted">{finalPackage.platforms.length}个平台</span>
      </div>
      <div className="packageGrid">
        {finalPackage.platforms.map((item) => (
          <article className="packageItem" key={item.platform}>
            <h3>{platformLabel(item.platform)}</h3>
            <div className="metaBlock">
              <strong>标题组</strong>
              {item.titles.map((title) => (
                <span key={title}>{title}</span>
              ))}
            </div>
            <div className="metaBlock">
              <strong>摘要</strong>
              <p>{item.summary}</p>
            </div>
            <div className="tagRow">{item.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
            {item.images.length > 0 && (
              <div className="imageGrid">
                {item.images.map((image) => (
                  <div className="imageAsset" key={image.id}>
                    {image.url ? <img src={image.url} alt={image.title} /> : <div className="imagePlaceholder">待生成</div>}
                    <strong>{image.placement || "image"} · {image.aspectRatio || ""}</strong>
                    <small>{image.url || image.prompt}</small>
                  </div>
                ))}
              </div>
            )}
            <details>
              <summary>查看排版稿和配图方案</summary>
              <pre>{item.formattedArticle}</pre>
              <pre>{item.coverPlan}</pre>
              <pre>{item.imagePrompts.join("\n")}</pre>
            </details>
          </article>
        ))}
      </div>
      <div className="finalReview">
        <strong>严反馈终审</strong>
        <ReviewScoreCard content={finalPackage.finalReview.content} />
      </div>
    </section>
  );
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "未知错误";
}

function getOutputScore(output: AgentOutput) {
  if (typeof output.maxScore !== "number") {
    return output.normalizedScore ?? output.score ?? 0;
  }
  return normalizeScoreValue(output.normalizedScore ?? output.score, output.maxScore, output.issues);
}

function getReportTotal(report: TaskState["scoreReports"][number]) {
  const total =
    report.outputs.length > 0
      ? report.outputs.reduce((sum, output) => sum + getOutputScore(output), 0)
      : report.totalScore;
  return Number(Math.min(10, Math.max(0, total)).toFixed(1));
}

function ownerByIssueType(issueType: AgentOutput["issues"][number]["issueType"]): AgentOutput["agentId"] {
  const map: Record<AgentOutput["issues"][number]["issueType"], AgentOutput["agentId"]> = {
    fact: "zhang_material",
    density: "zhang_material",
    structure: "zhao_position",
    appeal: "zhao_position",
    readability: "qian_human",
    compliance: "qian_human",
    style: "liu_style"
  };
  return map[issueType];
}

function statusText(status: TaskState["status"]) {
  const map: Record<TaskState["status"], string> = {
    draft: "待运行",
    running: "运行中",
    needs_config: "需配置",
    needs_material: "需补素材",
    approved: "已通过",
    needs_human: "需人工",
    failed: "失败"
  };
  return map[status];
}

function agentName(agentId: AgentOutput["agentId"]) {
  const map: Record<AgentOutput["agentId"], string> = {
    zhang_material: "张素材",
    zhao_position: "赵立意",
    li_article: "李文章",
    qian_human: "钱人味",
    liu_style: "刘风格",
    editor_supervisor: "编辑主Agent",
    writer_supervisor: "写手主Agent",
    wu_fact_check: "吴查查",
    sun_compliance: "孙风控",
    zhou_challenge: "周挑刺",
    chen_layout: "陈排版",
    zhang_publish: "章上线",
    yan_final: "严反馈",
    title_master: "标题大师"
  };
  return map[agentId];
}

function platformLabel(platform: Platform) {
  return platformOptions.find((item) => item.id === platform)?.label ?? platform;
}

createRoot(document.getElementById("root")!).render(
  <ErrorBoundary>
    <React.StrictMode>
      <App />
    </React.StrictMode>
  </ErrorBoundary>
);
