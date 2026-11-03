/**
 * Lê a configuração final pelo mesmo carregador usado nos scripts (bin/lib/config.py),
 * garantindo que padrões, testkit.config.json e variáveis ${VAR} tenham a mesma semântica.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const KIT_DIR = path.resolve(here, "..", "..");

export interface TestkitConfig {
  reportsDir: string;
  web: {
    baseUrl: string;
    browsers: string[];
    retries: number;
    workers: number;
    navigationTimeoutMs: number;
    publicPages: string[];
    ignoreConsoleErrors: string[];
    ignoreRequestFailures: string[];
    checks: Record<"smoke" | "accessibility" | "security" | "responsive" | "performance" | "crawl", boolean>;
    accessibility: { tags: string[]; failOnImpacts: string[]; disableRules: string[]; exclude: string[] };
    security: {
      requiredHeaders: string[];
      requireFrameProtection: boolean;
      requireHstsOnHttps: boolean;
      forbiddenHeaders: string[];
      sensitivePaths: string[];
      checkCors: boolean;
      checkMixedContent: boolean;
    };
    responsive: { viewports: { name: string; width: number; height: number }[]; minTapTargetPx: number };
    performance: {
      budgets: Record<"ttfbMs" | "domContentLoadedMs" | "loadMs" | "lcpMs" | "cls" | "totalTransferKb" | "jsTransferKb", number>;
    };
    crawl: { maxPages: number; checkExternalLinks: boolean; excludePatterns: string[] };
  };
}

let cached: TestkitConfig | undefined;

export function loadConfig(): TestkitConfig {
  if (cached) return cached;
  const python = process.env.PYTHON_BIN || (process.platform === "win32" ? "python" : "python3");
  const out = execFileSync(python, [path.join(KIT_DIR, "bin", "lib", "config.py"), "resolved"], {
    encoding: "utf-8",
    env: process.env,
  });
  cached = JSON.parse(out) as TestkitConfig & { _meta: { projectRoot: string } };
  return cached;
}

export const config = loadConfig();
export const PROJECT_ROOT: string = (config as unknown as { _meta: { projectRoot: string } })._meta.projectRoot;
export const REPORTS_DIR = path.resolve(PROJECT_ROOT, config.reportsDir);

export function url(p: string): string {
  if (/^https?:\/\//.test(p)) return p;
  return config.web.baseUrl.replace(/\/$/, "") + (p.startsWith("/") ? p : `/${p}`);
}
