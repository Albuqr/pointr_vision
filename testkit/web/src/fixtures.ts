import { test, expect, type Page } from "@playwright/test";
import { config, url } from "./config";

export interface PageIssues {
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: string[];
}

const ignoredConsole = config.web.ignoreConsoleErrors.map((p) => new RegExp(p, "i"));
const ignoredRequests = config.web.ignoreRequestFailures.map((p) => new RegExp(p, "i"));

/** Registra erros de console, exceções não tratadas e requisições com falha/5xx. */
export function monitor(page: Page): PageIssues {
  const issues: PageIssues = { consoleErrors: [], pageErrors: [], failedRequests: [] };
  page.on("console", (msg) => {
    if (msg.type() === "error" && !ignoredConsole.some((r) => r.test(msg.text()))) issues.consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => issues.pageErrors.push(`${err.name}: ${err.message}`));
  page.on("requestfailed", (req) => {
    const reason = req.failure()?.errorText ?? "";
    if (/ERR_ABORTED|NS_BINDING_ABORTED|cancelled/i.test(reason)) return; // navegação interrompida não é erro
    if (!ignoredRequests.some((r) => r.test(req.url()))) issues.failedRequests.push(`${req.method()} ${req.url()} — ${reason}`);
  });
  page.on("response", (res) => {
    if (res.status() >= 500 && !ignoredRequests.some((r) => r.test(res.url()))) {
      issues.failedRequests.push(`${res.request().method()} ${res.url()} — HTTP ${res.status()}`);
    }
  });
  return issues;
}

export function expectNoIssues(issues: PageIssues, where: string) {
  expect.soft(issues.pageErrors, `exceções JavaScript em ${where}`).toEqual([]);
  expect.soft(issues.consoleErrors, `erros de console em ${where}`).toEqual([]);
  expect.soft(issues.failedRequests, `requisições com falha em ${where}`).toEqual([]);
}

export { test, expect, url, config };
