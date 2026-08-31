/** The middle pane: the posting, and — more importantly — why it is in your queue.
 *
 * The breakdown is not decoration. An unexplained score trains you to rubber-stamp the queue,
 * and the human-in-the-loop is the thing constraint 1 depends on.
 */
import type { QueueEntry } from "../api/client";
import { Badge, completenessLabel, relativeDay } from "./Bits";

export default function EntryDetail({ entry }: { entry: QueueEntry }) {
  const completeness = completenessLabel(entry);
  const dateNote =
    entry.posted_at_precision === "unknown"
      ? "posting date unknown"
      : `posted ${relativeDay(entry.posted_at)}${
          entry.posted_at_precision === "approximate" ? " (approximate)" : ""
        }`;

  return (
    <div className="pane">
      <div className="detail">
        <h1>{entry.title}</h1>
        <div className="sub">
          {entry.company}
          {entry.locations.length > 0 && ` · ${entry.locations.join(", ")}`}
          {entry.remote && " · remote"}
          {" · "}
          {dateNote}
          {entry.compensation && ` · ${entry.compensation}`}
        </div>
        <div className="sub">
          <a href={entry.apply_url} target="_blank" rel="noreferrer">
            {entry.apply_url}
          </a>{" "}
          <Badge>{entry.source}</Badge>{" "}
          {completeness && <Badge kind={completeness.cls}>{completeness.text}</Badge>}
        </div>

        {entry.provenance_note && <p className="provenance">{entry.provenance_note}</p>}

        <section className="section">
          <h2>
            Why this is here — fit {entry.fit_score === null ? "—" : Math.round(entry.fit_score!)}
            {entry.score_confidence !== "high" && `, ${entry.score_confidence} confidence`}
            {entry.role_family && ` · ${entry.role_family}`}
          </h2>
          <table className="dims">
            <tbody>
              {entry.dimensions.map((dim) => (
                <tr key={dim.name}>
                  <td className="d-name">{dim.name.replace(/_/g, " ")}</td>
                  <td className="d-score">{Math.round(dim.score)}</td>
                  <td className="d-bar">
                    <div className={`bar${dim.score >= 70 ? " good" : ""}`}>
                      <i style={{ width: `${Math.max(2, Math.min(100, dim.score))}%` }} />
                    </div>
                  </td>
                  <td className="d-why">{dim.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {entry.adjudication_note && (
            <p className="note" style={{ marginTop: 8 }}>
              LLM adjudication: {entry.adjudication_note}
            </p>
          )}
        </section>

        {entry.missing_signals.length > 0 && (
          <section className="section">
            <h2>What's missing</h2>
            <ul className="signal-list missing">
              {entry.missing_signals.map((signal, i) => (
                <li key={i}>{signal}</li>
              ))}
            </ul>
          </section>
        )}

        <section className="section">
          <h2>Posting</h2>
          {entry.description_text ? (
            <div className="posting">{entry.description_text}</div>
          ) : (
            <div className="empty" style={{ padding: "16px 0" }}>
              <h2>No description available</h2>
              <p>
                This posting could not be retrieved from a permitted source, so it is queued on
                its title, company and location alone — which is why its score is marked low
                confidence.
              </p>
              <p>
                Open it, copy the description, and press <kbd>p</kbd> to paste it in. The entry
                re-scores at full confidence.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
