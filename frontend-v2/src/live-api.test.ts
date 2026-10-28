import { test } from "node:test";
import { validateTokens, loadTokens } from "./Tokens";
import assert from "node:assert/strict";
import {
  defaultQuery,
  readScreen,
  userQuery,
  leaderQuery,
  periodParams,
  validateOverview,
  loadOverview,
  overviewCsv,
  type OverviewPayload,
  loadUsers,
  queryParams,
  readQuery,
  validateUsers,
  validateLeaderRanking,
} from "./live-api";

function fixture() {
  return {
    leaderRanking: [
      {
        id: "synthetic",
        name: "Synthetic",
        team: "T",
        position: "팀장",
        questions: 0,
        rank: 1,
      },
    ],
    schemaVersion: 1,
    source: "openwebui-api-cache",
    updatedAt: "2026-10-22T00:00:00Z",
    period: { start: null, end: null, timezone: "Asia/Seoul" },
    dataState: {
      ready: true,
      stale: false,
      activeRunId: null,
      organization: "loaded",
      questionPolicy: "all-stored-user-message-ids",
    },
    filters: {
      divisions: ["전체"],
      teams: ["전체"],
      positions: ["전체"],
      matchStatuses: ["전체"],
    },
    summary: {
      users: 1,
      activeUsers: 0,
      zeroUsageUsers: 1,
      questions: 0,
      chats: 0,
      attachmentQuestions: 0,
    },
    daily: [],
    detail: {
      view: "leader" as const,
      page: 1,
      pageSize: 50,
      total: 1,
      records: [
        {
          id: "synthetic",
          name: "Synthetic",
          email: "",
          division: "D",
          team: "T",
          position: "팀장",
          mapping: "매핑 완료",
          rank: 1,
          questions: 0,
          chats: 0,
          attachments: 0,
          lastUsedAt: null,
          primaryModel: null,
        },
      ],
    },
  };
}
test("live contract preserves zero-use leaders without synthetic token values", () => {
  const p = fixture();
  validateUsers(p);
  assert.equal(p.detail.records[0].questions, 0);
  assert.equal("totalTokens" in p.detail.records[0], false);
  p.detail.records.push(p.detail.records[0]);
  assert.throws(() => validateUsers(p));
});
test("rejects missing numeric metrics rather than displaying zero", () => {
  const p = fixture();
  (p.summary as any).questions = undefined;
  assert.throws(() => validateUsers(p));
});
test("URL parsing restores server pagination and ignores invalid values", () => {
  const q = readQuery(
    "?view=leader&page=3&pageSize=25&team=T&order=asc&range=all",
  );
  assert.equal(q.page, 3);
  assert.equal(q.view, "leader");
  assert.equal(q.pageSize, 25);
  assert.equal(q.team, "T");
  assert.equal(readQuery("?page=-1&pageSize=0&view=other").page, 1);
  assert.equal(readQuery("?page=users").page, 1);
});
test("preset query excludes stale custom dates", () => {
  const p = queryParams({
    ...defaultQuery,
    start: "2026-01-01",
    end: "2026-01-02",
  });
  assert.equal(p.has("start"), false);
  const custom = queryParams({
    ...defaultQuery,
    range: "custom",
    start: "2026-01-01",
    end: "2026-01-02",
  });
  assert.equal(custom.get("start"), "2026-01-01");
  assert.equal(custom.has("range"), false);
});
test("actual users transport carries cancellation and dashboard auth; never snapshot fallback", async () => {
  const original = globalThis.fetch,
    controller = new AbortController();
  try {
    globalThis.fetch = async (url, options) => {
      assert.ok(String(url).startsWith("/api/dashboard/v2/users?"));
      assert.equal(options?.signal, controller.signal);
      assert.equal(
        (options?.headers as Record<string, string>).Authorization,
        "Bearer dashboard-only",
      );
      return new Response(JSON.stringify(fixture()), { status: 200 });
    };
    const result = await loadUsers(
      { ...defaultQuery, view: "leader" },
      "dashboard-only",
      controller.signal,
    );
    assert.equal(result.detail.total, 1);
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: "No successful sync" }), {
        status: 503,
      });
    await assert.rejects(
      () => loadUsers(defaultQuery, ""),
      /No successful sync/,
    );
  } finally {
    globalThis.fetch = original;
  }
});

