import { createMock } from "./mock";
import type { Operation, Snapshot } from "./domain";
export const demo = import.meta.env?.VITE_DATA_MODE !== "api";
const base = (import.meta.env?.VITE_API_BASE_URL || "").replace(/\/$/, "");
export async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(base + path, {
    cache: "no-store",
    ...options,
    headers: { Accept: "application/json", ...options.headers },
  });
  const text = await response.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(
      `서버가 JSON 대신 다른 응답을 반환했습니다 (HTTP ${response.status}).`,
    );
  }
  if (!body || typeof body !== "object")
    throw new Error("서버가 올바른 JSON 객체를 반환하지 않았습니다.");
  if (!response.ok || body.ok === false) {
    const reason = body.error || body.detail;
    throw new Error(
      typeof reason === "string"
        ? reason
        : `요청 오류 (HTTP ${response.status})`,
    );
  }
  return body;
}
// Historical snapshot demo contract. The API-mode entrypoint uses LiveApp/live-api
// and the new /users contract; it never requests this snapshot adapter.
export async function loadSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  if (demo) {
    await new Promise((r) => setTimeout(r, 650));
    return createMock();
  }
  const data = await request("/api/dashboard/v2/snapshot", { signal });
  validateSnapshot(data);
  return { ...data, source: "api" };
}
export function validateSnapshot(value: unknown): asserts value is Snapshot {
  const d = value as Snapshot;
  if (
    !d ||
    d.schemaVersion !== 1 ||
    !Array.isArray(d.users) ||
    !Array.isArray(d.usage) ||
    !Array.isArray(d.operations) ||
    !d.cache ||
    !Number.isFinite(d.cache.logs) ||
    !d.updatedAt ||
    !/^\d{4}-\d{2}-\d{2}$/.test(d.coverageStart) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(d.coverageEnd) ||
    d.coverageStart > d.coverageEnd
  )
    throw new Error(
      "API 데이터 계약이 맞지 않습니다. v2 어댑터 응답을 확인해주세요.",
    );
  const ids = new Set<string>();
  for (const u of d.users) {
    if (
      !u.id ||
      ids.has(u.id) ||
      u.source !== "openwebui-db" ||
      ![u.name, u.division, u.team, u.position, u.mapping].every(
        (x) => typeof x === "string",
      )
    )
      throw new Error(
        "전체 DB 사용자 명부에 중복 ID 또는 잘못된 항목이 있습니다.",
      );
    ids.add(u.id);
  }
  for (const e of d.usage) {
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(e.date) ||
      e.date < d.coverageStart ||
      e.date > d.coverageEnd ||
      (e.userId !== null && !ids.has(e.userId)) ||
      ![e.model, e.category].every((x) => typeof x === "string") ||
      ![
        e.questions,
        e.chats,
        e.attachments,
        e.requests,
        e.prompt,
        e.completion,
        e.spend,
      ].every((x) => Number.isFinite(x) && x >= 0)
    )
      throw new Error("사용량 데이터의 날짜·사용자 연결·숫자를 확인해주세요.");
  }
}
export async function runUpdate(kind: "quick" | "full"): Promise<Operation> {
  const body = await request(
    "/api/operations/" + (kind === "quick" ? "quick-update" : "full-update"),
    { method: "POST" },
  );
  // Requires a completed normalized operation. Async deployed jobs need polling in this adapter.
  if (
    !body.operation ||
    !Array.isArray(body.operation.steps) ||
    !["success", "failed", "running"].includes(body.operation.status)
  )
    throw new Error(
      "업데이트 응답 어댑터가 필요합니다. 실행 결과는 운영 로그에서 확인해주세요.",
    );
  return body.operation;
}
