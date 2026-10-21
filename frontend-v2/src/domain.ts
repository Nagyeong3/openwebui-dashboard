export type Page = "overview" | "users" | "tokens" | "operations";
export type User = {
  id: string;
  name: string;
  division: string;
  team: string;
  position: string;
  mapping: "매핑 완료" | "미매핑" | "중복 이름";
  source: "openwebui-db";
};
// Daily aggregate, never a raw chat body. Usage may contain tokens without a mapped user.
export type Usage = {
  date: string;
  userId: string | null;
  model: string;
  category: string;
  questions: number;
  chats: number;
  attachments: number;
  requests: number;
  prompt: number;
  completion: number;
  spend: number;
};
export type Step = {
  name: string;
  status: "success" | "running" | "failed" | "waiting";
  detail: string;
};
export type Operation = {
  id: string;
  kind: string;
  startedAt: string;
  status: "success" | "running" | "failed";
  steps: Step[];
};
export type Snapshot = {
  schemaVersion: 1;
  source: "mock" | "api";
  updatedAt: string;
  coverageStart: string;
  coverageEnd: string;
  users: User[];
  usage: Usage[];
  operations: Operation[];
  cache: { logs: number; classified: number; pending: number };
};
export type Filters = {
  start: string;
  end: string;
  division: string;
  team: string;
  position: string;
  mapping: string;
  model: string;
  category: string;
};
export type UserRow = User & {
  questions: number;
  chats: number;
  attachments: number;
  requests: number;
  prompt: number;
  completion: number;
  spend: number;
  total: number;
};
export const ALL = "전체";
export const day = (value: string) => new Date(value + "T00:00:00Z");
export const iso = (value: Date) => value.toISOString().slice(0, 10);
export function addDays(value: string, amount: number) {
  const d = day(value);
  d.setUTCDate(d.getUTCDate() + amount);
  return iso(d);
}
export function defaults(end: string): Filters {
  return {
    start: addDays(end, -29),
    end,
    division: ALL,
    team: ALL,
    position: ALL,
    mapping: ALL,
    model: ALL,
    category: ALL,
  };
}
export const isLeader = (u: User) => u.position.includes("팀장");
export const number = (n: number) =>
  n.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
export const compact = (n: number) =>
  n >= 1e6
    ? (n / 1e6).toFixed(1) + "M"
    : n >= 1e3
      ? (n / 1e3).toFixed(1) + "K"
      : number(n);
export const dollars = (n: number) =>
  "$" +
  n.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
