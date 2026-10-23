import { useEffect, useRef, useState } from "react";
import { MotionConfig, motion } from "motion/react";
import {
  Activity,
  AlertTriangle,
  ArrowDownToLine,
  ChevronLeft,
  ChevronRight,
  FileText,
  Layers3,
  Loader2,
  Menu,
  Moon,
  RefreshCw,
  Settings2,
  Sun,
  Users,
  X,
} from "lucide-react";
import {
  Chart,
  Empty,
  IconButton,
  Metric,
  Modal,
  Panel,
  Select,
  barOption,
  lineOption,
} from "./components";
import { number } from "./domain";
import {
  defaultQuery,
  loadUsers,
  queryParams,
  readQuery,
  type Payload,
  type Person,
  type Query,
  type Team,
  type View,
} from "./live-api";

const ALL = "전체";
const dateTime = (s: string | null) =>
  s
    ? new Date(s).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })
    : "사용 기록 없음";
const viewNames: Record<View, string> = {
  user: "전체 사용자",
  team: "팀별 현황",
  leader: "팀장 사용량",
};
const apiBase = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

export default function LiveApp() {
  const [q, setQ] = useState<Query>(() => readQuery(location.search));
  const [dark, setDark] = useState(
    () => localStorage.getItem("oui-theme") === "dark",
  );
  const [mobile, setMobile] = useState(false),
    [revision, refresh] = useState(0);
  const [token, setToken] = useState(""),
    [credential, setCredential] = useState(""),
    [auth, setAuth] = useState(false);
  const [search, setSearch] = useState(q.search),
    [drawer, setDrawer] = useState<Person | null>(null);
  const [exporting, setExporting] = useState(false),
    [exportError, setExportError] = useState("");
  const [state, setState] = useState<{
    key: string;
    data?: Payload;
    error?: string;
  }>({ key: "" });
  const [choices, setChoices] = useState<Payload["filters"]>({
    divisions: [ALL],
    teams: [ALL],
    positions: [ALL],
    matchStatuses: [ALL],
  });
  const exportController = useRef<AbortController | null>(null);
  const key = queryParams(q).toString() + "|" + revision + "|" + token;
  const data = state.key === key ? state.data : undefined;
  const error = state.key === key ? state.error : undefined;
  const loading = !data && !error;
  const patch = (values: Partial<Query>) => {
    setQ((old) => ({ ...old, page: 1, ...values }));
    setDrawer(null);
    setExportError("");
  };
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    localStorage.setItem("oui-theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q)) {
      if ((k === "start" || k === "end") && q.range !== "custom") continue;
      if (String(v)) p.set(k, String(v));
    }
    history.replaceState(null, "", location.pathname + "?" + p);
    const controller = new AbortController();
    loadUsers(q, token, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        // A changed roster/filter may shrink the last page after a refresh.
        const last = Math.max(1, Math.ceil(payload.detail.total / q.pageSize));
        if (q.page > last) {
          setQ((old) => ({ ...old, page: last }));
          return;
        }
        setChoices(payload.filters);
        setState({ key, data: payload });
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setState({
            key,
            error:
              e instanceof Error
                ? e.message
                : "사용자 정보를 불러오지 못했습니다.",
          });
      });
    return () => controller.abort();
  }, [key]);
  useEffect(() => {
    const pop = () => {
      const query = readQuery(location.search);
      setQ(query);
      setSearch(query.search);
      setDrawer(null);
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    exportController.current?.abort();
    setExporting(false);
    return () => exportController.current?.abort();
  }, [key]);
  const changeView = (view: View) => {
    patch({ view, pageSize: 50 });
    setMobile(false);
  };
  const selectRange = (range: string) => {
    if (range !== "custom") {
      patch({ range });
      return;
    }
    const today = new Date().toLocaleDateString("en-CA", {
      timeZone: "Asia/Seoul",
    });
    patch({
      range,
      start: data?.period.start || today,
      end: data?.period.end || today,
    });
  };
  async function exportCsv() {
    const c = new AbortController();
    exportController.current = c;
    setExporting(true);
    setExportError("");
    try {
      const response = await fetch(
        apiBase + "/api/dashboard/v2/users/export?" + queryParams(q),
        {
          signal: c.signal,
          headers: token ? { Authorization: "Bearer " + token } : {},
        },
      );
      if (
        !response.ok ||
        !response.headers.get("Content-Type")?.includes("text/csv")
      )
        throw new Error(
          "CSV 내보내기에 실패했습니다. 연결과 인증을 확인하세요.",
        );
      const blob = await response.blob();
      if (c.signal.aborted) return;
      const url = URL.createObjectURL(blob),
        link = document.createElement("a");
      link.href = url;
      link.download = `openwebui-${q.view}.csv`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      if (!c.signal.aborted)
        setExportError(e instanceof Error ? e.message : "CSV 내보내기 실패");
    } finally {
      if (!c.signal.aborted) setExporting(false);
    }
  }
  const records = data?.detail.records || [];
  return (
    <MotionConfig reducedMotion="user">
      <div className="app live-app">
        {mobile && (
          <button
            className="mobile-scrim"
            aria-label="메뉴 닫기"
            onClick={() => setMobile(false)}
          />
        )}
        <aside className={"sidebar " + (mobile ? "mobile-open" : "")}>
          <div className="brand">
            <span className="brand-symbol">
              <Layers3 size={24} />
            </span>
            <span className="brand-copy">
              OpenWebUI<span>ANALYTICS WORKSPACE</span>
            </span>
          </div>
          <div className="workspace-label">
            <span className="workspace-dot" /> API Analytics v2
          </div>
          <div className="nav-label">PEOPLE & ORGANIZATION</div>
          <nav aria-label="사용자 분석 보기">
            {(Object.keys(viewNames) as View[]).map((view) => (
              <button
                key={view}
                className={"nav-item " + (q.view === view ? "active" : "")}
                aria-current={q.view === view ? "page" : undefined}
                onClick={() => changeView(view)}
              >
                <Users size={18} />
                <span>{viewNames[view]}</span>
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="source-health">
              <span className={"status-dot " + (error ? "warning" : "")} />
              <div>
                OpenWebUI API
                <small>
                  {error
                    ? "연결 확인 필요"
                    : data
                      ? "분석 캐시 연결"
                      : "데이터 확인 중"}
                </small>
              </div>
            </div>
            <p className="live-note">
              OpenWebUI 등록 사용자 기준
              <br />
              CSV는 조직 정보만 보강합니다.
            </p>
          </div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <div className="breadcrumb">
              <IconButton label="메뉴" onClick={() => setMobile(!mobile)}>
                <Menu size={18} />
              </IconButton>
              <span>Workspace</span>
              <ChevronRight size={13} />
              <strong>People</strong>
            </div>
            <div className="topbar-actions">
              <span className="env-badge">API</span>
              <IconButton
                label="대시보드 인증 설정"
                onClick={() => {
                  setCredential(token);
                  setAuth(true);
                }}
              >
                <Settings2 size={18} />
              </IconButton>
              <IconButton
                label={dark ? "라이트 모드" : "다크 모드"}
                onClick={() => setDark(!dark)}
              >
                {dark ? <Sun size={18} /> : <Moon size={18} />}
              </IconButton>
            </div>
          </header>
          <main className="main live-main">
            <div className="page-heading">
              <div>
                <span className="eyebrow">PEOPLE ANALYTICS</span>
                <h1>{viewNames[q.view]}</h1>
                <p className="muted">
                  사용 기록이 없는 사용자도 놓치지 않는 조직의 AI 활용 현황
                </p>
              </div>
              <button
                className="button"
                onClick={() => refresh((n) => n + 1)}
                disabled={loading}
              >
                <RefreshCw size={16} className={loading ? "spinning" : ""} />
                다시 조회
              </button>
            </div>
            <section className="live-filters" aria-label="기간 및 조직 필터">
              <label>
                기간
                <select
                  value={q.range}
                  onChange={(e) => selectRange(e.target.value)}
                >
                  <option value="7d">최근 7일</option>
                  <option value="30d">최근 30일</option>
                  <option value="90d">최근 90일</option>
                  <option value="all">전체 기간</option>
                  <option value="custom">직접 지정</option>
                </select>
              </label>
              <Select
                label="실 / 본부"
                value={q.division}
                values={choices.divisions}
                onChange={(division) =>
                  patch({ division, team: ALL, position: ALL })
                }
              />
              <Select
                label="팀"
                value={q.team}
                values={choices.teams}
                onChange={(team) => patch({ team, position: ALL })}
              />
              <Select
                label="직급"
                value={q.position}
                values={choices.positions}
                onChange={(position) => patch({ position })}
              />
              <Select
                label="조직 매핑"
                value={q.matchStatus}
                values={choices.matchStatuses}
                onChange={(matchStatus) => patch({ matchStatus })}
              />
              <button
                className="button"
                onClick={() => {
                  setQ({ ...defaultQuery, view: q.view });
                  setSearch("");
                  setDrawer(null);
                }}
              >
                초기화
              </button>
            </section>
            {q.range === "custom" && (
              <form
                className="live-custom"
                onSubmit={(e) => {
                  e.preventDefault();
                  const f = new FormData(e.currentTarget);
                  patch({
                    start: String(f.get("start")),
                    end: String(f.get("end")),
                  });
                }}
                key={q.start + q.end}
              >
                <label>
                  시작일
                  <input
                    required
                    name="start"
                    type="date"
                    defaultValue={q.start}
                  />
                </label>
                <label>
                  종료일
                  <input required name="end" type="date" defaultValue={q.end} />
                </label>
                <button className="button primary">기간 적용</button>
              </form>
            )}
            <p className="live-note">
              최근 기간은 마지막 성공 수집일을 기준으로 계산합니다. 날짜 경계는
              한국 시간입니다.
            </p>
            {loading && (
              <div className="live-loading" role="status">
                <Loader2 className="spinning" size={24} />
                <span>사용자 현황을 불러오는 중입니다.</span>
              </div>
            )}
            {error && (
              <div className="error-state" role="alert">
                <AlertTriangle size={28} />
                <h2>사용자 데이터를 표시할 수 없습니다</h2>
                <p>{error}</p>
                <p>
                  최초 수집 전에는 서버에서 전체 동기화를 실행하세요. 인증이
                  필요하면 상단 설정에서 대시보드 토큰을 입력하세요.
                </p>
                <button
                  className="button primary"
                  onClick={() => refresh((n) => n + 1)}
                >
                  다시 시도
                </button>
              </div>
            )}
            {data && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
              >
                {data.dataState.stale && (
                  <div className="live-warning" role="status">
                    <AlertTriangle size={17} />
                    최신 동기화가 완료되지 않아 마지막 성공 데이터를 표시합니다.
                    {data.dataState.activeRunId ? " 수집이 진행 중입니다." : ""}
                  </div>
                )}
                {data.dataState.organization !== "loaded" && (
                  <p className="live-note">
                    조직 CSV 상태: {data.dataState.organization}. 미매칭
                    사용자는 기타 조직으로 표시됩니다.
                  </p>
                )}
                <div className="metrics-grid live-metrics">
                  {[
                    [
                      "표시 사용자",
                      data.summary.users,
                      "필터에 맞는 전체 등록 사용자",
                      Users,
                    ],
                    [
                      "활성 사용자",
                      data.summary.activeUsers,
                      "기간 내 질문 1건 이상",
                      Activity,
                    ],
                    [
                      "사용량 0",
                      data.summary.zeroUsageUsers,
                      "전체 목록과 순위에 포함",
                      Users,
                    ],
                    [
                      "질문 수",
                      data.summary.questions,
                      "저장된 사용자 메시지 기준",
                      FileText,
                    ],
                    [
                      "채팅방 수",
                      data.summary.chats,
                      "기간 내 질문의 고유 채팅방",
                      Layers3,
                    ],
                    [
                      "파일 첨부 질문",
                      data.summary.attachmentQuestions,
                      "파일이 있는 사용자 질문",
                      FileText,
                    ],
                  ].map(([label, value, note, Icon]) => {
                    const I = Icon as typeof Users;
                    return (
                      <Metric
                        key={String(label)}
                        label={String(label)}
                        value={Number(value)}
                        note={String(note)}
                        icon={<I size={17} />}
                      />
                    );
                  })}
                </div>
                <div className="live-charts">
                  <Panel
                    title="질문 추이"
                    subtitle="선택 필터 전체 집계 · 현재 페이지와 무관"
                  >
                    <Chart
                      dark={dark}
                      height={250}
                      label="일별 사용자 질문 수"
                      option={lineOption(
                        data.daily.map((d) => ({
                          date: d.date,
                          value: d.questions,
                        })),
                        dark,
                      )}
                    />
                  </Panel>
                  <Panel
                    title="현재 페이지 질문 수"
                    subtitle="현재 정렬 순서 중 앞 10개 행"
                  >
                    <Chart
                      dark={dark}
                      height={250}
                      label="현재 페이지 사용자 또는 팀별 질문 수"
                      option={barOption(
                        records
                          .slice(0, 10)
                          .map((r) => ({
                            name: "name" in r ? r.name : r.team,
                            value: r.questions,
                          })),
                        dark,
                      )}
                    />
                  </Panel>
                </div>
                <Panel
                  title={viewNames[q.view] + " 전체 순위"}
                  subtitle="질문 수 순서 · 0건 사용자 포함 · 동률은 이름/ID 순서"
                >
                  <div className="table-toolbar">
                    <form
                      className="table-search"
                      onSubmit={(e) => {
                        e.preventDefault();
                        patch({ search });
                      }}
                    >
                      <input
                        aria-label="사용자명 또는 팀 검색"
                        placeholder="사용자명 또는 팀 검색"
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                      />
                      <button className="button">검색</button>
                    </form>
                    <div className="table-controls">
                      {q.view === "leader" && (
                        <>
                          <button
                            className="button"
                            onClick={() =>
                              patch({ pageSize: 10, order: "desc" })
                            }
                          >
                            Top 10
                          </button>
                          <button
                            className="button"
                            onClick={() =>
                              patch({ pageSize: 50, order: "desc" })
                            }
                          >
                            전체 순위
                          </button>
                        </>
                      )}
                      <button
                        className="button"
                        onClick={() =>
                          patch({ order: q.order === "desc" ? "asc" : "desc" })
                        }
                      >
                        질문 {q.order === "desc" ? "많은 순 ↓" : "적은 순 ↑"}
                      </button>
                      <button
                        className="button"
                        disabled={exporting}
                        onClick={() => void exportCsv()}
                      >
                        <ArrowDownToLine size={15} />
                        {exporting ? "내보내는 중" : "전체 CSV"}
                      </button>
                    </div>
                  </div>
                  {exportError && <p role="alert">{exportError}</p>}
                  {!records.length ? (
                    <Empty />
                  ) : (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>순서</th>
                            <th>{q.view === "team" ? "팀" : "사용자명"}</th>
                            <th>실 / 본부</th>
                            <th>
                              {q.view === "team" ? "등록 사용자" : "팀 / 직급"}
                            </th>
                            <th>질문 수</th>
                            <th>채팅방 수</th>
                            <th>
                              {q.view === "team" ? "활성 사용자" : "조직 매핑"}
                            </th>
                            <th>{q.view === "team" ? "첨부 질문" : "상태"}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {records.map((r, i) => {
                            const person = "id" in r ? (r as Person) : null,
                              team = r as Team;
                            return (
                              <tr
                                key={
                                  person?.id ||
                                  JSON.stringify([r.division, r.team])
                                }
                              >
                                <td>{(q.page - 1) * q.pageSize + i + 1}</td>
                                <td>
                                  {person ? (
                                    <button
                                      className="live-person"
                                      onClick={() => setDrawer(person)}
                                    >
                                      {person.name || "(이름 없음)"}
                                    </button>
                                  ) : (
                                    <button
                                      className="live-person"
                                      onClick={() => {
                                        patch({
                                          view: "user",
                                          division: r.division,
                                          team: r.team,
                                        });
                                      }}
                                    >
                                      {r.team}
                                    </button>
                                  )}
                                </td>
                                <td>{r.division}</td>
                                <td>
                                  {person
                                    ? `${person.team} / ${person.position}`
                                    : number(team.users)}
                                </td>
                                <td>{number(r.questions)}</td>
                                <td>{number(r.chats)}</td>
                                <td>
                                  {person
                                    ? person.mapping
                                    : number(team.activeUsers)}
                                </td>
                                <td>
                                  {person ? (
                                    <span
                                      className={
                                        "activity-pill " +
                                        (!r.questions ? "inactive" : "")
                                      }
                                    >
                                      {r.questions ? "활성" : "사용량 0"}
                                    </span>
                                  ) : (
                                    number(team.attachmentQuestions)
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                  <div className="table-footer">
                    <span>
                      전체 {number(data.detail.total)}
                      {q.view === "team" ? "개 팀" : "명"} · {q.page} /{" "}
                      {Math.max(1, Math.ceil(data.detail.total / q.pageSize))}{" "}
                      페이지
                    </span>
                    <div className="live-pagination">
                      <label>
                        페이지 크기
                        <select
                          aria-label="페이지 크기"
                          value={q.pageSize}
                          onChange={(e) =>
                            patch({ pageSize: Number(e.target.value) })
                          }
                        >
                          {[10, 25, 50, 100].map((n) => (
                            <option key={n}>{n}</option>
                          ))}
                        </select>
                      </label>
                      <button
                        className="button"
                        aria-label="이전 페이지"
                        disabled={q.page <= 1}
                        onClick={() => patch({ page: q.page - 1 })}
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <button
                        className="button"
                        aria-label="다음 페이지"
                        disabled={q.page * q.pageSize >= data.detail.total}
                        onClick={() => patch({ page: q.page + 1 })}
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>
                </Panel>
                <div className="live-note live-unconnected">
                  토큰·비용·질문 카테고리는 아직 연결되지 않았습니다. 이번
                  화면은 OpenWebUI 질문 활동만 표시합니다.
                </div>
                <footer className="page-footer">
                  <span>마지막 성공 수집: {dateTime(data.updatedAt)}</span>
                  <span>
                    {data.period.start || "전체"} — {data.period.end || "전체"}{" "}
                    · Asia/Seoul
                  </span>
                </footer>
              </motion.div>
            )}
          </main>
        </div>
        {auth && (
          <Modal title="대시보드 인증" onClose={() => setAuth(false)}>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setToken(credential.trim());
                setAuth(false);
              }}
            >
              <p>
                백엔드에 DASHBOARD_API_TOKEN을 설정한 경우에만 입력하세요.
                OpenWebUI 관리자 키를 입력하지 마세요. 입력값은 메모리에만
                유지되며 새로고침하면 지워집니다.
              </p>
              <label className="live-auth">
                대시보드 토큰
                <input
                  type="password"
                  autoComplete="off"
                  value={credential}
                  onChange={(e) => setCredential(e.target.value)}
                />
              </label>
              <button className="button primary">적용</button>
            </form>
          </Modal>
        )}
        {drawer && (
          <Modal drawer title="사용자 상세" onClose={() => setDrawer(null)}>
            <div className="person-detail">
              <span className="detail-avatar">{drawer.name.slice(-2)}</span>
              <h3>{drawer.name}</h3>
              <p>
                {drawer.division} · {drawer.team} · {drawer.position}
              </p>
            </div>
            <div className="detail-metrics">
              <div>
                <span>질문</span>
                <strong>{number(drawer.questions)}</strong>
              </div>
              <div>
                <span>채팅방</span>
                <strong>{number(drawer.chats)}</strong>
              </div>
              <div>
                <span>첨부 질문</span>
                <strong>{number(drawer.attachments)}</strong>
              </div>
            </div>
            <dl className="detail-meta">
              <dt>사용자 ID</dt>
              <dd>{drawer.id}</dd>
              <dt>이메일</dt>
              <dd>{drawer.email || "없음"}</dd>
              <dt>조직 매핑</dt>
              <dd>{drawer.mapping}</dd>
              <dt>마지막 질문</dt>
              <dd>{dateTime(drawer.lastUsedAt)}</dd>
              <dt>주 사용 모델</dt>
              <dd>{drawer.primaryModel || "기록 없음"}</dd>
              <dt>원천</dt>
              <dd>OpenWebUI API</dd>
            </dl>
            <p className="detail-note">
              질문 0건 사용자도 OpenWebUI 명부에 존재하면 표시됩니다. 토큰과
              비용은 아직 연결되지 않았습니다.
            </p>
            <button className="button" onClick={() => setDrawer(null)}>
              <X size={15} />
              닫기
            </button>
          </Modal>
        )}
      </div>
    </MotionConfig>
  );
}
