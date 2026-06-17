export type Platform = "wechat" | "xiaohongshu" | "toutiao";

export interface ImageAsset {
  id: string;
  title: string;
  url?: string;
  sourceUrl?: string;
  localPath?: string;
  origin: "web" | "generated";
  prompt?: string;
  placement?: string;
  platform?: Platform;
  aspectRatio?: string;
}

export type IssueType =
  | "fact"
  | "compliance"
  | "appeal"
  | "structure"
  | "density"
  | "readability"
  | "style";

export type AgentId =
  | "zhang_material"
  | "zhao_position"
  | "li_article"
  | "qian_human"
  | "liu_style"
  | "editor_supervisor"
  | "writer_supervisor"
  | "wu_fact_check"
  | "sun_compliance"
  | "zhou_challenge"
  | "chen_layout"
  | "zhang_publish"
  | "yan_final"
  | "title_master";

export type TaskStatus =
  | "draft"
  | "running"
  | "needs_config"
  | "needs_material"
  | "approved"
  | "needs_human"
  | "discarded"
  | "failed";

export interface SourceMaterial {
  id: string;
  title: string;
  content: string;
  url?: string;
  images?: ImageAsset[];
  origin: "user" | "web";
}

export interface TaskInput {
  topic: string;
  celebrityVoiceModel: string;
  userValueDemand: string;
  promotionGoal: string;
  targetPlatforms: Platform[];
  sourceMaterials: SourceMaterial[];
  searchEnabled: boolean;
}

export interface AgentIssue {
  id: string;
  issueType: IssueType;
  severity: "low" | "medium" | "high";
  location: string;
  description: string;
  suggestion: string;
  ownerAgentId?: AgentId;
}

export interface AgentOutput {
  id: string;
  round: number;
  subRound?: number;
  agentId: AgentId;
  stage: string;
  status: "pending" | "running" | "completed" | "failed";
  content: string;
  issues: AgentIssue[];
  rawScore?: number;
  normalizedScore?: number;
  score?: number;
  maxScore?: number;
  supervisorType?: "editor" | "writer";
  sources: SourceMaterial[];
  createdAt: string;
}

export interface ScoreReport {
  round: number;
  totalScore: number;
  passed: boolean;
  maxScore: 10;
  outputs: AgentOutput[];
  createdAt: string;
}

export interface FeedbackRecord {
  round: number;
  editorSummary: AgentOutput;
  writerDispatch: AgentOutput;
  assignedIssues: AgentIssue[];
  rerunStages: string[];
  createdAt: string;
}

export interface PlatformPackage {
  platform: Platform;
  formattedArticle: string;
  titles: string[];
  summary: string;
  keywords: string[];
  tags: string[];
  images: ImageAsset[];
  coverPlan: string;
  imagePrompts: string[];
  pinnedComment: string;
}

export interface FinalPackage {
  platforms: PlatformPackage[];
  finalReview: AgentOutput;
  createdAt: string;
}

export interface TaskState {
  id: string;
  input: TaskInput;
  status: TaskStatus;
  createdAt: string;
  updatedAt: string;
  currentRound: number;
  outputs: AgentOutput[];
  scoreReports: ScoreReport[];
  feedbackRecords: FeedbackRecord[];
  finalPackage?: FinalPackage;
  error?: string;
}

export interface RuntimeConfig {
  hasApiKey: boolean;
  mockMode: boolean;
  model: string;
  baseURL: string;
  searchEnabled: boolean;
  researchProviders: string[];
}
