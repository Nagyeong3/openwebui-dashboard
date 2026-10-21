import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BarChart3,
  Bell,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Database,
  FileText,
  Layers3,
  LayoutDashboard,
  Loader2,
  Menu,
  Moon,
  MoreHorizontal,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Terminal,
  TrendingUp,
  Users,
  Wallet,
  X,
  Zap,
  AlertTriangle,
  CircleHelp,
  PanelLeftClose,
  ChevronDown,
  RotateCcw,
} from "lucide-react";
import { toPng } from "html-to-image";
import exportFontUrl from "@fontsource/noto-sans-kr/files/noto-sans-kr-korean-400-normal.woff2?url";
import {
  ALL,
  addDays,
  breakdown,
  compact,
  csvText,
  defaults,
  dollars,
  isLeader,
  number,
  options,
  previous,
  select,
  teamRows,
  trend,
  type Filters,
  type Operation,
  type Page,
  type Snapshot,
  type UserRow,
} from "./domain";
import { demo, loadSnapshot, runUpdate } from "./api";
import {
  barOption,
  Chart,
  Empty,
  IconButton,
  lineOption,
  Metric,
  Modal,
  palette,
  Panel,
  Select,
} from "./components";

const pages: {
  id: Page;
  name: string;
  en: string;
  description: string;
  icon: typeof Users;
}[] = [
  {
    id: "overview",
    name: "사용 현황",
    en: "Overview",
    description: "조직의 AI 활용 흐름을 한눈에 살펴보세요.",
    icon: LayoutDashboard,
  },
  {
    id: "users",
    name: "사용자 분석",
    en: "People",
    description: "조직과 사용자별 활용 현황에서 다음 기회를 발견하세요.",
    icon: Users,
  },
  {
    id: "tokens",
    name: "토큰 사용량",
    en: "Usage & cost",
    description: "모델별 토큰 사용과 비용을 투명하게 확인하세요.",
    icon: Layers3,
  },
  {
    id: "operations",
    name: "운영 업데이트",
    en: "Operations",
    description: "데이터 수집부터 분석 반영까지, 운영 흐름을 관리하세요.",
    icon: RefreshCw,
  },
];
function initialPage(): Page {
  const p = new URLSearchParams(location.search).get("page");
  return pages.some((x) => x.id === p) ? (p as Page) : "overview";
}
function initialFilters(end: string): Filters {
  const f = defaults(end),
    p = new URLSearchParams(location.search);
  for (const k of Object.keys(f) as (keyof Filters)[])
    if (p.get(k)) f[k] = p.get(k)!;
  if (
    !validDate(f.start) ||
    !validDate(f.end) ||
    f.start > f.end ||
    f.start < addDays(f.end, -730)
  ) {
    f.start = addDays(end, -29);
    f.end = end;
  }
  return f;
}
function validDate(s: string) {
  return (
    /^\d{4}-\d{2}-\d{2}$/.test(s) &&
    !Number.isNaN(Date.parse(s)) &&
    new Date(s).toISOString().slice(0, 10) === s
  );
}
const shortDate = (s: string) =>
  new Date(s).toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
