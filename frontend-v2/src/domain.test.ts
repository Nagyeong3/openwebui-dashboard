import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ALL,
  breakdown,
  csvText,
  defaults,
  isLeader,
  previous,
  select,
  teamRows,
  trend,
} from "./domain";
import { createMock } from "./mock";
import { request, validateSnapshot } from "./api";
const snapshot = createMock(),
  f = defaults(snapshot.coverageEnd);
test("DB roster survives a period with no usage, including every leader", () => {
  const data = select(snapshot, {
    ...f,
    start: "2026-01-01",
    end: "2026-01-31",
  });
  assert.equal(data.rows.length, snapshot.users.length);
  assert.equal(
    data.rows.filter(isLeader).length,
    snapshot.users.filter(isLeader).length,
  );
  assert.ok(data.rows.every((r) => r.questions === 0 && r.total === 0));
});
test("zero-usage leaders remain in full rankings beyond top ten", () => {
  const leaders = select(snapshot, f).rows.filter(isLeader);
  assert.equal(leaders.length, 18);
  for (const id of ["demo-db-015", "demo-db-016", "demo-db-017", "demo-db-018"])
    assert.equal(leaders.find((r) => r.id === id)?.questions, 0);
  assert.equal(new Set(leaders.map((r) => r.id)).size, 18);
});
test("questions reconcile across daily, category, team and user totals", () => {
  const d = select(snapshot, f);
  for (const sum of [
    d.rows.reduce((s, r) => s + r.questions, 0),
    trend(d.usage, f, "questions").reduce((s, r) => s + r.value, 0),
    breakdown(d.usage, "category", "questions").reduce(
      (s, r) => s + r.value,
      0,
    ),
    teamRows(d.rows).reduce((s, r) => s + r.questions, 0),
  ])
    assert.equal(sum, d.total.questions);
});
test("unidentified tokens included globally but excluded for org filtering", () => {
  const global = select(snapshot, f);
  const identifiedTokens = global.rows.reduce((s, r) => s + r.total, 0);
  assert.ok(global.total.tokens > identifiedTokens);
  const team = select(snapshot, { ...f, team: snapshot.users[0].team });
  assert.equal(
    team.total.tokens,
    team.rows.reduce((s, r) => s + r.total, 0),
  );
  assert.equal(team.unmappedRequests, 0);
});
test("model filtering does not discard inactive DB users", () => {
  const d = select(snapshot, { ...f, model: "not-present" });
  assert.equal(d.rows.length, snapshot.users.length);
  assert.equal(d.total.tokens, 0);
});
test("org filters intersect roster and usage; team headcounts reconcile", () => {
  const d = select(snapshot, {
    ...f,
    division: "기술본부",
    position: "팀장",
    team: ALL,
  });
  assert.ok(d.rows.every((r) => r.division === "기술본부" && isLeader(r)));
  assert.equal(
    teamRows(d.rows).reduce((s, r) => s + r.users, 0),
    d.users.length,
  );
});
test("previous period is equally long, adjacent and inclusive", () => {
  const p = previous({ ...f, start: "2026-10-01", end: "2026-10-21" });
  assert.equal(p.start, "2026-09-10");
  assert.equal(p.end, "2026-09-30");
});
test("CSV escapes quotes, formula strings and includes explicit zero", () => {
  const csv = csvText(
    ["name", "questions"],
    [
      [" =CMD()", 0],
      ['a"b', 12],
    ],
  );
  assert.ok(csv.startsWith("\ufeff"));
  assert.ok(csv.includes('"\' =CMD()","0"'));
  assert.ok(csv.includes('"a""b","12"'));
});
test("adapter rejects duplicate DB IDs and CSV-only roster entries", () => {
  validateSnapshot(snapshot);
  assert.throws(() =>
    validateSnapshot({
      ...snapshot,
      users: [...snapshot.users, snapshot.users[0]],
    }),
  );
  assert.throws(() =>
    validateSnapshot({
      ...snapshot,
      users: [{ ...snapshot.users[0], source: "csv" }],
    }),
  );
});
test("adapter rejects orphaned usage and invalid numeric metrics", () => {
  assert.throws(() =>
    validateSnapshot({
      ...snapshot,
      usage: [{ ...snapshot.usage[0], userId: "absent" }],
    }),
  );
  assert.throws(() =>
    validateSnapshot({
      ...snapshot,
      usage: [{ ...snapshot.usage[0], requests: -1 }],
    }),
  );
});
test("HTTP 200 with ok:false is an error, not a successful sync", async () => {
  const old = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({ ok: false, error: "LiteLLM HTTP error: 422" }),
      { status: 200 },
    );
  try {
    await assert.rejects(() => request("/api/tokens/sync"), /422/);
  } finally {
    globalThis.fetch = old;
  }
});
