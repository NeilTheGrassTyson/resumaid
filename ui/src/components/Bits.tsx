/** Small shared pieces: confidence and completeness labels, badges, toasts, modals. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { QueueEntry } from "../api/client";

/** A score is never shown bare — its confidence travels with it.
 *  A number built from a title and a company name is not comparable to one built from a full
 *  posting, and presenting them identically teaches you to distrust every score. */
export function confidenceMark(confidence: string): string {
  return confidence === "high" ? "" : confidence === "medium" ? "~" : "?";
}

export function completenessLabel(entry: QueueEntry): { text: string; cls: string } | null {
  if (entry.completeness === "full") {
    return entry.description_source === "human_paste"
      ? { text: "you pasted this", cls: "confirm" }
      : null;
  }
  if (entry.completeness === "partial") return { text: "snippet only", cls: "" };
  return { text: "link only", cls: "warn" };
}

export function Badge({ children, kind = "" }: { children: ReactNode; kind?: string }) {
  return <span className={`badge ${kind}`}>{children}</span>;
}

export function Toast({ message }: { message: string | null }) {
  if (!message) return null;
  return <div className="toast" role="status">{message}</div>;
}

export function Modal({
  title, subtitle, onClose, children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("textarea, input, button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div className="modal-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" ref={ref} role="dialog" aria-modal="true" aria-label={title}>
        <h3>{title}</h3>
        {subtitle && <p>{subtitle}</p>}
        {children}
      </div>
    </div>
  );
}

/**
 * A comma-separated list, edited as free text.
 *
 * A plain controlled `<input value={list.join(", ")}>` re-derives its own displayed value from
 * the parsed array on every keystroke — so the instant you type a comma, the empty token it
 * produces gets filtered out and the comma you just typed disappears from the box. This keeps
 * the text you're typing as its own local state, only reconciling it against the canonical
 * array (dropping blanks, trimming whitespace) once you leave the field.
 */
export function CommaListInput({
  value, onChange, placeholder, className,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  className?: string;
}) {
  const [text, setText] = useState(value.join(", "));
  const focused = useRef(false);

  useEffect(() => {
    if (!focused.current) setText(value.join(", "));
  }, [value]);

  return (
    <input
      type="text"
      className={className}
      placeholder={placeholder}
      value={text}
      onFocus={() => { focused.current = true; }}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean));
      }}
      onBlur={() => {
        focused.current = false;
        setText(value.join(", "));
      }}
    />
  );
}

export function relativeDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}
