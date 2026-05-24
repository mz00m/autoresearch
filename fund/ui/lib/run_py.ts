/**
 * Shared helper: spawn a `python3 -m fund.X` command, capture stdout/stderr,
 * return a uniform JSON shape. Localhost-only (the dashboard is a single-user
 * laptop tool). No shell interpolation — args are passed as an array.
 */
import { spawn } from "child_process";
import path from "path";

const FUND_ROOT = path.resolve(process.cwd(), "..");
const REPO_ROOT = path.resolve(FUND_ROOT, "..");

export type RunResult = {
  exit_code: number;
  stdout: string;
  stderr: string;
  command: string;
};

export function runPython(
  args: string[],
  timeoutMs = 180_000,
  extraEnv: Record<string, string> = {},
): Promise<RunResult> {
  return new Promise((resolve) => {
    const full = ["-u", ...args];
    const child = spawn("python3", full, {
      cwd: REPO_ROOT,
      env: { ...process.env, ...extraEnv },
    });
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
    }, timeoutMs);
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (c: Buffer) => (stdout += c.toString()));
    child.stderr.on("data", (c: Buffer) => (stderr += c.toString()));
    child.on("close", (code: number | null) => {
      clearTimeout(timer);
      resolve({
        exit_code: code ?? -1,
        stdout,
        stderr,
        command: ["python3", ...full].join(" "),
      });
    });
    child.on("error", (err: Error) => {
      clearTimeout(timer);
      resolve({
        exit_code: -1,
        stdout: "",
        stderr: `failed to spawn python3: ${err.message}`,
        command: ["python3", ...full].join(" "),
      });
    });
  });
}
