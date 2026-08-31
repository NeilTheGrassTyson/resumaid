/** The ranked list. Rows, not cards: this is a list you fly through, not a gallery. */
import { useEffect, useRef } from "react";
import type { QueueEntry } from "../api/client";
import { confidenceMark } from "./Bits";

export default function QueueList({
  entries, selectedId, onSelect, heading,
}: {
  entries: QueueEntry[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  heading: string;
}) {
  const selectedRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedId]);

  return (
    <div className="pane">
      <div className="pane-head">{heading}</div>
      {entries.map((entry) => {
        const selected = entry.id === selectedId;
        return (
          <div
            key={entry.id}
            ref={selected ? selectedRef : undefined}
            className="row"
            role="option"
            aria-selected={selected}
            onClick={() => onSelect(entry.id)}
          >
            <div className="score">
              {entry.fit_score === null || entry.fit_score === undefined
                ? "—"
                : Math.round(entry.fit_score)}
              <span className="conf">{confidenceMark(entry.score_confidence) || " "}</span>
            </div>
            <div>
              <div className="title">{entry.title}</div>
              <div className="meta">
                {entry.company}
                {entry.locations.length > 0 && ` · ${entry.locations[0]}`}
                {entry.oa_expected === "likely" && " · OA likely"}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
