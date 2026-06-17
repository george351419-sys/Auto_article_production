import type { AgentIssue } from "./types";

export function normalizeScoreValue(
  score: unknown,
  maxScore: number,
  issues: Pick<AgentIssue, "severity">[] = []
) {
  let normalized: number;

  if (typeof score === "number" && Number.isFinite(score)) {
    if (score <= maxScore) {
      normalized = score;
    } else if (score <= 10) {
      normalized = (score / 10) * maxScore;
    } else if (score <= 100) {
      normalized = (score / 100) * maxScore;
    } else {
      normalized = maxScore;
    }
  } else {
    normalized = inferScoreFromIssues(maxScore, issues);
  }

  return Number(Math.min(maxScore, Math.max(0, normalized)).toFixed(1));
}

export function inferScoreFromIssues(maxScore: number, issues: Pick<AgentIssue, "severity">[]) {
  if (issues.length === 0) {
    return maxScore;
  }

  const penalty = issues.reduce((sum, issue) => {
    if (issue.severity === "high") {
      return sum + 1.2;
    }
    if (issue.severity === "medium") {
      return sum + 0.7;
    }
    return sum + 0.4;
  }, 0);

  return maxScore - penalty;
}

