/**
 * The review queue.
 *
 * Keyboard-first by design: this is a list you fly through every morning, not a form you fill
 * in. j/k move, a approves, x rejects, p pastes a description, enter records a submission.
 *
 * The one thing this UI cannot do is submit an application. Approving prepares materials and
 * moves an entry to the ready tray; the human applies on the employer's site and comes back to
 * record it. See CLAUDE.md constraint 1 and REVIEW_QUEUE_SPEC.md §6.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api, ApiError, REJECTION_REASONS,
  type Application, type QueueEntry, type RejectionReason, type Slate,
} from "./api/client";
import { Modal, Toast } from "./components/Bits";
import EntryDetail from "./components/EntryDetail";
import FilteredTable from "./components/FilteredTable";
import LogTable from "./components/LogTable";
import MaterialsRail from "./components/MaterialsRail";
import QueueList from "./components/QueueList";
import SetupTab from "./components/SetupTab";

type Tab = "queue" | "ready" | "log" | "filtered" | "setup";

const KEYS: Record<Tab, [string, string][]> = {
  queue: [
    ["j / k", "move"], ["a", "approve"], ["x", "reject"], ["s", "snooze"],
    ["o", "open posting"], ["p", "paste description"], ["r", "run discovery"],
  ],
  ready: [["j / k", "move"], ["o", "open posting"], ["enter", "I submitted this"], ["u", "back to queue"]],
  log: [["click a cell", "record an outcome"], ["e", "export CSV"]],
  filtered: [["1-5", "switch tab"]],
  setup: [["1-5", "switch tab"]],
};

export default function App() {
  const [tab, setTab] = useState<Tab>("queue");
  const [slate, setSlate] = useState<Slate | null>(null);
  const [ready, setReady] = useState<QueueEntry[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [filtered, setFiltered] = useState<QueueEntry[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [modal, setModal] = useState<null | "reject" | "paste" | "submitted">(null);
  const [pasteText, setPasteText] = useState("");
  const [channel, setChannel] = useState("");
  const [running, setRunning] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [setupIncomplete, setSetupIncomplete] = useState(false);

  const say = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((current) => (current === message ? null : current)), 3200);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [nextSlate, nextReady, nextApps, nextFiltered] = await Promise.all([
        api.slate(), api.ready(), api.applications(), api.filtered(),
      ]);
      setSlate(nextSlate);
      setReady(nextReady);
      setApplications(nextApps);
      setFiltered(nextFiltered);
      // A prompt on the Setup tab beats an empty queue with no explanation.
      await api.setupStatus()
        .then((status) => setSetupIncomplete(!status.ready))
        .catch(() => setSetupIncomplete(true));
    } catch (error) {
      say(error instanceof ApiError ? error.message : "Could not reach the local API.");
    } finally {
      setLoaded(true);
    }
  }, [say]);

  useEffect(() => { void refresh(); }, [refresh]);

  const list = tab === "ready" ? ready : (slate?.entries ?? []);
  const selected = useMemo(
    () => list.find((entry) => entry.id === selectedId) ?? list[0] ?? null,
    [list, selectedId],
  );

  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected, selectedId]);

  const move = useCallback((delta: number) => {
    if (list.length === 0) return;
    const index = Math.max(0, list.findIndex((entry) => entry.id === selected?.id));
    setSelectedId(list[Math.min(list.length - 1, Math.max(0, index + delta))].id);
  }, [list, selected]);

  const act = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    try {
      await fn();
      await refresh();
      say(label);
    } catch (error) {
      say(error instanceof ApiError ? error.message : String(error));
    }
  }, [refresh, say]);

  const approve = useCallback(() => {
    if (!selected) return;
    void act(`Approved — ${selected.title}. Nothing sent; it's in the ready tray.`,
             () => api.approve(selected.id));
  }, [act, selected]);

  const reject = useCallback((reason: RejectionReason) => {
    if (!selected) return;
    setModal(null);
    void act(`Rejected (${reason.replace(/_/g, " ")})`, () => api.reject(selected.id, reason));
  }, [act, selected]);

  const snooze = useCallback(() => {
    if (!selected) return;
    void act("Snoozed for 3 days", () => api.snooze(selected.id, 3));
  }, [act, selected]);

  const openPosting = useCallback(() => {
    if (selected) window.open(selected.apply_url, "_blank", "noreferrer");
  }, [selected]);

  const submitPaste = useCallback(() => {
    if (!selected || !pasteText.trim()) return;
    const text = pasteText;
    setModal(null);
    setPasteText("");
    void act("Description added — re-scored at full confidence",
             () => api.paste(selected.id, text));
  }, [act, pasteText, selected]);

  const confirmSubmitted = useCallback(() => {
    if (!selected) return;
    const via = channel.trim();
    setModal(null);
    setChannel("");
    void act("Logged. Good luck.", () => api.markSubmitted(selected.id, via || undefined));
  }, [act, channel, selected]);

  const runDiscovery = useCallback(async () => {
    setRunning(true);
    try {
      const report = await api.run();
      await refresh();
      say(report.summary);
    } catch (error) {
      say(error instanceof ApiError ? error.message : String(error));
    } finally {
      setRunning(false);
    }
  }, [refresh, say]);

  const patchApplication = useCallback((id: number, patch: Record<string, unknown>) => {
    void act("Recorded", () => api.updateApplication(id, patch));
  }, [act]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (modal) return;

      const key = event.key.toLowerCase();
      const tabs: Tab[] = ["queue", "ready", "log", "filtered", "setup"];
      if (["1", "2", "3", "4", "5"].includes(key)) { setTab(tabs[Number(key) - 1]); return; }
      if (tab === "log" || tab === "filtered" || tab === "setup") {
        if (key === "e" && tab === "log") window.location.href = "/api/applications/export";
        return;
      }
      switch (key) {
        case "j": case "arrowdown": event.preventDefault(); move(1); break;
        case "k": case "arrowup": event.preventDefault(); move(-1); break;
        case "o": openPosting(); break;
        case "a": if (tab === "queue") approve(); break;
        case "x": if (tab === "queue") setModal("reject"); break;
        case "s": if (tab === "queue") snooze(); break;
        case "p": if (tab === "queue") { setPasteText(""); setModal("paste"); } break;
        case "u":
          if (tab === "ready" && selected) {
            void act("Back in the queue", () => api.unapprove(selected.id));
          }
          break;
        case "enter": if (tab === "ready" && selected) setModal("submitted"); break;
        case "r": if (tab === "queue" && !running) void runDiscovery(); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [act, approve, modal, move, openPosting, runDiscovery, running, selected, snooze, tab]);

  const counts = slate?.counts ?? {};

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">resum<span>aid</span></div>
        <nav className="tabs" role="tablist">
          {([
            ["queue", "Queue", slate?.total_queued ?? 0],
            ["ready", "Ready to submit", ready.length],
            ["log", "Applications", applications.length],
            ["filtered", "Filtered", counts.filtered ?? 0],
            ["setup", "Setup", setupIncomplete ? -2 : -1],
          ] as [Tab, string, number][]).map(([id, label, count]) => (
            <button key={id} className="tab" role="tab" aria-selected={tab === id}
                    onClick={() => setTab(id)}>
              {label}
              {count >= 0 && <span className="count">{count}</span>}
              {count === -2 && (
                <span className="count needs" title="Add a resume and say what you're looking for">!</span>
              )}
            </button>
          ))}
        </nav>
        <div className="spacer" />
        {tab === "log" && applications.length > 0 && (
          <a className="ghost-btn" href="/api/applications/export"
             style={{ textDecoration: "none" }}>Download CSV</a>
        )}
        <button className="ghost-btn" onClick={() => void runDiscovery()} disabled={running}>
          {running ? "Running…" : "Run discovery"}
        </button>
      </header>

      {tab === "setup" ? (
        <div className="pane"><SetupTab onChanged={() => void refresh()} /></div>
      ) : tab === "log" ? (
        <div className="pane"><LogTable applications={applications} onPatch={patchApplication} /></div>
      ) : tab === "filtered" ? (
        <div className="pane"><FilteredTable entries={filtered} /></div>
      ) : list.length === 0 ? (
        <div className="pane">
          <EmptyState tab={tab} loaded={loaded} queued={slate?.total_queued ?? 0} />
        </div>
      ) : (
        <div className="triage" role="listbox" aria-label="Review queue">
          <QueueList
            entries={list}
            selectedId={selected?.id ?? null}
            onSelect={setSelectedId}
            heading={
              tab === "ready"
                ? `${ready.length} awaiting your submission`
                : `${list.length} shown · ${slate?.submissions_per_day ?? 5}/day target`
            }
          />
          {selected && <EntryDetail entry={selected} />}
          {selected && (
            <MaterialsRail
              entry={selected}
              onApprove={approve}
              onReject={() => setModal("reject")}
              onSnooze={snooze}
              onPaste={() => { setPasteText(""); setModal("paste"); }}
              onOpen={openPosting}
              onSubmitted={() => setModal("submitted")}
              onUnapprove={() =>
                void act("Back in the queue", () => api.unapprove(selected.id))}
            />
          )}
        </div>
      )}

      <footer className="keybar">
        {KEYS[tab].map(([key, label]) => (
          <span key={key}><kbd>{key}</kbd> <b>{label}</b></span>
        ))}
      </footer>

      {modal === "reject" && (
        <Modal title="Why not this one?"
               subtitle="The reason is the only honest signal for tuning the bar later."
               onClose={() => setModal(null)}>
          <div className="reasons">
            {REJECTION_REASONS.map((reason) => (
              <button key={reason.value} className="act" onClick={() => reject(reason.value)}>
                {reason.label}
              </button>
            ))}
          </div>
        </Modal>
      )}

      {modal === "paste" && (
        <Modal
          title="Paste the description"
          subtitle="Open the posting, copy its description, and paste it here. The entry re-scores at full confidence."
          onClose={() => setModal(null)}
        >
          <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)}
                    placeholder="Paste the job description…" />
          <div className="row-btns">
            <button className="ghost-btn" onClick={() => setModal(null)}>Cancel</button>
            <button className="act primary" style={{ width: "auto" }}
                    onClick={submitPaste} disabled={!pasteText.trim()}>
              Save and re-score
            </button>
          </div>
        </Modal>
      )}

      {modal === "submitted" && selected && (
        <Modal
          title="You submitted this?"
          subtitle="This records something you already did. The tool never submits on your behalf."
          onClose={() => setModal(null)}
        >
          <p className="note" style={{ marginBottom: 8 }}>
            {selected.title} at {selected.company}
          </p>
          <input type="text" value={channel} placeholder="Submitted via (greenhouse, workday, email…)"
                 onChange={(e) => setChannel(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && confirmSubmitted()} />
          <div className="row-btns">
            <button className="ghost-btn" onClick={() => setModal(null)}>Not yet</button>
            <button className="act confirm" style={{ width: "auto" }} onClick={confirmSubmitted}>
              Yes, log it
            </button>
          </div>
        </Modal>
      )}

      <Toast message={toast} />
    </div>
  );
}

function EmptyState({ tab, loaded, queued }: { tab: Tab; loaded: boolean; queued: number }) {
  if (!loaded) return <div className="empty">Loading…</div>;
  if (tab === "ready") {
    return (
      <div className="empty">
        <h2>Nothing approved yet</h2>
        <p>Approve something in the queue and it lands here with the resume to send and a link
           to the employer's form.</p>
      </div>
    );
  }
  return (
    <div className="empty">
      <h2>{queued > 0 ? "Nothing left for today" : "Queue is empty"}</h2>
      {queued > 0 ? (
        <p>You've worked through today's slate. Press <kbd>r</kbd> to look for more.</p>
      ) : (
        <>
          <p>
            Press <kbd>r</kbd> to run discovery, or from a terminal: <code>resumaid run</code>.
          </p>
          <p>
            If nothing turns up, check that you've added a resume
            (<code>resumaid resume add</code>) and declared what you're looking for in
            <code>interests.yaml</code>.
          </p>
          <p className="constraint">
            A thin day is a real answer: if only three roles clear the bar, only three are
            queued. The bar doesn't move to fill a quota.
          </p>
        </>
      )}
    </div>
  );
}