test("overview entry, legacy user URLs and leader filter share one user page", async () => {
  assert.equal(readScreen(""), "overview");
  assert.equal(readScreen("?screen=overview&view=leader"), "overview");
  assert.equal(readScreen("?view=leader"), "users");
  assert.equal(userQuery({ ...defaultQuery, view: "team" }).view, "user");
  const q = leaderQuery(
    { ...defaultQuery, team: "Old", search: "old", order: "asc", page: 4 },
    { start: "2026-09-28", end: "2026-10-27", timezone: "Asia/Seoul" },
  );
  assert.equal(q.view, "leader");
  assert.equal(q.team, "전체");
  assert.equal(q.search, "");
  assert.equal(q.page, 1);
  assert.equal(q.order, "desc");
  assert.equal(q.range, "custom");
  assert.equal(q.pageSize, 50);
  assert.equal(readQuery("?" + queryParams(q)).range, "custom");
  assert.equal(readQuery("?" + queryParams(q)).start, "2026-09-28");
  assert.deepEqual([...periodParams(q).keys()], ["start", "end"]);
});

function overviewFixture(): OverviewPayload {
  const p = fixture();
  return {
    ...p,
    summary: {
      ...p.summary,
      leaders: 1,
      activeLeaders: 0,
      averageQuestionsPerChat: null,
    },
    comparison: {
      status: "zero-baseline",
      start: "2026-09-01",
      end: "2026-09-30",
      questions: 0,
      changePercent: null,
    },
    leaderTop10: p.detail.records,
    integrations: {
      tokens: {
        status: "not-connected",
        source: "litellm",
        total: null,
        input: null,
        output: null,
        requests: null,
        averagePerRequest: null,
        costUsd: null,
      },
      categories: {
        status: "not-connected",
        source: "embedding-classifier",
        records: null,
        classified: null,
      },
    },
  };
}
test("overview validation retains zeros and distinguishes missing integrations", async () => {
  const p = overviewFixture();
  validateOverview(p);
  assert.equal(p.leaderTop10[0].questions, 0);
  (p.integrations.tokens as any).costUsd = 0;
  assert.throws(() => validateOverview(p));
  const bad = overviewFixture();
  (bad.comparison as any).changePercent = Infinity;
  assert.throws(() => validateOverview(bad));
});
test("overview transport uses only period, auth and cancellation", async () => {
  const original = globalThis.fetch,
    controller = new AbortController();
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(String(url), "/api/dashboard/v2/overview?range=7d");
      assert.equal(options?.signal, controller.signal);
      assert.equal(
        (options?.headers as Record<string, string>).Authorization,
        "Bearer dashboard-only",
      );
      return new Response(JSON.stringify(overviewFixture()), { status: 200 });
    };
    await loadOverview(
      { ...defaultQuery, team: "Hidden", view: "leader", page: 5 },
      "dashboard-only",
      controller.signal,
    );
  } finally {
    globalThis.fetch = original;
  }
});
test("overview CSV includes daily and leaders, null is blank and formulas are escaped", async () => {
  const p = overviewFixture();
  p.leaderTop10[0].name = "=SUM(1,2)";
  validateOverview(p);
  const csv = overviewCsv(p);
  assert.ok(csv.startsWith("\ufeff"));
  assert.ok(csv.includes("'=SUM(1,2)"));
  assert.ok(csv.includes('"팀장 Top 10 순위"'));
  assert.ok(csv.includes('"추정 비용"') === false);
  assert.ok(csv.includes('"연동 준비 중"'));
  assert.ok(!csv.includes('"null"'));
});