export function options(values: string[]) {
  return [
    ALL,
    ...Array.from(new Set(values.filter(Boolean))).sort((a, b) =>
      a.localeCompare(b, "ko"),
    ),
  ];
}
export function roster(snapshot: Snapshot, f: Filters) {
  return snapshot.users.filter(
    (u) =>
      u.source === "openwebui-db" &&
      (f.division === ALL || u.division === f.division) &&
      (f.team === ALL || u.team === f.team) &&
      (f.position === ALL || u.position === f.position) &&
      (f.mapping === ALL || u.mapping === f.mapping),
  );
}
export function select(snapshot: Snapshot, f: Filters) {
  const users = roster(snapshot, f);
  const ids = new Set(users.map((u) => u.id));
  const orgFiltered = [f.division, f.team, f.position, f.mapping].some(
    (x) => x !== ALL,
  );
  const usage = snapshot.usage.filter(
    (e) =>
      e.date >= f.start &&
      e.date <= f.end &&
      (e.userId !== null ? ids.has(e.userId) : !orgFiltered) &&
      (f.model === ALL || e.model === f.model) &&
      (f.category === ALL || e.category === f.category),
  );
  const rows: UserRow[] = users.map((u) => ({
    ...u,
    questions: 0,
    chats: 0,
    attachments: 0,
    requests: 0,
    prompt: 0,
    completion: 0,
    spend: 0,
    total: 0,
  }));
  const byId = new Map(rows.map((u) => [u.id, u]));
  for (const e of usage) {
    const row = e.userId ? byId.get(e.userId) : undefined;
    if (row) {
      for (const key of [
        "questions",
        "chats",
        "attachments",
        "requests",
        "prompt",
        "completion",
        "spend",
      ] as const)
        row[key] += e[key];
      row.total += e.prompt + e.completion;
    }
  }
  rows.sort(
    (a, b) =>
      b.questions - a.questions ||
      a.name.localeCompare(b.name, "ko") ||
      a.id.localeCompare(b.id),
  );
  const total = {
    questions: 0,
    chats: 0,
    attachments: 0,
    requests: 0,
    prompt: 0,
    completion: 0,
    spend: 0,
    tokens: 0,
  };
  for (const e of usage) {
    for (const key of [
      "questions",
      "chats",
      "attachments",
      "requests",
      "prompt",
      "completion",
      "spend",
    ] as const)
      total[key] += e[key];
    total.tokens += e.prompt + e.completion;
  }
  const active = rows.filter((r) => r.questions > 0).length;
  const tokenUsers = rows.filter((r) => r.requests > 0).length;
  const activeTeams = new Set(
    rows.filter((r) => r.questions > 0).map((r) => r.team),
  ).size;
  return {
    users,
    usage,
    rows,
    total,
    active,
    tokenUsers,
    activeTeams,
    zero: rows.filter((r) => r.questions === 0).length,
    unmappedRequests: usage
      .filter((r) => !r.userId)
      .reduce((s, r) => s + r.requests, 0),
  };
}
export function previous(f: Filters): Filters {
  const length =
    Math.round((day(f.end).getTime() - day(f.start).getTime()) / 86400000) + 1;
  return { ...f, start: addDays(f.start, -length), end: addDays(f.start, -1) };
}
export function trend(
  usage: Usage[],
  f: Filters,
  metric: "questions" | "tokens",
) {
  const map = new Map<string, number>();
  for (let date = f.start; date <= f.end; date = addDays(date, 1))
    map.set(date, 0);
  for (const e of usage)
    map.set(
      e.date,
      (map.get(e.date) || 0) +
        (metric === "tokens" ? e.prompt + e.completion : e.questions),
    );
  return [...map].map(([date, value]) => ({ date, value }));
}
export function breakdown(
  usage: Usage[],
  field: "category" | "model",
  metric: "questions" | "tokens",
) {
  const map = new Map<string, number>();
  for (const e of usage)
    map.set(
      e[field],
      (map.get(e[field]) || 0) +
        (metric === "tokens" ? e.prompt + e.completion : e.questions),
    );
  return [...map]
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}
export function teamRows(rows: UserRow[]) {
  const map = new Map<
    string,
    {
      id: string;
      name: string;
      division: string;
      users: number;
      questions: number;
      total: number;
      active: number;
    }
  >();
  for (const r of rows) {
    const id = r.division + "/" + r.team;
    const t = map.get(id) || {
      id,
      name: r.team,
      division: r.division,
      users: 0,
      questions: 0,
      total: 0,
      active: 0,
    };
    t.users++;
    t.questions += r.questions;
    t.total += r.total;
    t.active += Number(r.questions > 0);
    map.set(id, t);
  }
  return [...map.values()].sort(
    (a, b) => b.questions - a.questions || a.id.localeCompare(b.id),
  );
}
export function csvText(headers: string[], records: (string | number)[][]) {
  // Protect spreadsheet formula execution, including values with leading control/space.
  const escape = (v: string | number) => {
    let s = String(v);
    if (typeof v === "string" && /^[\s]*[=+@-]/.test(s)) s = "'" + s;
    return '"' + s.replaceAll('"', '""') + '"';
  };
  return (
    "\ufeff" +
    [headers, ...records].map((row) => row.map(escape).join(",")).join("\r\n")
  );
}
