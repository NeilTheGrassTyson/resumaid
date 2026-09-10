/** The application history: where you applied, when, and what came back.
 *
 * Editing a row is the point, not a side feature — outcomes arrive by email days later, and
 * answering the OA question is what teaches the prediction (ADR 0008).
 */
import { OUTCOMES, type Application, type Outcome } from "../api/client";

export default function LogTable({
  applications, onPatch,
}: {
  applications: Application[];
  onPatch: (id: number, patch: Record<string, unknown>) => void;
}) {
  if (applications.length === 0) {
    return (
      <div className="empty">
        <h2>Nothing submitted yet</h2>
        <p>
          Approve something in the queue, apply on the employer's site, then mark it submitted.
          It lands here.
        </p>
      </div>
    );
  }

  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            <th>Company</th>
            <th>Position</th>
            <th>Submitted</th>
            <th>Via</th>
            <th>Outcome</th>
            <th>Assessment</th>
            <th>Platform</th>
            <th>Resume</th>
            <th className="num">Fit</th>
          </tr>
        </thead>
        <tbody>
          {applications.map((row) => (
            <tr key={row.id}>
              <td>{row.company}</td>
              <td>
                {row.apply_url ? (
                  <a href={row.apply_url} target="_blank" rel="noreferrer"
                     style={{ color: "inherit" }}>
                    {row.title}
                  </a>
                ) : row.title}
              </td>
              <td className="date">{row.submitted_at.slice(0, 10)}</td>
              <td>{row.submission_channel ?? "—"}</td>
              <td>
                <select
                  className="cell"
                  value={row.outcome}
                  onChange={(e) => onPatch(row.id, { outcome: e.target.value as Outcome })}
                >
                  {OUTCOMES.map((outcome) => (
                    <option key={outcome} value={outcome}>{outcome}</option>
                  ))}
                </select>
              </td>
              <td>
                <select
                  className="cell"
                  value={row.oa_received === null ? "" : row.oa_received ? "yes" : "no"}
                  onChange={(e) =>
                    onPatch(row.id, {
                      oa_received: e.target.value === "" ? null : e.target.value === "yes",
                    })
                  }
                  title={
                    row.oa_received === null
                      ? `predicted: ${row.oa_expected}. Recording what actually happened is ` +
                        "what makes the next prediction yours rather than a keyword guess."
                      : undefined
                  }
                >
                  <option value="">{`— (predicted ${row.oa_expected})`}</option>
                  <option value="yes">yes</option>
                  <option value="no">no</option>
                </select>
              </td>
              <td>
                <input
                  className="cell"
                  type="text"
                  size={12}
                  defaultValue={row.oa_platform ?? ""}
                  placeholder="—"
                  onBlur={(e) => {
                    const value = e.target.value.trim();
                    if (value !== (row.oa_platform ?? "")) {
                      onPatch(row.id, { oa_platform: value || null });
                    }
                  }}
                />
              </td>
              <td className="note">{row.resume_used ?? "—"}</td>
              <td className="num">
                {row.fit_score_at_submit === null || row.fit_score_at_submit === undefined
                  ? "—"
                  : Math.round(row.fit_score_at_submit)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