function download(
  content: string,
  file: string,
  type = "text/csv;charset=utf-8",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = file;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function App() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [page, setPage] = useState<Page>(initialPage),
    [filters, setFilters] = useState<Filters>(() =>
      initialFilters("2026-10-21"),
    );
  const [dark, setDark] = useState(
    () => localStorage.getItem("oui-theme") === "dark",
  );
  const [collapsed, setCollapsed] = useState(false),
    [mobileMenu, setMobileMenu] = useState(false);
  const [drawer, setDrawer] = useState<UserRow | null>(null),
    [toast, setToast] = useState(""),
    [info, setInfo] = useState(false);
  const [dateOpen, setDateOpen] = useState(false),
    [exportOpen, setExportOpen] = useState(false),
    [exporting, setExporting] = useState(false);
  const [dateDraft, setDateDraft] = useState({
      start: filters.start,
      end: filters.end,
    }),
    [dateError, setDateError] = useState("");
  const [group, setGroup] = useState<"user" | "team" | "leader">("user"),
    [allRanks, setAllRanks] = useState(false),
    [search, setSearch] = useState(""),
    [pageIndex, setPageIndex] = useState(0),
    [sort, setSort] = useState<"desc" | "asc">("desc");
  const [busy, setBusy] = useState(false),
    [confirm, setConfirm] = useState<"quick" | "full" | null>(null),
    [jobs, setJobs] = useState<Operation[]>([]);
  const report = useRef<HTMLDivElement>(null),
    timer = useRef<ReturnType<typeof setInterval> | null>(null),
    dateRef = useRef<HTMLDivElement>(null),
    exportRef = useRef<HTMLDivElement>(null);
  const initialRange = useRef(
    !new URLSearchParams(location.search).has("start"),
  );
  const notify = (message: string) => setToast(message);
  async function refresh(signal?: AbortSignal) {
    setLoading(true);
    setError("");
    try {
      const s = await loadSnapshot(signal);
      if (signal?.aborted) return;
      setSnapshot(s);
      setJobs(s.operations);
      if (initialRange.current) {
        setFilters((f) => ({ ...f, ...defaults(s.coverageEnd) }));
        initialRange.current = false;
      }
    } catch (e) {
      if (!signal?.aborted)
        setError(
          e instanceof Error ? e.message : "데이터를 불러오지 못했습니다.",
        );
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    const c = new AbortController();
    void refresh(c.signal);
    return () => {
      c.abort();
      if (timer.current) clearInterval(timer.current);
    };
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    localStorage.setItem("oui-theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    const params = new URLSearchParams({ page, ...filters });
    history.replaceState(null, "", location.pathname + "?" + params.toString());
  }, [page, filters]);
  useEffect(() => {
    const pop = () => {
      setPage(initialPage());
      setFilters(initialFilters(snapshot?.coverageEnd || "2026-10-21"));
    };
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, [snapshot?.coverageEnd]);
  useEffect(() => {
    setPageIndex(0);
    setDrawer(null);
  }, [filters, group, search, sort, allRanks]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    function close(e: MouseEvent) {
      if (!dateRef.current?.contains(e.target as Node)) setDateOpen(false);
      if (!exportRef.current?.contains(e.target as Node)) setExportOpen(false);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const data = useMemo(
    () => (snapshot ? select(snapshot, filters) : null),
    [snapshot, filters],
  );
  const before = useMemo(
    () => (snapshot ? select(snapshot, previous(filters)) : null),
    [snapshot, filters],
  );
  const compareAvailable =
    !!snapshot &&
    previous(filters).start >= snapshot.coverageStart &&
    previous(filters).end <= snapshot.coverageEnd;
  const teams = useMemo(() => teamRows(data?.rows || []), [data]);
  const title = pages.find((p) => p.id === page)!;
  const allUsers = snapshot?.users || [];
  const divUsers = allUsers.filter(
    (u) => filters.division === ALL || u.division === filters.division,
  );
  const teamUsers = divUsers.filter(
    (u) => filters.team === ALL || u.team === filters.team,
  );
  const setFilter = (key: keyof Filters, value: string) => {
    setFilters((f) => ({
      ...f,
      [key]: value,
      ...(key === "division"
        ? { team: ALL, position: ALL }
        : key === "team"
          ? { position: ALL }
          : {}),
    }));
  };
  const navigate = (p: Page) => {
    setPage(p);
    setMobileMenu(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const activeFilters = (
    ["division", "team", "position", "mapping", "model", "category"] as const
  ).filter((k) => filters[k] !== ALL);
  const leaders = data?.rows.filter(isLeader) || [];
  const ranked = group === "leader" ? leaders : data?.rows || [];
  const metricKey = page === "tokens" ? "total" : "questions";
  const sorted = [...ranked].sort(
    (a, b) =>
      (sort === "desc"
        ? b[metricKey] - a[metricKey]
        : a[metricKey] - b[metricKey]) ||
      a.name.localeCompare(b.name, "ko") ||
      a.id.localeCompare(b.id),
  );
  const searched = sorted.filter((u) =>
    `${u.name} ${u.team} ${u.division}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const shownRanks = allRanks ? searched : searched.slice(0, 10);
  const viewRows = shownRanks.slice(pageIndex * 10, (pageIndex + 1) * 10);
  const pageCount = Math.max(1, Math.ceil(shownRanks.length / 10));
  const reset = () => {
    setFilters(defaults(snapshot?.coverageEnd || "2026-10-21"));
    setSearch("");
  };

  async function exportReport(kind: "csv" | "png" | "pdf") {
    setExportOpen(false);
    if (!data || !snapshot) return;
    if (kind === "csv") {
      const rows =
        group === "leader" && page === "users"
          ? data.rows.filter(isLeader)
          : data.rows;
      download(
        csvText(
          [
            "사용자 ID",
            "사용자명",
            "본부",
            "팀",
            "직급",
            "매핑 상태",
            "질문 수",
            "채팅 수",
            "요청 수",
            "입력 토큰",
            "출력 토큰",
            "비용(USD)",
          ],
          rows.map((r) => [
            r.id,
            r.name,
            r.division,
            r.team,
            r.position,
            r.mapping,
            r.questions,
            r.chats,
            r.requests,
            r.prompt,
            r.completion,
            r.spend.toFixed(6),
          ]),
        ),
        `openwebui-${page}-${filters.start}-${filters.end}.csv`,
      );
      notify(
        "선택 기간의 전체 사용자 데이터를 내보냈습니다. 0건 사용자도 포함됩니다.",
      );
      return;
    }
    if (kind === "pdf") {
      window.print();
      return;
    }
    if (!report.current) return;
    setExporting(true);
    try {
      await document.fonts.ready;
      // Embed one local font explicitly; avoid scanning every imported stylesheet/font
      // when exporting a long dashboard in a closed-network browser.
      const fontResponse = await fetch(exportFontUrl);
      if (!fontResponse.ok) throw new Error("Export font unavailable");
      const fontBlob = await fontResponse.blob();
      const fontData = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = reject;
        reader.readAsDataURL(fontBlob);
      });
      const url = await toPng(report.current, {
        fontEmbedCSS: `@font-face{font-family:'Noto Sans KR';font-weight:100 900;src:url(${fontData}) format('woff2');}`,
        backgroundColor: dark ? "#151827" : "#f6f7fb",
        pixelRatio: 2,
        filter: (node) =>
          !(node instanceof HTMLElement && node.dataset.exportHide === "true"),
      });
      const a = document.createElement("a");
      const pngBlob = await (await fetch(url)).blob();
      const downloadUrl = URL.createObjectURL(pngBlob);
      a.href = downloadUrl;
      a.download = `openwebui-${page}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
      notify("현재 화면을 PNG로 저장했습니다.");
    } catch (error) {
      console.error("PNG export failed", error);
      notify("이미지 내보내기에 실패했습니다. PDF 인쇄를 이용해주세요.");
    } finally {
      setExporting(false);
    }
  }
  async function execute(kind: "quick" | "full") {
    setConfirm(null);
    setBusy(true);
    if (!demo) {
      try {
        const op = await runUpdate(kind);
        setJobs((j) => [op, ...j]);
        notify(
          op.status === "success"
            ? "업데이트가 완료되었습니다."
            : op.status === "running"
              ? "업데이트 진행 중입니다. 운영 로그를 확인해주세요."
              : "일부 단계에 실패했습니다. 실행 기록을 확인해주세요.",
        );
        if (op.status === "success") await refresh();
      } catch (e) {
        notify(e instanceof Error ? e.message : "업데이트 요청 실패");
      } finally {
        setBusy(false);
      }
      return;
    }
    const op: Operation = {
      id: `demo-${Date.now()}`,
      kind: kind === "quick" ? "빠른 업데이트" : "전체 업데이트",
      status: "running",
      startedAt: new Date().toISOString(),
      steps: [
        {
          name: "OpenWebUI DB 스냅샷",
          status: "running",
          detail: "시뮬레이션 · 스냅샷 무결성 검사 중",
        },
        {
          name: "토큰 로그 동기화",
          status: "waiting",
          detail: "시뮬레이션 대기",
        },
        {
          name: "질문 카테고리 분류",
          status: "waiting",
          detail: "시뮬레이션 대기",
        },
      ],
    };
    setJobs((j) => [op, ...j]);
    let stage = 0;
    timer.current = setInterval(() => {
      stage++;
      setJobs((j) =>
        j.map((job) =>
          job.id !== op.id
            ? job
            : {
                ...job,
                status: stage >= 3 ? "success" : "running",
                steps: job.steps.map((s, i) => ({
                  ...s,
                  status:
                    i < stage ? "success" : i === stage ? "running" : "waiting",
                  detail:
                    i < stage
                      ? "시뮬레이션 완료 · 실제 서버 작업 없음"
                      : i === stage
                        ? "시뮬레이션 실행 중"
                        : "시뮬레이션 대기",
                })),
              },
        ),
      );
      if (stage >= 3) {
        clearInterval(timer.current!);
        timer.current = null;
        setBusy(false);
        notify(
          "업데이트 시뮬레이션이 완료되었습니다. 실제 데이터는 변경하지 않았습니다.",
        );
      }
    }, 1100);
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className={"app " + (collapsed ? "sidebar-collapsed" : "")}>
        {mobileMenu && (
          <button
            className="mobile-scrim"
            aria-label="메뉴 닫기"
            onClick={() => setMobileMenu(false)}
          />
        )}
        <aside className={"sidebar " + (mobileMenu ? "mobile-open" : "")}>
          <a
            href="?page=overview"
            className="brand"
            onClick={(e) => {
              e.preventDefault();
              navigate("overview");
            }}
          >
            <span className="brand-symbol">
              <Layers3 size={24} />
            </span>
            <span className="brand-copy">
              OpenWebUI<span>ANALYTICS WORKSPACE</span>
            </span>
          </a>
          <div className="workspace-label">
            <span className="workspace-dot" /> AI 활용 인사이트{" "}
            <span className="workspace-version">v2</span>
          </div>
          <div className="nav-label">WORKSPACE</div>
          <nav aria-label="주 메뉴">
            {pages.slice(0, 3).map((p) => (
              <button
                key={p.id}
                aria-current={p.id === page ? "page" : undefined}
                className={"nav-item " + (p.id === page ? "active" : "")}
                onClick={() => navigate(p.id)}
                title={p.name}
              >
                <p.icon size={19} />
                <span>{p.name}</span>
                {p.id === page && <span className="nav-active-dot" />}
              </button>
            ))}
          </nav>
          <div className="nav-label operations-label">MANAGEMENT</div>
          <nav aria-label="운영 메뉴">
            <button
              className={"nav-item " + (page === "operations" ? "active" : "")}
              onClick={() => navigate("operations")}
              title="운영 업데이트"
            >
              <RefreshCw size={18} />
              <span>운영 업데이트</span>
              {page === "operations" && <span className="nav-active-dot" />}
            </button>
            <button
              className="nav-item"
              onClick={() => setInfo(true)}
              title="지표 및 데이터 기준"
            >
              <CircleHelp size={18} />
              <span>지표 및 데이터 기준</span>
            </button>
          </nav>
          <div className="sidebar-bottom">
            <div className="source-health">
              <span className={"status-dot " + (error ? "warning" : "")} />
              <div>
                {demo ? "데모 워크스페이스" : "분석 데이터 연결"}
                <small>
                  {demo
                    ? "합성 데이터로 체험 중"
                    : error
                      ? "연결 확인 필요"
                      : "DB 스냅샷 기반"}
                </small>
              </div>
              <ShieldCheck size={17} />
            </div>
            <button className="profile" onClick={() => setInfo(true)}>
              <span className="avatar">O</span>
              <span>
                Analytics Admin<small>OpenWebUI Workspace</small>
              </span>
              <MoreHorizontal size={16} />
            </button>
          </div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <div className="breadcrumb">
              <IconButton
                label={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
                onClick={() => {
                  if (window.innerWidth < 900) setMobileMenu(!mobileMenu);
                  else setCollapsed(!collapsed);
                }}
              >
                {collapsed ? <Menu size={19} /> : <PanelLeftClose size={19} />}
              </IconButton>
              <span>Workspace</span>
              <ChevronRight size={13} />
              <strong>{title.en}</strong>
            </div>
            <div className="topbar-actions">
              <span className="env-badge">
                <span className="status-dot" />
                {demo ? "DEMO" : "LIVE API"}
              </span>
              <IconButton
                label={dark ? "라이트 모드로 전환" : "다크 모드로 전환"}
                onClick={() => setDark(!dark)}
              >
                {dark ? <Sun size={18} /> : <Moon size={18} />}
              </IconButton>
              <IconButton
                label="최근 업데이트 알림"
                onClick={() =>
                  notify(
                    snapshot
                      ? `${demo ? "데모 스냅샷" : "데이터"} 기준 시각: ${shortDate(snapshot.updatedAt)}`
                      : "데이터를 불러오는 중입니다.",
                  )
                }
              >
                <Bell size={18} />
              </IconButton>
              <span className="avatar avatar-small">O</span>
            </div>
          </header>
          <main ref={report} className="main">
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  <span /> OPENWEBUI INTELLIGENCE
                </div>
                <h1>
                  {title.name}
                  <span className="title-dot">.</span>
                </h1>
                <p>{title.description}</p>
              </div>
              <div className="page-actions" data-export-hide="true">
                {page !== "operations" && (
                  <div className="date-wrap" ref={dateRef}>
                    <button
                      className="button"
                      aria-expanded={dateOpen}
                      onClick={() => {
                        setDateOpen(!dateOpen);
                        setDateDraft({
                          start: filters.start,
                          end: filters.end,
                        });
                        setDateError("");
                      }}
                    >
                      <CalendarDays size={15} />
                      {filters.start.slice(5).replace("-", ".")} —{" "}
                      {filters.end.slice(5).replace("-", ".")}
                      <ChevronDown size={13} />
                    </button>
                    {dateOpen && (
                      <div className="date-popover">
                        <div className="date-presets">
                          {[7, 30, 90].map((n) => (
                            <button
                              key={n}
                              onClick={() => {
                                const end =
                                  snapshot?.coverageEnd || filters.end;
                                setFilters((f) => ({
                                  ...f,
                                  start: addDays(end, 1 - n),
                                  end,
                                }));
                                setDateOpen(false);
                              }}
                            >
                              최근 {n}일
                            </button>
                          ))}
                          <button
                            onClick={() => {
                              if (snapshot)
                                setFilters((f) => ({
                                  ...f,
                                  start: snapshot.coverageStart,
                                  end: snapshot.coverageEnd,
                                }));
                              setDateOpen(false);
                            }}
                          >
                            전체 기간
                          </button>
                        </div>
                        <label>
                          시작일
                          <input
                            type="date"
                            value={dateDraft.start}
                            max={dateDraft.end}
                            onChange={(e) =>
                              setDateDraft((d) => ({
                                ...d,
                                start: e.target.value,
                              }))
                            }
                          />
                        </label>
                        <label>
                          종료일
                          <input
                            type="date"
                            value={dateDraft.end}
                            min={dateDraft.start}
                            onChange={(e) =>
                              setDateDraft((d) => ({
                                ...d,
                                end: e.target.value,
                              }))
                            }
                          />
                        </label>
                        {dateError && (
                          <p role="alert" className="danger-text">
                            {dateError}
                          </p>
                        )}
                        <button
                          className="button primary"
                          onClick={() => {
                            if (
                              !validDate(dateDraft.start) ||
                              !validDate(dateDraft.end) ||
                              dateDraft.start > dateDraft.end ||
                              dateDraft.start < addDays(dateDraft.end, -730)
                            ) {
                              setDateError(
                                "올바른 날짜를 선택해주세요. 최대 731일입니다.",
                              );
                              return;
                            }
                            setFilters((f) => ({ ...f, ...dateDraft }));
                            setDateOpen(false);
                          }}
                        >
                          기간 적용
                        </button>
                      </div>
                    )}
                  </div>
                )}
                <IconButton
                  label="데이터 새로고침"
                  className={loading ? "spinning" : ""}
                  onClick={() => {
                    if (!loading && !busy) void refresh();
                  }}
                >
                  <RefreshCw size={17} />
                </IconButton>
                <div ref={exportRef} className="export-wrap">
                  <button
                    className="button primary"
                    disabled={!snapshot || exporting}
                    aria-expanded={exportOpen}
                    onClick={() => setExportOpen(!exportOpen)}
                  >
                    {exporting ? (
                      <Loader2 size={15} className="spinning" />
                    ) : (
                      <ArrowDownToLine size={15} />
                    )}
                    리포트 내보내기
                  </button>
                  {exportOpen && (
                    <div className="export-menu">
                      <button onClick={() => void exportReport("csv")}>
                        <FileText size={16} />
                        전체 사용자 CSV
                      </button>
                      <button onClick={() => void exportReport("png")}>
                        <LayoutDashboard size={16} />
                        현재 화면 PNG
                      </button>
                      <button onClick={() => void exportReport("pdf")}>
                        <FileText size={16} />
                        PDF 인쇄 / 저장
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
            {demo && (
              <div className="demo-banner">
                <Sparkles size={15} />
                <span>
                  데모 워크스페이스 <span className="demo-separator">·</span>{" "}
                  화면의 모든 사용자·조직·수치는 합성 데이터입니다.
                </span>
                <button onClick={() => setInfo(true)}>
                  데이터 기준
                  <ArrowRight size={12} />
                </button>
              </div>
            )}
            {page !== "operations" && snapshot && (
              <div className="filter-area" data-export-hide="true">
                <div className="filter-bar">
                  <span className="filter-icon">
                    <Settings2 size={17} />
                  </span>
                  <Select
                    label="본부"
                    value={filters.division}
                    values={options(allUsers.map((u) => u.division))}
                    onChange={(v) => setFilter("division", v)}
                  />
                  <Select
                    label="팀"
                    value={filters.team}
                    values={options(divUsers.map((u) => u.team))}
                    onChange={(v) => setFilter("team", v)}
                  />
                  <Select
                    label="직급"
                    value={filters.position}
                    values={options(teamUsers.map((u) => u.position))}
                    onChange={(v) => setFilter("position", v)}
                  />
                  {page === "tokens" ? (
                    <Select
                      label="모델"
                      value={filters.model}
                      values={options(snapshot.usage.map((e) => e.model))}
                      onChange={(v) => setFilter("model", v)}
                    />
                  ) : (
                    <Select
                      label="매핑 상태"
                      value={filters.mapping}
                      values={options(allUsers.map((u) => u.mapping))}
                      onChange={(v) => setFilter("mapping", v)}
                    />
                  )}
                  <button className="reset-button" onClick={reset}>
                    <RotateCcw size={14} />
                    <span>초기화</span>
                  </button>
                </div>
                {!!activeFilters.length && (
                  <div className="filter-chips">
                    {activeFilters.map((k) => (
                      <button key={k} onClick={() => setFilter(k, ALL)}>
                        {filters[k]}
                        <X size={12} />
                      </button>
                    ))}
                    <span>모든 지표에 동일 조건 적용</span>
                  </div>
                )}
              </div>
            )}
            {error ? (
              <div className="error-state" role="alert">
                <AlertTriangle size={28} />
                <h2>데이터를 불러올 수 없습니다</h2>
                <p>{error}</p>
                <button
                  className="button primary"
                  onClick={() => void refresh()}
                >
                  다시 시도
                </button>
              </div>
            ) : loading ? (
              <div
                className="skeleton-layout"
                aria-busy="true"
                aria-label="분석 데이터 로딩 중"
              >
                <div className="skeleton-metrics">
                  {[1, 2, 3, 4].map((i) => (
                    <div className="skeleton" key={i} />
                  ))}
                </div>
                <div className="skeleton skeleton-chart" />
                <div className="skeleton skeleton-chart" />
              </div>
            ) : (
              data &&
              snapshot && (
                <AnimatePresence mode="wait">
                  <motion.div
                    key={page}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -5 }}
                    transition={{ duration: 0.18 }}
                  >
                    {page === "overview" && (
                      <>
                        <div className="section-kicker">
                          <span>PERFORMANCE AT A GLANCE</span>
                          <span>
                            <Clock3 size={12} />
                            {shortDate(snapshot.updatedAt)} 기준
                          </span>
                        </div>
                        <div className="metrics-grid">
                          <Metric
                            label="활성 사용자"
                            value={data.active}
                            prior={before?.active}
                            comparisonAvailable={compareAvailable}
                            note={`전체 ${number(data.users.length)}명 중 · 기간 내 질문 사용자`}
                            icon={<Users size={18} />}
                            accent
                          />
                          <Metric
                            label="전체 질문"
                            value={data.total.questions}
                            prior={before?.total.questions}
                            comparisonAvailable={compareAvailable}
                            note="사용자 메시지 기준 · 이전 동일 기간 대비"
                            icon={<FileText size={18} />}
                          />
                          <Metric
                            label="사용 토큰"
                            value={data.total.tokens}
                            prior={before?.total.tokens}
                            comparisonAvailable={compareAvailable}
                            note="입력 + 출력 · LiteLLM 로그 기준"
                            icon={<Layers3 size={18} />}
                          />
                          <Metric
                            label="추정 비용"
                            value={data.total.spend}
                            prior={before?.total.spend}
                            comparisonAvailable={compareAvailable}
                            note="LiteLLM spend 기준 · USD"
                            icon={<Wallet size={18} />}
                            format={dollars}
                          />
                        </div>
                        <div className="insight-strip">
                          <span className="insight-icon">
                            <TrendingUp size={17} />
                          </span>
                          <span>
                            AI 활용률{" "}
                            <strong>
                              {data.users.length
                                ? (
                                    (data.active / data.users.length) *
                                    100
                                  ).toFixed(1)
                                : "0"}
                              %
                            </strong>
                          </span>
                          <span className="strip-divider" />
                          <span>
                            활성 팀 <strong>{data.activeTeams}개</strong>
                          </span>
                          <span className="strip-divider" />
                          <span>
                            사용량 0인 사용자 <strong>{data.zero}명</strong>
                          </span>
                          <button
                            onClick={() => {
                              setAllRanks(true);
                              navigate("users");
                            }}
                          >
                            전체 사용자 살펴보기
                            <ArrowRight size={14} />
                          </button>
                        </div>
                        <div className="chart-grid">
                          <Panel
                            title="질문 사용 추이"
                            subtitle="일별 사용자 질문 · 그래프를 드래그하거나 하단 슬라이더로 확대"
                            action={<span className="legend-dot">질문 수</span>}
                          >
                            {data.total.questions ? (
                              <Chart
                                dark={dark}
                                option={lineOption(
                                  trend(data.usage, filters, "questions"),
                                  dark,
                                )}
                                label="일별 질문 수 추이. 드래그와 휠로 확대할 수 있습니다."
                                height={294}
                              />
                            ) : (
                              <Empty />
                            )}
                          </Panel>
                          <Panel
                            title="질문 카테고리"
                            subtitle="질문이 어떤 업무에 활용되고 있나요?"
                            action={<span className="pill">분포</span>}
                          >
                            <CategoryChart
                              snapshot={snapshot}
                              filters={filters}
                              dark={dark}
                              onPick={(v) => setFilter("category", v)}
                            />
                          </Panel>
                        </div>
                        <div className="bottom-grid">
                          <Panel
                            title="조직별 활용 현황"
                            subtitle="전체 DB 사용자를 기준으로, 사용량 0인 팀도 포함"
                            action={
                              <button
                                className="text-button"
                                onClick={() => {
                                  setGroup("team");
                                  navigate("users");
                                }}
                              >
                                자세히 보기
                                <ArrowRight size={13} />
                              </button>
                            }
                          >
                            {teams.length ? (
                              <Chart
                                dark={dark}
                                height={252}
                                label="팀별 질문 수. 막대를 클릭하면 해당 팀으로 필터링합니다."
                                option={barOption(
                                  teams
                                    .slice(0, 6)
                                    .map((t) => ({
                                      name: t.name,
                                      value: t.questions,
                                    })),
                                  dark,
                                )}
                                onClick={(name) => {
                                  const t = teams.find((t) => t.name === name);
                                  if (t) {
                                    setFilters((f) => ({
                                      ...f,
                                      division: t.division,
                                      team: name,
                                      position: ALL,
                                    }));
                                    navigate("users");
                                  }
                                }}
                              />
                            ) : (
                              <Empty />
                            )}
                            <div className="chart-accessible-links">
                              {teams.map((t) => (
                                <button
                                  key={t.id}
                                  onClick={() => {
                                    setFilters((f) => ({
                                      ...f,
                                      division: t.division,
                                      team: t.name,
                                      position: ALL,
                                    }));
                                    navigate("users");
                                  }}
                                >
                                  {t.name}
                                </button>
                              ))}
                            </div>
                          </Panel>
                          <Panel
                            title="팀장 활용 순위"
                            subtitle="상위 5명 미리보기 · 0건 팀장은 전체 순위에서 확인"
                            action={
                              <button
                                className="text-button"
                                onClick={() => {
                                  setGroup("leader");
                                  setAllRanks(true);
                                  navigate("users");
                                }}
                              >
                                전체 {leaders.length}명<ArrowRight size={13} />
                              </button>
                            }
                          >
                            <div className="mini-ranking">
                              {leaders.slice(0, 5).map((r, i) => (
                                <button key={r.id} onClick={() => setDrawer(r)}>
                                  <span className={"rank-number rank-" + i}>
                                    {String(i + 1).padStart(2, "0")}
                                  </span>
                                  <span className="user-avatar">
                                    {r.name.slice(-2)}
                                  </span>
                                  <span className="mini-person">
                                    {r.name}
                                    <small>{r.team}</small>
                                  </span>
                                  <span className="mini-bar">
                                    <span
                                      style={{
                                        width: `${Math.max(0, (r.questions / (leaders[0]?.questions || 1)) * 100)}%`,
                                      }}
                                    />
                                  </span>
                                  <strong>
                                    {number(r.questions)}
                                    <small>건</small>
                                  </strong>
                                </button>
                              ))}
                            </div>
                            {!leaders.length && (
                              <Empty title="선택한 조건에 팀장이 없습니다" />
                            )}
                            <button
                              className="ranking-footer"
                              onClick={() => {
                                setGroup("leader");
                                setAllRanks(false);
                                navigate("users");
                              }}
                            >
                              Top 10 자세히 보기
                              <ArrowRight size={13} />
                            </button>
                          </Panel>
                        </div>
                      </>
                    )}
                    {page === "tokens" && (
                      <>
                        <div className="section-kicker">
                          <span>TOKEN INTELLIGENCE</span>
                          <span>
                            <Clock3 size={12} />
                            {shortDate(snapshot.updatedAt)} 기준
                          </span>
                        </div>
                        <div className="metrics-grid">
                          <Metric
                            label="전체 토큰"
                            value={data.total.tokens}
                            prior={before?.total.tokens}
                            comparisonAvailable={compareAvailable}
                            note="입력 + 출력 토큰"
                            icon={<Layers3 size={18} />}
                            accent
                          />
                          <Metric
                            label="입력 토큰"
                            value={data.total.prompt}
                            note="프롬프트 및 컨텍스트"
                            icon={<ArrowRight size={18} />}
                          />
                          <Metric
                            label="출력 토큰"
                            value={data.total.completion}
                            note="모델이 생성한 응답"
                            icon={<FileText size={18} />}
                          />
                          <Metric
                            label="추정 비용"
                            value={data.total.spend}
                            note="LiteLLM spend 기준 · USD"
                            format={dollars}
                            icon={<Wallet size={18} />}
                          />
                        </div>
                        <div className="insight-strip">
                          <span className="insight-icon">
                            <Zap size={16} />
                          </span>
                          <span>
                            API 요청{" "}
                            <strong>{number(data.total.requests)}건</strong>
                          </span>
                          <span className="strip-divider" />
                          <span>
                            식별 사용자 <strong>{data.tokenUsers}명</strong>
                          </span>
                          <span className="strip-divider" />
                          <span>
                            미식별 요청{" "}
                            <strong>{number(data.unmappedRequests)}건</strong>
                          </span>
                          <button onClick={() => setInfo(true)}>
                            집계 기준
                            <CircleHelp size={14} />
                          </button>
                        </div>
                        <div className="chart-grid">
                          <Panel
                            title="토큰 사용 추이"
                            subtitle="일별 전체 토큰 · 입력과 출력 합계"
                            action={
                              <span className="legend-dot">전체 토큰</span>
                            }
                          >
                            {data.total.tokens ? (
                              <Chart
                                dark={dark}
                                height={294}
                                option={lineOption(
                                  trend(data.usage, filters, "tokens"),
                                  dark,
                                  true,
                                )}
                                label="일별 전체 토큰 사용 추이"
                              />
                            ) : (
                              <Empty />
                            )}
                          </Panel>
                          <Panel
                            title="모델별 토큰 비중"
                            subtitle="모델을 선택하면 전체 화면에 적용됩니다"
                          >
                            <ModelChart
                              data={data.usage}
                              dark={dark}
                              onPick={(v) => setFilter("model", v)}
                            />
                          </Panel>
                        </div>
                      </>
                    )}
                    {(page === "users" || page === "tokens") && (
                      <>
                        {page === "users" && (
                          <>
                            <div className="section-kicker">
                              <span>PEOPLE & ADOPTION</span>
                              <span>
                                <ShieldCheck size={12} />
                                OpenWebUI DB 사용자 기준
                              </span>
                            </div>
                            <div className="metrics-grid">
                              <Metric
                                label="전체 사용자"
                                value={data.users.length}
                                note="활동 여부와 관계없이 DB 사용자 전체"
                                icon={<Users size={18} />}
                                accent
                              />
                              <Metric
                                label="활성 사용자"
                                value={data.active}
                                prior={before?.active}
                                comparisonAvailable={compareAvailable}
                                note="선택 기간 내 질문 1건 이상"
                                icon={<Activity size={18} />}
                              />
                              <Metric
                                label="전체 질문"
                                value={data.total.questions}
                                note="사용자 메시지 기준"
                                icon={<FileText size={18} />}
                              />
                              <Metric
                                label="사용량 0인 사용자"
                                value={data.zero}
                                note="전체 목록과 순위에 포함"
                                icon={<Users size={18} />}
                              />
                            </div>
                            <div className="adoption-card">
                              <div>
                                <span className="eyebrow">TEAM ADOPTION</span>
                                <h2>조직의 활용 흐름</h2>
                                <p>
                                  팀원을 기준으로 활성 사용자 비율을 비교합니다.
                                </p>
                              </div>
                              <div className="adoption-teams">
                                {teams.map((t) => (
                                  <button
                                    key={t.id}
                                    onClick={() =>
                                      setFilters((f) => ({
                                        ...f,
                                        division: t.division,
                                        team: t.name,
                                        position: ALL,
                                      }))
                                    }
                                  >
                                    <div>
                                      <span>{t.name}</span>
                                      <strong>
                                        {t.users
                                          ? Math.round(
                                              (t.active / t.users) * 100,
                                            )
                                          : 0}
                                        %
                                      </strong>
                                    </div>
                                    <div className="progress-track">
                                      <span
                                        style={{
                                          width: `${t.users ? (t.active / t.users) * 100 : 0}%`,
                                        }}
                                      />
                                    </div>
                                    <small>
                                      {t.active} / {t.users}명 활성
                                    </small>
                                  </button>
                                ))}
                                {!teams.length && (
                                  <p className="muted">
                                    선택 조건에 해당하는 팀이 없습니다.
                                  </p>
                                )}
                              </div>
                            </div>
                          </>
                        )}
                        <Panel
                          title={
                            page === "tokens"
                              ? "사용자별 토큰 사용량"
                              : group === "leader"
                                ? "팀장 활용 순위"
                                : group === "team"
                                  ? "팀별 활용 현황"
                                  : "전체 사용자 현황"
                          }
                          subtitle="0건 사용자도 표시합니다. 조직 CSV에만 존재하는 사람은 포함하지 않습니다."
                          className="detail-panel"
                          action={
                            <button
                              className="button small"
                              onClick={() => void exportReport("csv")}
                            >
                              <ArrowDownToLine size={14} />
                              CSV 다운로드
                            </button>
                          }
                        >
                          <div className="table-toolbar">
                            <div
                              className="tabs"
                              role="group"
                              aria-label="사용량 보기 방식"
                            >
                              {(["user", "team", "leader"] as const).map(
                                (g) => (
                                  <button
                                    key={g}
                                    className={group === g ? "active" : ""}
                                    aria-pressed={group === g}
                                    onClick={() => setGroup(g)}
                                  >
                                    {g === "user"
                                      ? "사용자"
                                      : g === "team"
                                        ? "팀"
                                        : "팀장"}
                                  </button>
                                ),
                              )}
                            </div>
                            <div className="table-controls">
                              {group !== "team" && (
                                <>
                                  <label className="table-search">
                                    <Search size={14} />
                                    <input
                                      aria-label="사용자 또는 팀 검색"
                                      placeholder="이름 또는 팀 검색"
                                      value={search}
                                      onChange={(e) =>
                                        setSearch(e.target.value)
                                      }
                                    />
                                  </label>
                                  <div className="segmented">
                                    <button
                                      className={!allRanks ? "active" : ""}
                                      onClick={() => setAllRanks(false)}
                                    >
                                      Top 10
                                    </button>
                                    <button
                                      className={allRanks ? "active" : ""}
                                      onClick={() => setAllRanks(true)}
                                    >
                                      전체 {ranked.length}명
                                    </button>
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                          {group === "team" ? (
                            <div className="table-scroll">
                              <table>
                                <thead>
                                  <tr>
                                    <th>팀</th>
                                    <th>본부</th>
                                    <th className="numeric">DB 사용자</th>
                                    <th className="numeric">활성 사용자</th>
                                    <th className="numeric">질문 수</th>
                                    <th className="numeric">토큰</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {teams.map((t) => (
                                    <tr key={t.id}>
                                      <td>
                                        <button
                                          className="person-button"
                                          onClick={() =>
                                            setFilters((f) => ({
                                              ...f,
                                              division: t.division,
                                              team: t.name,
                                              position: ALL,
                                            }))
                                          }
                                        >
                                          {t.name}
                                          <ArrowRight size={13} />
                                        </button>
                                      </td>
                                      <td>{t.division}</td>
                                      <td className="numeric">
                                        {number(t.users)}명
                                      </td>
                                      <td className="numeric">
                                        {number(t.active)}명
                                      </td>
                                      <td className="numeric">
                                        {number(t.questions)}
                                      </td>
                                      <td className="numeric">
                                        {number(t.total)}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                              {!teams.length && <Empty />}
                            </div>
                          ) : (
                            <>
                              <div className="table-scroll">
                                <table>
                                  <thead>
                                    <tr>
                                      <th className="rank-col">순위</th>
                                      <th>사용자</th>
                                      <th>소속</th>
                                      <th>직급</th>
                                      <th>활동 상태</th>
                                      <th className="numeric">
                                        <button
                                          className="sort-button"
                                          onClick={() =>
                                            setSort((s) =>
                                              s === "desc" ? "asc" : "desc",
                                            )
                                          }
                                        >
                                          {page === "tokens"
                                            ? "전체 토큰"
                                            : "질문 수"}
                                          {sort === "desc" ? " ↓" : " ↑"}
                                        </button>
                                      </th>
                                      <th className="numeric">
                                        {page === "tokens"
                                          ? "추정 비용"
                                          : "채팅 수"}
                                      </th>
                                      <th />
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {viewRows.map((r) => (
                                      <tr key={r.id}>
                                        <td className="rank-col">
                                          {sorted.findIndex(
                                            (u) => u.id === r.id,
                                          ) + 1}
                                        </td>
                                        <td>
                                          <button
                                            className="person-button"
                                            onClick={() => setDrawer(r)}
                                          >
                                            <span className="user-avatar">
                                              {r.name.slice(-2)}
                                            </span>
                                            <span>
                                              {r.name}
                                              <small>{r.id}</small>
                                            </span>
                                          </button>
                                        </td>
                                        <td>
                                          <span className="table-team">
                                            {r.team}
                                            <small>{r.division}</small>
                                          </span>
                                        </td>
                                        <td>{r.position}</td>
                                        <td>
                                          <span
                                            className={
                                              "activity-pill " +
                                              (r[metricKey] === 0
                                                ? "inactive"
                                                : "")
                                            }
                                          >
                                            <span />
                                            {r[metricKey] === 0
                                              ? "사용량 0"
                                              : "활성"}
                                          </span>
                                        </td>
                                        <td
                                          className={
                                            "numeric strong " +
                                            (r[metricKey] === 0 ? "muted" : "")
                                          }
                                        >
                                          {number(r[metricKey])}
                                        </td>
                                        <td className="numeric muted">
                                          {page === "tokens"
                                            ? dollars(r.spend)
                                            : number(r.chats)}
                                        </td>
                                        <td>
                                          <IconButton
                                            label={`${r.name} 상세 보기`}
                                            onClick={() => setDrawer(r)}
                                          >
                                            <ChevronRight size={15} />
                                          </IconButton>
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                                {!viewRows.length && (
                                  <Empty title="조건에 맞는 사용자가 없습니다" />
                                )}
                              </div>
                              <div className="table-footer">
                                <span>
                                  {shownRanks.length}명 중{" "}
                                  {shownRanks.length ? pageIndex * 10 + 1 : 0}–
                                  {Math.min(
                                    (pageIndex + 1) * 10,
                                    shownRanks.length,
                                  )}
                                  명 표시{" "}
                                  <span className="zero-note">· 0건 포함</span>
                                </span>
                                <div className="pagination">
                                  <button
                                    disabled={pageIndex === 0}
                                    aria-label="이전 페이지"
                                    onClick={() => setPageIndex((p) => p - 1)}
                                  >
                                    <ChevronLeft size={16} />
                                  </button>
                                  <span>
                                    {pageIndex + 1} / {pageCount}
                                  </span>
                                  <button
                                    disabled={pageIndex + 1 >= pageCount}
                                    aria-label="다음 페이지"
                                    onClick={() => setPageIndex((p) => p + 1)}
                                  >
                                    <ChevronRight size={16} />
                                  </button>
                                </div>
                              </div>
                            </>
                          )}
                        </Panel>
                      </>
                    )}
                    {page === "operations" && (
                      <>
                        <div className="section-kicker">
                          <span>DATA PIPELINE</span>
                          <span>
                            <span className="status-dot" />
                            {demo ? "시뮬레이션 환경" : "분석 파이프라인"}
                          </span>
                        </div>
                        <div className="ops-metrics">
                          <Panel
                            title="분석 DB 스냅샷"
                            action={<Database size={18} />}
                          >
                            <div className="ops-value">
                              <span className="status-dot" />
                              마지막 반영 완료
                            </div>
                            <p className="muted">
                              {shortDate(snapshot.updatedAt)} · DB 사용자{" "}
                              {snapshot.users.length}명
                            </p>
                          </Panel>
                          <Panel
                            title="토큰 캐시 로그"
                            action={<Layers3 size={18} />}
                          >
                            <div className="ops-number">
                              {number(snapshot.cache.logs)}
                              <span>건</span>
                            </div>
                            <p className="muted">
                              LiteLLM 요청 ID 기준 중복 제거
                            </p>
                          </Panel>
                          <Panel
                            title="질문 분류 결과"
                            action={<Sparkles size={18} />}
                          >
                            <div className="ops-number">
                              {number(snapshot.cache.classified)}
                              <span>건</span>
                            </div>
                            <p className="muted">
                              미분류 대기{" "}
                              <strong>
                                {number(snapshot.cache.pending)}건
                              </strong>
                            </p>
                          </Panel>
                        </div>
                        <div className="update-grid">
                          <div className="update-card">
                            <span className="update-icon">
                              <Zap size={23} />
                            </span>
                            <span className="pill">일상 운영</span>
                            <h2>빠른 업데이트</h2>
                            <p>
                              새 DB 스냅샷과 최근 토큰 로그를 반영하고
                              <br />
                              새로운 질문을 분류합니다.
                            </p>
                            <div className="update-flow">
                              <span>DB 스냅샷</span>
                              <ChevronRight size={12} />
                              <span>토큰 동기화</span>
                              <ChevronRight size={12} />
                              <span>최근 질문 분류</span>
                            </div>
                            <button
                              className="button primary"
                              disabled={busy}
                              onClick={() => setConfirm("quick")}
                            >
                              {busy ? (
                                <Loader2 className="spinning" size={16} />
                              ) : (
                                <RefreshCw size={16} />
                              )}{" "}
                              {demo
                                ? "빠른 업데이트 시뮬레이션"
                                : "빠른 업데이트 실행"}
                            </button>
                          </div>
                          <div className="update-card">
                            <span className="update-icon amber">
                              <Database size={23} />
                            </span>
                            <span className="pill amber">전체 처리</span>
                            <h2>전체 업데이트</h2>
                            <p>
                              스냅샷 반영 후 남아 있는 모든 질문을
                              <br />
                              배치 단위로 순차 분류합니다.
                            </p>
                            <div className="update-flow">
                              <span>DB 스냅샷</span>
                              <ChevronRight size={12} />
                              <span>토큰 동기화</span>
                              <ChevronRight size={12} />
                              <span>전체 미분류 처리</span>
                            </div>
                            <button
                              className="button"
                              disabled={busy}
                              onClick={() => setConfirm("full")}
                            >
                              <Database size={16} />
                              {demo
                                ? "전체 업데이트 시뮬레이션"
                                : "전체 업데이트 실행"}
                            </button>
                          </div>
                        </div>
                        <Panel
                          title="업데이트 실행 기록"
                          subtitle={
                            demo
                              ? "시뮬레이션 결과는 현재 브라우저 세션에만 유지됩니다."
                              : "최근 실행 작업의 단계별 상태를 확인합니다."
                          }
                          action={<span className="pill">{jobs.length}회</span>}
                        >
                          <div className="job-list">
                            {jobs.map((job, index) => (
                              <div className="job" key={job.id}>
                                <div className="job-heading">
                                  <div>
                                    <span className="job-icon">
                                      <Terminal size={17} />
                                    </span>
                                    <strong>{job.kind}</strong>
                                    <span className="muted">
                                      {shortDate(job.startedAt)}
                                    </span>
                                    {index === 0 && (
                                      <span className="latest-label">
                                        최근 실행
                                      </span>
                                    )}
                                  </div>
                                  <span
                                    className={
                                      "activity-pill " +
                                      (job.status === "failed"
                                        ? "failed"
                                        : job.status === "running"
                                          ? "running"
                                          : "")
                                    }
                                  >
                                    {job.status === "running" ? (
                                      <Loader2 size={12} className="spinning" />
                                    ) : job.status === "failed" ? (
                                      <AlertTriangle size={12} />
                                    ) : (
                                      <Check size={12} />
                                    )}{" "}
                                    {job.status === "success"
                                      ? "완료"
                                      : job.status === "running"
                                        ? "진행 중"
                                        : "실패"}
                                  </span>
                                </div>
                                <div className="steps">
                                  {job.steps.map((s, i) => (
                                    <div
                                      className={"step " + s.status}
                                      key={s.name}
                                    >
                                      <div className="step-icon">
                                        {s.status === "success" ? (
                                          <Check size={13} />
                                        ) : s.status === "running" ? (
                                          <Loader2
                                            size={13}
                                            className="spinning"
                                          />
                                        ) : s.status === "failed" ? (
                                          <X size={13} />
                                        ) : (
                                          i + 1
                                        )}
                                      </div>
                                      <div>
                                        <strong>{s.name}</strong>
                                        <p>{s.detail}</p>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        </Panel>
                      </>
                    )}
                  </motion.div>
                </AnimatePresence>
              )
            )}
            <footer className="page-footer">
              <span>
                <span className="status-dot" />
                {demo ? "SYNTHETIC DEMO DATA" : "OPENWEBUI SNAPSHOT"}
                {snapshot && ` · ${shortDate(snapshot.updatedAt)}`}
              </span>
              <span>
                {page !== "operations"
                  ? `${filters.start} — ${filters.end} · Asia/Seoul`
                  : "Operations workspace"}
                <span className="footer-brand">OpenWebUI Analytics</span>
              </span>
            </footer>
          </main>
        </div>
        <AnimatePresence>
          {toast && (
            <motion.div
              className="toast"
              role="status"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
            >
              <CheckCircle2 size={18} />
              <span>{toast}</span>
              <IconButton label="알림 닫기" onClick={() => setToast("")}>
                <X size={14} />
              </IconButton>
            </motion.div>
          )}
        </AnimatePresence>
        {drawer && (
          <Modal drawer title="사용자 상세" onClose={() => setDrawer(null)}>
            <div className="person-detail">
              <span className="detail-avatar">{drawer.name.slice(-2)}</span>
              <h3>{drawer.name}</h3>
              <p>
                {drawer.division} · {drawer.team} · {drawer.position}
              </p>
              <span
                className={
                  "activity-pill " + (!drawer.questions ? "inactive" : "")
                }
              >
                {drawer.questions ? "활성 사용자" : "사용량 0 · DB 등록 사용자"}
              </span>
            </div>
            <div className="detail-metrics">
              <div>
                <span>질문 수</span>
                <strong>{number(drawer.questions)}</strong>
              </div>
              <div>
                <span>채팅 수</span>
                <strong>{number(drawer.chats)}</strong>
              </div>
              <div>
                <span>전체 토큰</span>
                <strong>{compact(drawer.total)}</strong>
              </div>
              <div>
                <span>추정 비용</span>
                <strong>{dollars(drawer.spend)}</strong>
              </div>
            </div>
            <dl className="detail-meta">
              <dt>사용자 ID</dt>
              <dd>{drawer.id}</dd>
              <dt>조직 매핑</dt>
              <dd>{drawer.mapping}</dd>
              <dt>조회 기간</dt>
              <dd>
                {filters.start} ~ {filters.end}
              </dd>
              <dt>사용자 원천</dt>
              <dd>OpenWebUI DB</dd>
            </dl>
            <p className="detail-note">
              활동 기록이 없어도 DB 사용자 명부에 존재하면 순위와 목록에
              포함됩니다.
            </p>
          </Modal>
        )}
        {confirm && (
          <Modal
            title={
              confirm === "full" ? "전체 업데이트 실행" : "빠른 업데이트 실행"
            }
            onClose={() => setConfirm(null)}
          >
            <p className="confirm-copy">
              {demo
                ? "실제 서버에 요청하지 않고 단계별 진행 화면을 시뮬레이션합니다."
                : confirm === "full"
                  ? "전체 미분류 질문을 처리합니다. 처리량에 따라 시간이 소요될 수 있습니다."
                  : "최신 DB 스냅샷, 토큰 로그, 신규 질문 분류를 순서대로 실행합니다."}
            </p>
            <div className="modal-actions">
              <button className="button" onClick={() => setConfirm(null)}>
                취소
              </button>
              <button
                className="button primary"
                onClick={() => void execute(confirm)}
              >
                실행
              </button>
            </div>
          </Modal>
        )}
        {info && (
          <Modal title="지표 및 데이터 기준" onClose={() => setInfo(false)}>
            <div className="definitions">
              <p>
                <strong>사용자 기준</strong>OpenWebUI DB가 사용자 명부의
                기준입니다. CSV는 조직 정보만 보강하며 CSV에만 있는 사람은
                포함하지 않습니다.
              </p>
              <p>
                <strong>0건 사용자와 팀장</strong>조회 기간에 사용 기록이 없는
                DB 사용자도 전체 목록과 전체 순위에 포함합니다. Top 10은 사용량
                내림차순으로 최대 10명이며, 0건 팀장은 전체 순위에서 확인할 수
                있습니다.
              </p>
              <p>
                <strong>질문·활성 사용자</strong>질문은 role=user 메시지, 활성
                사용자는 기간 내 질문 1건 이상인 사용자입니다. 활성 팀은 활성
                사용자가 있는 팀입니다.
              </p>
              <p>
                <strong>채팅·첨부 집계</strong>이 데모의 채팅·첨부 수는 일별
                합성 집계입니다. 실제 API 연결 시 고유 채팅방·첨부 질문 기준의
                중복 없는 집계로 변환해야 합니다.
              </p>
              <p>
                <strong>토큰·비용</strong>LiteLLM 입력+출력 토큰 및 spend(USD)
                기준입니다. 미식별 요청은 전체 토큰에 포함되며 조직 필터 선택 시
                제외됩니다.
              </p>
              <p>
                <strong>비교 기간</strong>직전 동일 일수와 비교합니다. 비교
                기간이 데이터 수집 범위 밖이면 증감률을 표시하지 않습니다.
              </p>
              <p>
                <strong>데이터 상태</strong>
                {demo
                  ? "현재 합성 데이터 모드입니다. 실제 운영 데이터 연결은 v2 API 어댑터 검증이 필요합니다."
                  : "API 모드입니다. 반환된 DB 명부와 집계 데이터로 표시합니다."}
              </p>
            </div>
          </Modal>
        )}
      </div>
    </MotionConfig>
  );
}
function CategoryChart({
  snapshot,
  filters,
  dark,
  onPick,
}: {
  snapshot: Snapshot;
  filters: Filters;
  dark: boolean;
  onPick: (v: string) => void;
}) {
  const d = breakdown(
    select(snapshot, filters).usage,
    "category",
    "questions",
  ).filter((x) => x.value > 0);
  const sum = d.reduce((s, r) => s + r.value, 0);
  if (!sum) return <Empty />;
  return (
    <div className="category-content">
      <div className="donut-wrap">
        <Chart
          dark={dark}
          height={180}
          label="질문 카테고리 비율. 아래 범례 버튼으로 필터링할 수 있습니다."
          onClick={onPick}
          option={{
            color: palette,
            tooltip: { trigger: "item" },
            series: [
              {
                type: "pie",
                radius: ["68%", "87%"],
                center: ["50%", "50%"],
                padAngle: 3,
                itemStyle: { borderRadius: 4 },
                label: { show: false },
                emphasis: { scaleSize: 4 },
                data: d,
              },
            ],
            graphic: [
              {
                type: "text",
                left: "center",
                top: "38%",
                style: {
                  text: compact(sum),
                  font: "600 25px sans-serif",
                  fill: dark ? "#f4f4fb" : "#30344b",
                },
              },
              {
                type: "text",
                left: "center",
                top: "57%",
                style: {
                  text: "전체 질문",
                  font: "11px sans-serif",
                  fill: "#989db0",
                },
              },
            ],
          }}
        />
      </div>
      <div className="category-legend">
        {d.map((r, i) => (
          <button key={r.name} onClick={() => onPick(r.name)}>
            <span style={{ background: palette[i % palette.length] }} />
            <span>{r.name}</span>
            <strong>{((r.value / sum) * 100).toFixed(1)}%</strong>
          </button>
        ))}
      </div>
    </div>
  );
}
function ModelChart({
  data,
  dark,
  onPick,
}: {
  data: Snapshot["usage"];
  dark: boolean;
  onPick: (v: string) => void;
}) {
  const d = breakdown(data, "model", "tokens"),
    sum = d.reduce((s, r) => s + r.value, 0);
  return sum ? (
    <div className="model-list">
      {d.map((r, i) => (
        <button key={r.name} onClick={() => onPick(r.name)}>
          <span
            className="model-icon"
            style={{ background: palette[i] + "18", color: palette[i] }}
          >
            <Layers3 size={18} />
          </span>
          <span className="model-body">
            <span>
              <strong>{r.name}</strong>
              <b>{compact(r.value)}</b>
            </span>
            <span className="progress-track">
              <span
                style={{
                  width: `${(r.value / sum) * 100}%`,
                  background: palette[i],
                }}
              />
            </span>
            <small>
              {((r.value / sum) * 100).toFixed(1)}% · 전체 토큰 대비
            </small>
          </span>
          <ChevronRight size={14} />
        </button>
      ))}
    </div>
  ) : (
    <Empty />
  );
}
