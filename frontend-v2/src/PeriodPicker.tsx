import { useEffect, useId, useRef, useState } from "react";
import { CalendarDays, Check, ChevronDown } from "lucide-react";
import type { Query } from "./live-api";

const presets = [
  ["7d", "최근 7일"],
  ["month", "이번달"],
  ["all", "전체기간"],
  ["custom", "기간 지정"],
] as const;
export function validPeriod(start: string, end: string): boolean {
  const parse = (s: string) =>
    /^(?!0000)\d{4}-\d{2}-\d{2}$/.test(s) &&
    !Number.isNaN(Date.parse(s)) &&
    new Date(s).toISOString().slice(0, 10) === s;
  return !!(
    parse(start) &&
    parse(end) &&
    start <= end &&
    (Date.parse(end) - Date.parse(start)) / 86400000 < 3660
  );
}
export default function PeriodPicker({
  q,
  period,
  onChange,
}: {
  q: Query;
  period?: { start: string | null; end: string | null };
  onChange: (values: Partial<Query>) => void;
}) {
  const [open, setOpen] = useState<"menu" | "custom" | null>(null);
  const [start, setStart] = useState(""),
    [end, setEnd] = useState("");
  const root = useRef<HTMLDivElement>(null),
    trigger = useRef<HTMLButtonElement>(null),
    firstDate = useRef<HTMLInputElement>(null);
  const id = useId();
  const label =
    presets.find(([v]) => v === q.range)?.[1] ||
    (q.range === "30d" ? "최근 30일" : "최근 90일");
  function close() {
    setOpen(null);
    trigger.current?.focus();
  }
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(null);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(null);
        trigger.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    if (open === "custom") firstDate.current?.focus();
    else
      root.current
        ?.querySelector<HTMLButtonElement>(
          '[role="menuitemradio"][aria-checked="true"]',
        )
        ?.focus();
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  function choose(range: string) {
    if (range !== "custom") {
      onChange({ range, start: "", end: "" });
      close();
      return;
    }
    const today = new Date().toLocaleDateString("en-CA", {
      timeZone: "Asia/Seoul",
    });
    setStart(q.range === "custom" ? q.start : period?.start || today);
    setEnd(q.range === "custom" ? q.end : period?.end || today);
    setOpen("custom");
  }
  return (
    <div ref={root} className="period-picker">
      <button
        ref={trigger}
        type="button"
        className="button period-trigger"
        aria-label={`조회 기간: ${label}`}
        aria-haspopup={open === "custom" ? "dialog" : "menu"}
        aria-expanded={!!open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(open ? null : "menu")}
      >
        <CalendarDays size={16} />
        <span>{label}</span>
        <ChevronDown size={14} />
      </button>
      {open === "menu" && (
        <div
          id={id}
          role="menu"
          aria-label="조회 기간 선택"
          className="period-menu"
          onKeyDown={(e) => {
            if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
            e.preventDefault();
            const buttons = Array.from(
              e.currentTarget.querySelectorAll<HTMLButtonElement>("button"),
            );
            const index = buttons.indexOf(
              document.activeElement as HTMLButtonElement,
            );
            buttons[
              (index + (e.key === "ArrowDown" ? 1 : -1) + buttons.length) %
                buttons.length
            ]?.focus();
          }}
        >
          {presets.map(([value, text]) => (
            <button
              type="button"
              role="menuitemradio"
              aria-checked={q.range === value}
              key={value}
              onClick={() => choose(value)}
            >
              {text}
              {q.range === value && <Check size={15} />}
            </button>
          ))}
        </div>
      )}
      {open === "custom" && (
        <form
          id={id}
          role="dialog"
          aria-labelledby={id + "-title"}
          className="period-popover"
          onSubmit={(e) => {
            e.preventDefault();
            if (!validPeriod(start, end)) return;
            onChange({ range: "custom", start, end });
            close();
          }}
          onKeyDown={(e) => {
            if (e.key !== "Tab") return;
            const fields = Array.from(
              e.currentTarget.querySelectorAll<HTMLElement>(
                "input,button:not(:disabled)",
              ),
            );
            const first = fields[0],
              last = fields[fields.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last?.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first?.focus();
            }
          }}
        >
          <h2 id={id + "-title"}>사용자 지정 기간</h2>
          <p>조회할 시작일과 종료일을 선택하세요.</p>
          <fieldset>
            <legend>시작일</legend>
            <input
              ref={firstDate}
              required
              type="date"
              aria-label="시작일"
              value={start}
              max={end || undefined}
              onChange={(e) => setStart(e.target.value)}
            />
          </fieldset>
          <fieldset>
            <legend>종료일</legend>
            <input
              required
              type="date"
              aria-label="종료일"
              value={end}
              min={start || undefined}
              onChange={(e) => setEnd(e.target.value)}
            />
          </fieldset>
          {!validPeriod(start, end) && (
            <p className="period-error" role="status">
              시작일과 종료일을 확인하세요. 최대 3,660일을 선택할 수 있습니다.
            </p>
          )}
          <div className="period-actions">
            <button
              type="button"
              className="button period-cancel"
              onClick={close}
            >
              취소
            </button>
            <button
              type="submit"
              className="button primary"
              disabled={!validPeriod(start, end)}
            >
              적용
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
