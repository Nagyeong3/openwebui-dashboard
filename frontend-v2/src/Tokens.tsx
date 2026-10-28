import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, Coins, Loader2, RefreshCw } from "lucide-react";
import { request } from "./api";
import {
  Chart,
  Empty,
  Panel,
  Select,
  barOption,
  lineOption,
} from "./components";
import { number } from "./domain";
import { queryParams, type Query, type Payload } from "./live-api";

type Totals = {
  total: number | null;
  input: number | null;
  output: number | null;
  costUsd: number | null;
  requests: number;
  averagePerRequest: number | null;
  users?: number;
  unidentifiedRequests?: number;
  missingCostRequests: number;
  missingTokenRequests: number;
  estimatedCostRequests: number;
};
type Row = Totals & {
  id?: string;
  name?: string;
  team?: string;
  model?: string;
  division?: string;
  date?: string;
};
type Log = {
  id: string;
  at: number;
  model: string;
  prompt: number | null;
  completion: number | null;
  total: number | null;
  userName: string | null;
  team: string | null;
  costUsd: number | null;
  costSource: string;
};
export type TokenPayload = {
  schemaVersion: number;
  source: string;
  updatedAt: string;
  period: Payload["period"];
  summary: Totals;
  daily: Row[];
  topUsers: Row[];
  users: Row[];
  teams: Row[];
  models: Row[];
  filters: {
    divisions: string[];
    teams: string[];
    positions: string[];
    models: string[];
  };
  dataState: { stale: boolean; coverageStart: string; organization: string };
  detail: { records: Log[]; total: number; page: number; pageSize: number };
};
type Run = {
  id: string;
  kind: string;
  status: string;
  error: string | null;
  scanned: number;
  saved: number;
  skipped: number;
  pages: number;
};
type Status = {
  ready: boolean;
  configured: boolean;
  lastSuccess: string | null;
  logs: number;
  activeRunId: string | null;
  runs: Run[];
};
const ALL = "전체";
const value = (n: number | null | undefined) => (n == null ? "—" : number(n));
const money = (n: number | null | undefined) =>
  n == null ? "—" : "$" + n.toFixed(6);
