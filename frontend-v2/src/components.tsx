import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { animate, motion, useReducedMotion } from "motion/react";
import * as echarts from "echarts/core";
import { LineChart, BarChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  AriaComponent,
  GraphicComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import {
  ChevronDown,
  Search,
  Check,
  ArrowUpRight,
  ArrowDownRight,
  Minus,
  X,
} from "lucide-react";
import { number, compact } from "./domain";
echarts.use([
  LineChart,
  BarChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  AriaComponent,
  GraphicComponent,
  SVGRenderer,
]);
export const palette = [
  "#6864e8",
  "#46b6c3",
  "#9a8aeb",
  "#f4b860",
  "#718aaf",
  "#c99cc9",
  "#c9cbd8",
];
export function IconButton({
  children,
  label,
  onClick,
  className = "",
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      className={"icon-button " + className}
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
export function Select({
  label,
  value,
  values,
  onChange,
}: {
  label: string;
  value: string;
  values: string[];
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false),
    [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null),
    input = useRef<HTMLInputElement>(null),
    id = useId();
  const [active, setActive] = useState(0);
  const filtered = values.filter((v) =>
    v.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  useEffect(() => {
    if (open) {
      setSearch("");
      setActive(0);
      input.current?.focus();
    }
  }, [open]);
  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    ref.current?.querySelector("button")?.focus();
  };
  return (
    <div
      className="select-wrap"
      ref={ref}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          setOpen(false);
          ref.current?.querySelector("button")?.focus();
        }
      }}
    >
      <button
        className={"select-trigger " + (value !== "전체" ? "selected" : "")}
        aria-expanded={open}
        aria-controls={id}
        aria-haspopup="listbox"
        onClick={() => setOpen(!open)}
      >
        <span className="filter-label">{label}</span>
        <span className="select-value">{value}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="select-popover">
          <div className="select-search">
            <Search size={15} />
            <input
              ref={input}
              value={search}
              placeholder={`${label} 검색`}
              aria-label={`${label} 검색`}
              role="combobox"
              aria-expanded="true"
              aria-controls={id}
              aria-activedescendant={
                filtered.length ? `${id}-${active}` : undefined
              }
              onChange={(e) => {
                setSearch(e.target.value);
                setActive(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActive((v) => Math.min(v + 1, filtered.length - 1));
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActive((v) => Math.max(0, v - 1));
                }
                if (e.key === "Enter" && filtered[active])
                  pick(filtered[active]);
              }}
            />
          </div>
          <div
            id={id}
            role="listbox"
            aria-label={label}
            className="select-list"
          >
            {filtered.map((v, index) => (
              <button
                key={v}
                id={`${id}-${index}`}
                role="option"
                aria-selected={v === value}
                className={index === active ? "highlight" : ""}
                onMouseEnter={() => setActive(index)}
                onClick={() => pick(v)}
              >
                {v}
                {value === v && <Check size={15} />}
              </button>
            ))}
            {!filtered.length && <p className="muted">검색 결과가 없습니다.</p>}
          </div>
        </div>
      )}
    </div>
  );
}
function Count({
  value,
  format,
}: {
  value: number;
  format: (n: number) => string;
}) {
  const ref = useRef<HTMLSpanElement>(null),
    reduce = useReducedMotion();
  const old = useRef(0);
  useEffect(() => {
    if (!ref.current) return;
    if (reduce) {
      ref.current.textContent = format(value);
      old.current = value;
      return;
    }
    const c = animate(old.current, value, {
      duration: 0.65,
      ease: "easeOut",
      onUpdate: (v) => {
        if (ref.current) ref.current.textContent = format(v);
      },
    });
    old.current = value;
    return () => c.stop();
  }, [value, format, reduce]);
  return <span ref={ref}>{format(value)}</span>;
}
export function Metric({
  label,
  value,
  prior,
  note,
  icon,
  accent = false,
  format = compact,
  comparisonAvailable = true,
}: {
  label: string;
  value: number;
  prior?: number;
  note: string;
  icon: ReactNode;
  accent?: boolean;
  format?: (n: number) => string;
  comparisonAvailable?: boolean;
}) {
  const delta =
    prior !== undefined && prior > 0 ? ((value - prior) / prior) * 100 : null;
  return (
    <motion.article
      layout
      className={"metric " + (accent ? "metric-accent" : "")}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <div className="metric-top">
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <div className="metric-value">
        <Count value={value} format={format} />
        {prior !== undefined && (
          <span
            className={"delta " + (delta !== null && delta < 0 ? "down" : "")}
          >
            {!comparisonAvailable ? (
              <Minus size={12} />
            ) : delta === null ? (
              <Minus size={12} />
            ) : delta >= 0 ? (
              <ArrowUpRight size={12} />
            ) : (
              <ArrowDownRight size={12} />
            )}
            {!comparisonAvailable
              ? "비교 없음"
              : delta === null
                ? "기준 없음"
                : Math.abs(delta).toFixed(1) + "%"}
          </span>
        )}
      </div>
      <div className="metric-note">{note}</div>
    </motion.article>
  );
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.section
      layout
      className={"panel " + className}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
    >
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </motion.section>
  );
}
export function Chart({
  option,
  dark,
  label,
  onClick,
  height = 280,
}: {
  option: echarts.EChartsCoreOption;
  dark: boolean;
  label: string;
  onClick?: (name: string) => void;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null),
    instance = useRef<echarts.EChartsType | null>(null),
    click = useRef(onClick);
  click.current = onClick;
  const reduce = useReducedMotion();
  // Unrelated UI updates (export/menu/toast) must not restart chart animations.
  const optionKey = JSON.stringify(option, (_key, value) =>
    typeof value === "function" ? value.toString() : value,
  );
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    instance.current = chart;
    chart.on("click", (p) => click.current?.(p.name));
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(ref.current);
    return () => {
      resize.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    instance.current?.setOption(
      {
        ...option,
        animation: !reduce,
        animationDuration: 550,
        animationDurationUpdate: 320,
        backgroundColor: "transparent",
        textStyle: {
          fontFamily: "Noto Sans KR, sans-serif",
          color: dark ? "#a9acc2" : "#7c8197",
        },
        aria: { enabled: true },
        tooltip: {
          trigger: "axis",
          confine: true,
          backgroundColor: dark ? "#24273a" : "#fff",
          borderColor: dark ? "#363b53" : "#e5e6ef",
          textStyle: { color: dark ? "#f3f4fa" : "#262940", fontSize: 12 },
          ...((option.tooltip as Record<string, unknown>) || {}),
        },
      },
      { notMerge: false, replaceMerge: ["series", "graphic"] },
    );
  }, [optionKey, dark, reduce]);
  return (
    <div
      ref={ref}
      className="chart"
      role="img"
      aria-label={label}
      style={{ height }}
    />
  );
}
export function lineOption(
  data: { date: string; value: number }[],
  dark: boolean,
  tokens = false,
) {
  return {
    legend: {
      top: 0,
      right: 15,
      data: [tokens ? "전체 토큰" : "질문 수"],
      textStyle: { color: dark ? "#a9acc2" : "#7c8197", fontSize: 10 },
      itemWidth: 12,
      itemHeight: 6,
    },
    grid: { left: 56, right: 20, top: 24, bottom: 57 },
    tooltip: {
      valueFormatter: (v: unknown) =>
        number(Number(v)) + (tokens ? " 토큰" : " 건"),
    },
    xAxis: {
      type: "category",
      data: data.map((d) => d.date),
      boundaryGap: false,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        formatter: (v: string) => v.slice(5).replace("-", "."),
        hideOverlap: true,
        margin: 16,
        color: dark ? "#898da8" : "#969aad",
      },
    },
    yAxis: {
      type: "value",
      splitNumber: 4,
      axisLabel: {
        formatter: (v: number) => compact(v),
        color: dark ? "#898da8" : "#969aad",
      },
      splitLine: {
        lineStyle: { color: dark ? "#2d3147" : "#eef0f6", type: "dashed" },
      },
    },
    dataZoom: [
      { type: "inside", filterMode: "none" },
      {
        type: "slider",
        height: 10,
        bottom: 9,
        borderColor: "transparent",
        fillerColor: "#6864e825",
        backgroundColor: "#6864e808",
        showDetail: false,
        handleSize: "150%",
        handleStyle: { color: "#8f8beb" },
        moveHandleSize: 0,
      },
    ],
    series: [
      {
        name: tokens ? "전체 토큰" : "질문 수",
        type: "line",
        data: data.map((d) => d.value),
        smooth: 0.22,
        symbol: "circle",
        symbolSize: 6,
        showSymbol: false,
        lineStyle: { color: "#726bec", width: 3 },
        itemStyle: { color: "#726bec" },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "#726bec38" },
            { offset: 1, color: "#726bec00" },
          ]),
        },
      },
    ],
  };
}
export function barOption(
  data: { name: string; value: number }[],
  dark: boolean,
  unit = "",
) {
  return {
    grid: { top: 4, left: 116, right: 50, bottom: 18 },
    xAxis: { type: "value", show: false },
    yAxis: {
      type: "category",
      inverse: true,
      data: data.map((d) => d.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        width: 105,
        overflow: "truncate",
        color: dark ? "#c0c2d4" : "#626980",
        fontSize: 11,
      },
    },
    tooltip: {
      trigger: "item",
      valueFormatter: (v: unknown) => number(Number(v)) + (unit ? " " + unit : ""),
    },
    series: [
      {
        type: "bar",
        barWidth: 12,
        data: data.map((d, i) => ({
          ...d,
          itemStyle: {
            color: palette[i % palette.length],
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: {
          show: true,
          position: "right",
          formatter: (p: { value: number }) => compact(p.value),
          color: dark ? "#b0b4ce" : "#70778f",
          fontSize: 10,
        },
      },
    ],
  };
}
export function Empty({
  title = "선택한 조건의 사용 기록이 없습니다",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-mark">
        <Search size={23} />
      </div>
      <h3>{title}</h3>
      <p>
        {children ||
          "기간이나 조직 필터를 변경해보세요. DB 사용자는 0건으로 유지됩니다."}
      </p>
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  drawer = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  drawer?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const active = document.activeElement as HTMLElement;
    dialog.showModal();
    return () => {
      dialog.close();
      active?.focus();
    };
  }, []);
  return (
    <dialog
      className={"modal " + (drawer ? "detail-drawer" : "")}
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-heading">
        <h2>{title}</h2>
        <IconButton label="닫기" onClick={onClose}>
          <X size={18} />
        </IconButton>
      </div>
      {children}
    </dialog>
  );
}
