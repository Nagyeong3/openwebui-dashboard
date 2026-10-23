import { request } from "./api";

export type View = "user" | "team" | "leader";
export type Query = {
  range: string;
  start: string;
  end: string;
  division: string;
  team: string;
  position: string;
  matchStatus: string;
  view: View;
  page: number;
  pageSize: number;
  order: "asc" | "desc";
  search: string;
};
export type Person = {
  id: string;
  name: string;
  email: string;
  division: string;
  team: string;
  position: string;
  mapping: string;
  questions: number;
  chats: number;
  attachments: number;
  rank: number;
  lastUsedAt: string | null;
  primaryModel: string | null;
};
export type Team = {
  division: string;
  team: string;
  users: number;
  activeUsers: number;
  questions: number;
  chats: number;
  attachmentQuestions: number;
};
export type Payload = {
  schemaVersion: number;
  source: string;
  updatedAt: string;
  period: { start: string | null; end: string | null; timezone: string };
  dataState: {
    ready: boolean;
    stale: boolean;
    activeRunId: string | null;
    organization: string;
    questionPolicy: string;
  };
  filters: {
    divisions: string[];
    teams: string[];
    positions: string[];
    matchStatuses: string[];
  };
  summary: {
    users: number;
    activeUsers: number;
    zeroUsageUsers: number;
    questions: number;
    chats: number;
    attachmentQuestions: number;
  };
  daily: { date: string; questions: number }[];
  detail: {
    view: View;
    records: (Person | Team)[];
    total: number;
    page: number;
    pageSize: number;
  };
};
export const defaultQuery: Query = {
  range: "30d",
  start: "",
  end: "",
  division: "전체",
  team: "전체",
  position: "전체",
  matchStatus: "전체",
  view: "user",
  page: 1,
  pageSize: 50,
  order: "desc",
  search: "",
};
export function readQuery(search: string): Query {
  const p = new URLSearchParams(search),
    q = { ...defaultQuery };
  for (const k of [
    "division",
    "team",
    "position",
    "matchStatus",
    "search",
    "start",
    "end",
  ] as const)
    q[k] = p.get(k) ?? q[k];
  if (["all", "7d", "30d", "90d", "custom"].includes(p.get("range") || ""))
    q.range = p.get("range")!;
  if (["user", "team", "leader"].includes(p.get("view") || ""))
    q.view = p.get("view") as View;
  if (p.get("order") === "asc") q.order = "asc";
  if (/^[1-9]\d*$/.test(p.get("page") || "")) q.page = Number(p.get("page"));
  if ([10, 25, 50, 100].includes(Number(p.get("pageSize"))))
    q.pageSize = Number(p.get("pageSize"));
  return q;
}
export function queryParams(q: Query): URLSearchParams {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) {
    if (k === "start" || k === "end") {
      if (q.range === "custom") p.set(k, String(v));
    } else if (!(k === "range" && q.range === "custom")) p.set(k, String(v));
  }
  return p;
}
const count = (v: unknown) =>
  typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const text = (v: unknown) => typeof v === "string";
const nullableText = (v: unknown) => v === null || text(v);
export function validateUsers(value: unknown): asserts value is Payload {
  const p = value as Payload;
  const fail = () => {
    throw new Error(
      "사용자 API 응답 형식이 맞지 않습니다. 백엔드 버전을 확인하세요.",
    );
  };
  if (
    !p ||
    p.schemaVersion !== 1 ||
    p.source !== "openwebui-api-cache" ||
    !text(p.updatedAt) ||
    !Number.isFinite(Date.parse(p.updatedAt)) ||
    !p.dataState ||
    p.dataState.ready !== true ||
    typeof p.dataState.stale !== "boolean" ||
    !nullableText(p.dataState.activeRunId) ||
    !text(p.dataState.organization) ||
    !text(p.dataState.questionPolicy) ||
    !p.period ||
    p.period.timezone !== "Asia/Seoul" ||
    !nullableText(p.period.start) ||
    !nullableText(p.period.end) ||
    !p.filters ||
    !p.summary ||
    !p.detail ||
    !Array.isArray(p.daily)
  )
    fail();
  for (const k of ["divisions", "teams", "positions", "matchStatuses"] as const)
    if (!Array.isArray(p.filters[k]) || !p.filters[k].every(text)) fail();
  for (const k of [
    "users",
    "activeUsers",
    "zeroUsageUsers",
    "questions",
    "chats",
    "attachmentQuestions",
  ] as const)
    if (!count(p.summary[k])) fail();
  if (
    !["user", "team", "leader"].includes(p.detail.view) ||
    !count(p.detail.total) ||
    !count(p.detail.page) ||
    p.detail.page < 1 ||
    !count(p.detail.pageSize) ||
    p.detail.pageSize < 1 ||
    !Array.isArray(p.detail.records) ||
    p.detail.records.length > p.detail.pageSize
  )
    fail();
  const ids = new Set();
  for (const r of p.detail.records) {
    if (
      !r ||
      ![r.division, r.team].every(text) ||
      ![r.questions, r.chats].every(count)
    )
      fail();
    if (p.detail.view === "team") {
      const t = r as Team;
      if (![t.users, t.activeUsers, t.attachmentQuestions].every(count)) fail();
    } else {
      const u = r as Person;
      if (
        ![u.id, u.name, u.email, u.position, u.mapping].every(text) ||
        !u.id ||
        ids.has(u.id) ||
        !count(u.rank) ||
        u.rank < 1 ||
        !count(u.attachments) ||
        !nullableText(u.lastUsedAt) ||
        !nullableText(u.primaryModel)
      )
        fail();
      ids.add(u.id);
    }
  }
  for (const d of p.daily)
    if (!d || !/^\d{4}-\d{2}-\d{2}$/.test(d.date) || !count(d.questions))
      fail();
}
export async function loadUsers(
  q: Query,
  token: string,
  signal?: AbortSignal,
): Promise<Payload> {
  if (q.range === "custom" && (!q.start || !q.end || q.start > q.end))
    throw new Error("조회 시작일과 종료일을 확인하세요.");
  const data = await request("/api/dashboard/v2/users?" + queryParams(q), {
    signal,
    headers: token ? { Authorization: "Bearer " + token } : {},
  });
  validateUsers(data);
  if (
    data.detail.view !== q.view ||
    data.detail.page !== q.page ||
    data.detail.pageSize !== q.pageSize
  )
    throw new Error("요청한 보기/페이지와 API 응답이 다릅니다.");
  return data;
}