test("leader chart receives full population independently of table pagination", () => {
  const p = fixture();
  p.detail.total = 13;
  p.leaderRanking = Array.from({ length: 13 }, (_, i) => ({
    id: `l${i}`,
    name: `L${i}`,
    team: "T",
    position: "팀장",
    questions: i < 2 ? 5 : 0,
    rank: i + 1,
  }));
  validateLeaderRanking(p);
  assert.equal(p.detail.records.length, 1);
  assert.equal(p.leaderRanking.length, 13);
  assert.equal(p.leaderRanking[12].questions, 0);
  p.leaderRanking.pop();
  assert.throws(() => validateLeaderRanking(p));
});
test("date picker defaults to seven days and validates dates before apply", async () => {
  const { validPeriod } = await import("./PeriodPicker");
  assert.equal(defaultQuery.range, "7d");
  assert.equal(readQuery("?range=month").range, "month");
  assert.ok(validPeriod("2026-10-01", "2026-10-27"));
  assert.ok(validPeriod("2024-02-29", "2024-02-29"));
  assert.equal(validPeriod("2026-02-29", "2026-03-01"), false);
  assert.equal(validPeriod("2026-10-28", "2026-10-27"), false);
  assert.equal(validPeriod("", "2026-10-27"), false);
});

test("token API keeps missing values distinct from zero and authenticates transport", async () => {
  const totals = {
    total: null,
    input: 0,
    output: null,
    costUsd: 0,
    requests: 1,
    averagePerRequest: null,
    missingCostRequests: 0,
    missingTokenRequests: 1,
    estimatedCostRequests: 0,
  };
  const p = {
    schemaVersion: 1,
    source: "litellm-api-cache",
    summary: totals,
    period: { start: null, end: null, timezone: "Asia/Seoul" },
    filters: {},
    dataState: {},
    detail: { records: [] },
    daily: [],
    topUsers: [],
    users: [],
    teams: [],
    models: [],
  };
  validateTokens(p);
  assert.equal(p.summary.costUsd, 0);
  assert.equal(p.summary.total, null);
  const original = globalThis.fetch,
    c = new AbortController();
  try {
    globalThis.fetch = async (url, options) => {
      assert.ok(String(url).startsWith("/api/dashboard/v2/tokens?"));
      assert.ok(String(url).includes("model="));
      assert.equal(options?.signal, c.signal);
      assert.equal(
        (options?.headers as Record<string, string>).Authorization,
        "Bearer dashboard-only",
      );
      return new Response(JSON.stringify(p), { status: 200 });
    };
    await loadTokens(defaultQuery, "dashboard-only", c.signal);
  } finally {
    globalThis.fetch = original;
  }
  (p.summary as any).total = NaN;
  assert.throws(() => validateTokens(p));
});
test("token navigation is live and overview accepts connected token values", () => {
  assert.equal(readScreen("?screen=tokens"), "tokens");
  const p = overviewFixture();
  p.integrations.tokens = {
    status: "ready",
    source: "litellm",
    total: 15,
    input: 10,
    output: 5,
    requests: 1,
    averagePerRequest: 15,
    costUsd: 0,
  };
  validateOverview(p);
  assert.ok(overviewCsv(p).includes("연동 완료"));
});

test("category contract conserves all questions including pending and uncertain", async () => {
  const {validateCategories}=await import('./Categories');
  const p={schemaVersion:1,source:'category-llm-cache',period:{start:null,end:null,timezone:'Asia/Seoul'},summary:{questions:4,classified:2,pending:1,uncertain:1,noText:0,truncated:0,coveragePercent:50},distribution:[{name:'문서/RAG',value:2,percent:50},{name:'미분류',value:2,percent:50}],filters:{divisions:[],teams:[],positions:[],categories:[]},definitions:[],detail:{total:4,page:1,pageSize:50,records:[]}};
  assert.doesNotThrow(()=>validateCategories(p));
  assert.throws(()=>validateCategories({...p,summary:{...p.summary,questions:5}}));
  assert.throws(()=>validateCategories({...p,distribution:[{name:'문서/RAG',value:-1,percent:25}]}));
  assert.equal(readScreen('?screen=categories'),'categories');
});

test("overview accepts partial classification and requires category totals to match questions",()=>{
  const p=overviewFixture();
  p.summary.questions=4;
  p.integrations.categories={status:'ready',source:'litellm-classifier',records:[{name:'문서/RAG',value:1,percent:25},{name:'미분류',value:3,percent:75}],classified:1};
  assert.doesNotThrow(()=>validateOverview(p));
  p.integrations.categories.records![1].value=2;
  assert.throws(()=>validateOverview(p));
});