export function validateTokens(p: unknown): asserts p is TokenPayload {
  const d = p as TokenPayload;
  if (
    !d ||
    d.schemaVersion !== 1 ||
    d.source !== "litellm-api-cache" ||
    !d.summary ||
    !d.filters ||
    !d.period ||
    d.period.timezone !== "Asia/Seoul" ||
    !d.dataState ||
    !d.detail ||
    !Array.isArray(d.detail.records)
  )
    throw new Error("토큰 API 응답 형식을 확인하세요.");
  for (const rows of [d.daily, d.topUsers, d.users, d.teams, d.models])
    if (!Array.isArray(rows)) throw new Error("토큰 집계 배열이 없습니다.");
  for (const row of [
    d.summary,
    ...d.daily,
    ...d.topUsers,
    ...d.users,
    ...d.teams,
    ...d.models,
  ])
    for (const key of [
      "total",
      "input",
      "output",
      "costUsd",
      "requests",
      "averagePerRequest",
    ] as const) {
      const n = row[key];
      if (n !== null && (typeof n !== "number" || !Number.isFinite(n) || n < 0))
        throw new Error("토큰 집계 수치가 잘못되었습니다.");
    }
}
export async function loadTokens(
  q: Query,
  token: string,
  signal?: AbortSignal,
): Promise<TokenPayload> {
  const result = await request("/api/dashboard/v2/tokens?" + queryParams(q), {
    signal,
    headers: token ? { Authorization: "Bearer " + token } : {},
  });
  validateTokens(result);
  return result;
}
function Toggle({
  mode,
  onChange,
  label,
}: {
  mode: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <div
      className="overview-toggle"
      role="group"
      aria-label={label + " 표시 방식"}
    >
      <span className={"overview-toggle-thumb " + (mode ? "right" : "")} />
      <button aria-pressed={!mode} onClick={() => onChange(false)}>
        표
      </button>
      <button aria-pressed={mode} onClick={() => onChange(true)}>
        그래프
      </button>
    </div>
  );
}
export default function Tokens({
  q,
  token,
  revision,
  onChange,
  onPeriod,
  onUpdated,
  dark,
}: {
  q: Query;
  token: string;
  revision: number;
  onChange: (v: Partial<Query>) => void;
  onPeriod: (p: Payload["period"]) => void;
  onUpdated: () => void;
  dark: boolean;
}) {
  const [state, setState] = useState<{
      key: string;
      data?: TokenPayload;
      error?: string;
    }>({ key: "" }),
    [status, setStatus] = useState<Status | null>(null),
    [jobError, setJobError] = useState(""),
    [starting, setStarting] = useState(false);
  const [graph, setGraph] = useState(true),
    [rankingGraph, setRankingGraph] = useState(true),
    [tab, setTab] = useState<"users" | "teams" | "models" | "logs">("users");
  const abort = useRef<AbortController | null>(null);
  const done = useRef("");
  const key = queryParams(q).toString() + "|" + revision + "|" + token;
  const data = state.key === key ? state.data : undefined,
    error = state.key === key ? state.error : undefined;
  const headers: Record<string, string> = token
    ? { Authorization: "Bearer " + token }
    : {};
  useEffect(() => {
    const c = new AbortController();
    abort.current = c;
    loadTokens(q, token, c.signal)
      .then((d) => {
        if (!c.signal.aborted) {
          setState({ key, data: d });
          onPeriod(d.period);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setState({ key, error: e.message });
      });
    return () => c.abort();
  }, [key]);
  useEffect(() => {
    const c = new AbortController();
    request("/api/dashboard/v2/tokens/status", { signal: c.signal, headers })
      .then((s) => {
        if (!c.signal.aborted) setStatus(s as Status);
      })
      .catch((e) => {
        if (!c.signal.aborted) setJobError(e.message);
      });
    return () => c.abort();
  }, [revision, token]);
  useEffect(() => {
    if (!status?.activeRunId) return;
    const c = new AbortController(),
      id = status.activeRunId;
    const timer = setInterval(() => {
      request("/api/dashboard/v2/tokens/status", { signal: c.signal, headers })
        .then((s) => {
          if (c.signal.aborted) return;
          setStatus(s as Status);
          if (!(s as Status).activeRunId && done.current !== id) {
            done.current = id;
            onUpdated();
          }
        })
        .catch((e) => {
          if (!c.signal.aborted) setJobError(e.message);
        });
    }, 2000);
    return () => {
      c.abort();
      clearInterval(timer);
    };
  }, [status?.activeRunId, token]);
  async function sync(kind: "quick" | "full") {
    setStarting(true);
    setJobError("");
    try {
      const r = await request("/api/dashboard/v2/tokens/sync?kind=" + kind, {
        method: "POST",
        headers,
      });
      const s = (await request("/api/dashboard/v2/tokens/status", {
        headers,
      })) as Status;
      setStatus(s);
      if (!s.activeRunId && done.current !== r.runId) {
        done.current = r.runId;
        onUpdated();
      }
    } catch (e) {
      setJobError(e instanceof Error ? e.message : "동기화 시작 실패");
    } finally {
      setStarting(false);
    }
  }
  async function csv() {
    try {
      const base = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
      const r = await fetch(
        base + "/api/dashboard/v2/tokens/export?" + queryParams(q),
        { headers, cache: "no-store" },
      );
      if (!r.ok || !r.headers.get("Content-Type")?.includes("text/csv"))
        throw new Error("토큰 CSV 내보내기 실패");
      const url = URL.createObjectURL(await r.blob()),
        a = document.createElement("a");
      a.href = url;
      a.download = "token-usage.csv";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setJobError(e instanceof Error ? e.message : "CSV 오류");
    }
  }
  const working = starting || !!status?.activeRunId,
    run = status?.runs[0];
  const filters = data?.filters || {
    divisions: [ALL],
    teams: [ALL],
    positions: [ALL],
    models: [ALL],
  };
  return (
    <div className="token-screen">
      <section className="token-sync-bar">
        <div>
          <strong>LiteLLM 토큰 로그 수집</strong>
          <p>
            마지막 성공:{" "}
            {status?.lastSuccess
              ? new Date(status.lastSuccess).toLocaleString("ko-KR", {
                  timeZone: "Asia/Seoul",
                })
              : "아직 없음"}{" "}
            · 저장 로그 {value(status?.logs)}건
          </p>
        </div>
        <div className="live-heading-actions">
          <button
            className="button"
            disabled={working}
            onClick={() => void sync("full")}
          >
            전체 재수집
          </button>
          <button
            className="button primary"
            disabled={working}
            onClick={() => void sync("quick")}
          >
            {working ? (
              <Loader2 className="spinning" size={16} />
            ) : (
              <RefreshCw size={16} />
            )}
            로그 동기화
          </button>
        </div>
      </section>
      {status && !status.configured && (
        <p className="live-warning">
          사용량 연결 설정을 확인하세요. 설정 후 서버를 재시작하세요.
        </p>
      )}
      {run && (
        <p
          className={
            "live-note " + (run.status === "failed" ? "token-error" : "")
          }
          role="status"
        >
          최근 수집: {run.kind} / {run.status} · 조회 {value(run.scanned)}건 ·
          저장 대상 {value(run.saved)}건 · 별칭 제외 {value(run.skipped)}건 ·{" "}
          {run.pages}페이지 {run.error && "· " + run.error}
        </p>
      )}
      {jobError && (
        <p role="alert" className="token-error">
          {jobError}
        </p>
      )}
      <section className="live-filters" aria-label="토큰 필터">
        <Select
          label="실 / 본부"
          value={q.division}
          values={filters.divisions}
          onChange={(division) =>
            onChange({ division, team: ALL, position: ALL })
          }
        />
        <Select
          label="팀"
          value={q.team}
          values={filters.teams}
          onChange={(team) => onChange({ team, position: ALL })}
        />
        <Select
          label="직급"
          value={q.position}
          values={filters.positions}
          onChange={(position) => onChange({ position })}
        />
        <Select
          label="모델"
          value={q.model}
          values={filters.models}
          onChange={(model) => onChange({ model })}
        />
        <button
          className="button"
          onClick={() =>
            onChange({ division: ALL, team: ALL, position: ALL, model: ALL })
          }
        >
          필터 초기화
        </button>
      </section>
      <p className="live-note">
        모델 필터는 전체 로그에, 조직 필터는 OpenWebUI 사용자로 식별된 로그에
        적용됩니다. 질문 수와 모델 요청 수는 서로 다른 지표입니다.
      </p>
      {!data && !error && (
        <div className="live-loading" role="status">
          <Loader2 className="spinning" />
          토큰 사용량을 불러오는 중입니다.
        </div>
      )}
      {error && (
        <div className="overview-pending">
          <Coins size={32} />
          <strong>토큰 데이터를 표시할 수 없습니다</strong>
          <p>{error}</p>
          <p>최초 로그 동기화가 필요하거나 연결·인증 설정을 확인해야 합니다.</p>
        </div>
      )}
      {data && (
        <>
          {data.dataState.stale && (
            <div className="live-warning">
              최근 수집이 완료되지 않아 마지막 성공 데이터를 표시합니다.
            </div>
          )}
          {(data.summary.missingCostRequests > 0 ||
            data.summary.missingTokenRequests > 0) && (
            <p className="live-warning">
              비용 누락 {data.summary.missingCostRequests}건 · 토큰 누락{" "}
              {data.summary.missingTokenRequests}건. 누락된 합계는 대시로
              표시합니다.
            </p>
          )}
          <div className="token-primary">
            {[
              ["총 토큰 (토큰)", value(data.summary.total)],
              ["입력 토큰 (토큰)", value(data.summary.input)],
              ["출력 토큰 (토큰)", value(data.summary.output)],
              ["추정 비용 (USD)", money(data.summary.costUsd)],
            ].map(([label, n]) => (
              <article className="metric" key={label}>
                <div className="metric-top">
                  {label}
                  <Coins size={17} />
                </div>
                <strong className="pending-value">{n}</strong>
                <div className="metric-note">
                  {label === "추정 비용 (USD)"
                    ? "USD"
                    : "토큰"}
                </div>
              </article>
            ))}
          </div>
          <div className="token-secondary">
            {[
              ["요청 수 (건)", value(data.summary.requests)],
              ["식별 사용자 수 (명)", value(data.summary.users)],
              ["요청당 평균 (토큰/요청)", value(data.summary.averagePerRequest)],
            ].map(([label, n]) => (
              <article className="metric" key={label}>
                <div className="metric-top">{label}</div>
                <strong className="pending-value">{n}</strong>
              </article>
            ))}
          </div>
          <p className="live-note">
            미식별 요청 {value(data.summary.unidentifiedRequests)}건 · 가격표
            추정 {data.summary.estimatedCostRequests}건 · 수집 범위 시작{" "}
            {new Date(
              Number(data.dataState.coverageStart) * 1000,
            ).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" })}
          </p>
          <div className="live-charts">
            <Panel
              title="토큰 사용 추이"
              subtitle="단위: 토큰 · K = 1,000 · M = 1,000,000"
            >
              <div className="overview-chart-body">
                {graph ? (
                  <Chart
                    dark={dark}
                    label="일별 전체 토큰 수"
                    height={270}
                    option={{
                      ...lineOption(
                        data.daily.map((d) => ({
                          date: d.date!,
                          value: d.total || 0,
                        })),
                        dark,
                        true,
                      ),
                      series: [
                        {
                          ...lineOption([], false, true).series[0],
                          smooth: 0,
                          data: data.daily.map((d) => d.total),
                        },
                      ],
                    }}
                  />
                ) : (
                  <div className="overview-table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>날짜</th>
                          <th>전체 토큰 (토큰)</th>
                          <th>비용 (USD)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.daily.map((d) => (
                          <tr key={d.date}>
                            <td>{d.date}</td>
                            <td>{value(d.total)}</td>
                            <td>{money(d.costUsd)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="overview-panel-footer">
                <span></span>
                <Toggle
                  label="토큰 사용 추이"
                  mode={graph}
                  onChange={setGraph}
                />
              </div>
            </Panel>
            <Panel
              title="토큰 사용량 Top 10"
              subtitle="단위: 토큰 · 식별된 사용자 기준 · K = 1,000 · M = 1,000,000"
            >
              <div className="overview-chart-body">
                {!data.topUsers.length ? (
                  <Empty />
                ) : rankingGraph ? (
                  <Chart
                    dark={dark}
                    label="사용자별 토큰 Top10"
                    height={270}
                    option={barOption(
                      data.topUsers
                        .filter((r) => r.total !== null)
                        .map((r) => ({ name: r.name!, value: r.total! })),
                      dark,
                      "토큰",
                    )}
                  />
                ) : (
                  <div className="overview-table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>사용자명</th>
                          <th>팀</th>
                          <th>토큰 수 (토큰)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.topUsers.map((r) => (
                          <tr key={r.id}>
                            <td>{r.name}</td>
                            <td>{r.team}</td>
                            <td>{value(r.total)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
              <div className="overview-panel-footer">
                <span></span>
                <Toggle
                  label="토큰 Top10"
                  mode={rankingGraph}
                  onChange={setRankingGraph}
                />
              </div>
            </Panel>
          </div>
          <Panel
            title="토큰 사용 상세"
            action={
              <button className="button" onClick={() => void csv()}>
                <ArrowDownToLine size={15} />
                전체 로그 CSV
              </button>
            }
          >
            <div className="table-toolbar">
              <div className="table-controls">
                {(
                  [
                    ["users", "사용자별"],
                    ["teams", "팀별"],
                    ["models", "모델별"],
                    ["logs", "요청 로그"],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    className={"button " + (tab === key ? "primary" : "")}
                    onClick={() => setTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="overview-table-scroll">
              {tab === "logs" ? (
                <table>
                  <thead>
                    <tr>
                      <th>시각</th>
                      <th>모델</th>
                      <th>사용자</th>
                      <th>입력 (토큰)</th>
                      <th>출력 (토큰)</th>
                      <th>전체 (토큰)</th>
                      <th>비용 (USD)</th>
                      <th>비용 기준</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.detail.records.map((r) => (
                      <tr key={r.id}>
                        <td>
                          {new Date(r.at * 1000).toLocaleString("ko-KR", {
                            timeZone: "Asia/Seoul",
                          })}
                        </td>
                        <td>{r.model}</td>
                        <td>{r.userName || "미식별"}</td>
                        <td>{value(r.prompt)}</td>
                        <td>{value(r.completion)}</td>
                        <td>{value(r.total)}</td>
                        <td>{money(r.costUsd)}</td>
                        <td>{r.costSource}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <table>
                  <thead>
                    <tr>
                      <th>
                        {tab === "users"
                          ? "사용자명"
                          : tab === "teams"
                            ? "실 / 팀"
                            : "모델"}
                      </th>
                      <th>요청 수 (건)</th>
                      <th>입력 (토큰)</th>
                      <th>출력 (토큰)</th>
                      <th>전체 (토큰)</th>
                      <th>비용 (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data[tab].map((r, i) => (
                      <tr
                        key={
                          r.id ||
                          r.model ||
                          JSON.stringify([r.division, r.team, i])
                        }
                      >
                        <td>
                          {tab === "users"
                            ? r.name
                            : tab === "teams"
                              ? r.division + " / " + r.team
                              : r.model}
                        </td>
                        <td>{value(r.requests)}</td>
                        <td>{value(r.input)}</td>
                        <td>{value(r.output)}</td>
                        <td>{value(r.total)}</td>
                        <td>{money(r.costUsd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            {tab === "logs" && (
              <div className="table-footer">
                <span>
                  전체 {data.detail.total}건 · {q.page}페이지
                </span>
                <div className="table-controls">
                  <button
                    className="button"
                    disabled={q.page <= 1}
                    onClick={() => onChange({ page: q.page - 1 })}
                  >
                    이전
                  </button>
                  <button
                    className="button"
                    disabled={q.page * q.pageSize >= data.detail.total}
                    onClick={() => onChange({ page: q.page + 1 })}
                  >
                    다음
                  </button>
                </div>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}
