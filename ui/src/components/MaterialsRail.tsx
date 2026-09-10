/** The right rail: what you'd send, what it'll cost you, and the actions.
 *
 * Approving prepares. It contacts no employer and submits nothing — the button says so,
 * because the distinction is the whole design (CLAUDE.md constraint 1).
 */
import type { QueueEntry } from "../api/client";
import { Badge } from "./Bits";

const OA_LABEL: Record<string, { text: string; kind: string }> = {
  likely: { text: "likely", kind: "warn" },
  possible: { text: "possible", kind: "" },
  unlikely: { text: "unlikely", kind: "confirm" },
  unknown: { text: "unknown", kind: "" },
};

export default function MaterialsRail({
  entry, onApprove, onReject, onSnooze, onPaste, onOpen, onSubmitted, onUnapprove,
}: {
  entry: QueueEntry;
  onApprove: () => void;
  onReject: () => void;
  onSnooze: () => void;
  onPaste: () => void;
  onOpen: () => void;
  onSubmitted: () => void;
  onUnapprove: () => void;
}) {
  const oa = OA_LABEL[entry.oa_expected] ?? OA_LABEL.unknown;
  const approved = entry.state === "approved";

  return (
    <div className="pane rail-pane">
      <div className="pane-head">{approved ? "Ready to submit" : "Materials"}</div>
      <div className="rail">
        <div>
          <div className="k">Resume to send</div>
          {entry.recommended_resume ? (
            <>
              <div className="v">{entry.recommended_resume.filename}</div>
              {entry.selection_rationale && (
                <div className="note" style={{ marginTop: 3 }}>{entry.selection_rationale}</div>
              )}
              <div className="path">{entry.recommended_resume.path}</div>
              {entry.runner_up_resume && (
                <div className="note" style={{ marginTop: 6 }}>
                  Runner-up: {entry.runner_up_resume.filename}
                </div>
              )}
            </>
          ) : (
            <div className="note">No resumes uploaded yet.</div>
          )}
        </div>

        <div>
          <div className="k">Online assessment</div>
          <div className="v">
            <Badge kind={oa.kind}>{oa.text}</Badge>{" "}
            <span className="note">{entry.oa_expectation_confidence} confidence</span>
          </div>
          {entry.oa_expectation_evidence.length > 0 && (
            <ul className="signal-list" style={{ marginTop: 6, fontSize: 12 }}>
              {entry.oa_expectation_evidence.map((item, i) => (
                <li key={i} title={item.quote ?? undefined}>{item.detail}</li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <div className="k">Actions</div>
          {approved ? (
            <>
              <button className="act" onClick={onOpen}>
                Open posting <kbd>o</kbd>
              </button>
              <button className="act confirm" onClick={onSubmitted}>
                I submitted this <kbd>enter</kbd>
              </button>
              <button className="act" onClick={onUnapprove}>
                Back to queue <kbd>u</kbd>
              </button>
              <p className="constraint">
                You fill in the employer's form yourself. This tool never submits an
                application — it prepares one and waits.
              </p>
            </>
          ) : (
            <>
              <button className="act primary" onClick={onApprove}>
                Approve <kbd>a</kbd>
              </button>
              <button className="act" onClick={onReject}>
                Reject <kbd>x</kbd>
              </button>
              <button className="act" onClick={onSnooze}>
                Snooze 3d <kbd>s</kbd>
              </button>
              <button className="act" onClick={onOpen}>
                Open posting <kbd>o</kbd>
              </button>
              <button className="act" onClick={onPaste}>
                Paste description <kbd>p</kbd>
              </button>
              <p className="constraint">
                Approving prepares this application and moves it to the ready tray. It sends
                nothing.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
