/** Contract adapter — unified /health and /contract endpoints per LLD §3.

 * Provides GET /health (health check) and GET /contract (endpoint manifest)
 * for the writing module. Express route handlers.
 */
import type { Request, Response } from "express";

const MODULE = "writing";
const VERSION = "2.0.1";
const CONTRACT_VERSION = "1.0";
const START_TIME = Date.now();

const ENDPOINTS = [
  { path: "/api/tasks", method: "POST", purpose: "create_task" },
  { path: "/api/tasks/{id}/run", method: "POST", purpose: "run_task" },
  { path: "/api/tasks/{id}", method: "GET", purpose: "get_task" },
  { path: "/api/tasks", method: "GET", purpose: "list_tasks" },
  { path: "/api/config", method: "GET", purpose: "get_config" },
];

export function healthHandler(_req: Request, res: Response): void {
  res.json({
    ok: true,
    module: MODULE,
    version: VERSION,
    uptime_seconds: Math.floor((Date.now() - START_TIME) / 1000),
    deps_ok: true,
  });
}

export function contractHandler(_req: Request, res: Response): void {
  res.json({
    module: MODULE,
    contract_version: CONTRACT_VERSION,
    endpoints: ENDPOINTS,
  });
}
