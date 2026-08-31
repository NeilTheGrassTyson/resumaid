/** What the gate removed, and why.
 *
 * Filtered entries are retained rather than deleted: this table is how you audit whether the
 * bar is throwing away things it shouldn't.
 */
import type { QueueEntry } from "../api/client";
import { confidenceMark } from "./Bits";

export default function FilteredTable({ entries }: { entries: QueueEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="empty">
        <h2>Nothing filtered</h2>
        <p>Once a run has scored some postings, everything below the bar shows up here.</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th className="num">Fit</th>
            <th>Position</th>
            <th>Company</th>
            <th>Location</th>
            <th>Why it was filtered</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td className="num">
                {entry.fit_score === null || entry.fit_score === undefined
                  ? "—"
                  : `${Math.round(entry.fit_score)}${confidenceMark(entry.score_confidence)}`}
              </td>
              <td>{entry.title}</td>
              <td>{entry.company}</td>
              <td className="note">{entry.locations[0] ?? "—"}</td>
              <td className="note">{entry.filter_reason ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
