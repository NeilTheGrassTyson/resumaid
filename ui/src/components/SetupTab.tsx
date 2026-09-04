/**
 * Setup: resumes, what you're looking for, and which boards to poll.
 *
 * Everything here writes to the same files the CLI reads — `~/.resumaid/profile.yaml`,
 * `interests.yaml`, and the SQLite database — so the two surfaces stay interchangeable and
 * nothing is trapped in the browser.
 *
 * Ordered the way a new user needs it: you cannot score anything without a resume, and you
 * cannot filter anything without saying what you want.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, ApiError,
  type Board, type Interests, type PlacePref, type Profile, type Resume, type RoleFamily,
} from "../api/client";

type Loaded = {
  resumes: Resume[];
  profile: Profile | null;
  interests: Interests | null;
  boards: Board[];
};

/**
 * Interests with every section present.
 *
 * The API model gives these defaults so a hand-written interests.yaml can omit whole sections,
 * which makes them optional in the generated types. A form needs them present, so the draft is
 * normalized once on load rather than null-checked at every field.
 */
type Draft = Required<Interests> & {
  locations: Required<NonNullable<Interests["locations"]>>;
  hard_filters: Required<NonNullable<Interests["hard_filters"]>>;
  exclusions: Required<NonNullable<Interests["exclusions"]>>;
  throughput: Required<NonNullable<Interests["throughput"]>>;
};

function normalize(interests: Interests | null): Draft {
  const base = interests ?? EMPTY_INTERESTS;
  return {
    role_families: base.role_families ?? [],
    industries: base.industries ?? [],
    locations: {
      remote: base.locations?.remote ?? true,
      home: base.locations?.home ?? null,
      max_distance_miles: base.locations?.max_distance_miles ?? 50,
      places: base.locations?.places ?? [],
      metros: base.locations?.metros ?? [],
      relocation: base.locations?.relocation ?? "no",
    },
    hard_filters: {
      degree_level_min: base.hard_filters?.degree_level_min ?? null,
      seniority: base.hard_filters?.seniority ?? [],
      citizenship_required_ok: base.hard_filters?.citizenship_required_ok ?? true,
      clearance_required_ok: base.hard_filters?.clearance_required_ok ?? false,
      employment_types: base.hard_filters?.employment_types ?? [],
    },
    exclusions: {
      companies: base.exclusions?.companies ?? [],
      title_keywords: base.exclusions?.title_keywords ?? [],
    },
    throughput: {
      submissions_per_day: base.throughput?.submissions_per_day ?? 5,
    },
  };
}

const EMPTY_INTERESTS: Interests = {
  role_families: [],
  industries: [],
  locations: {
    remote: true, home: null, max_distance_miles: 50,
    places: [], metros: [], relocation: "no",
  },
  hard_filters: {
    degree_level_min: null, seniority: [], citizenship_required_ok: true,
    clearance_required_ok: false, employment_types: [],
  },
  exclusions: { companies: [], title_keywords: [] },
  throughput: { submissions_per_day: 5 },
};

export default function SetupTab({ onChanged }: { onChanged: () => void }) {
  const [data, setData] = useState<Loaded>({
    resumes: [], profile: null, interests: null, boards: [],
  });
  const [draft, setDraft] = useState<Draft>(normalize(null));
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const say = useCallback((text: string) => {
    setError(null);
    setMessage(text);
    window.setTimeout(() => setMessage((m) => (m === text ? null : m)), 3200);
  }, []);

  const load = useCallback(async () => {
    const [resumes, boards] = await Promise.all([api.resumes(), api.boards()]);
    // Both 404 before first setup, which is a state to render rather than an error.
    const profile = await api.profile().catch(() => null);
    const interests = await api.interests().catch(() => null);
    setData({ resumes, profile, interests, boards });
    if (interests && !dirty) setDraft(normalize(interests));
  }, [dirty]);

  useEffect(() => { void load(); }, [load]);

  const act = useCallback(
    async (label: string, fn: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await fn();
        await load();
        onChanged();
        say(label);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [load, onChanged, say],
  );

  const patchLocations = (patch: Partial<Draft["locations"]>) => {
    setDirty(true);
    setDraft((d) => ({ ...d, locations: { ...d.locations, ...patch } }));
  };

  return (
    <div className="setup">
      {(message || error) && (
        <div className={`setup-note ${error ? "bad" : "good"}`}>{error ?? message}</div>
      )}

      <ResumeSection
        resumes={data.resumes}
        profile={data.profile}
        busy={busy}
        act={act}
        onError={setError}
      />

      <InterestsSection
        draft={draft}
        dirty={dirty}
        busy={busy}
        onPatch={(patch) => { setDirty(true); setDraft((d) => ({ ...d, ...patch })); }}
        onPatchLocations={patchLocations}
        onSave={() =>
          act("Saved what you're looking for", async () => {
            await api.saveInterests(draft);
            setDirty(false);
          })
        }
        onRevert={() => { setDraft(normalize(data.interests)); setDirty(false); }}
      />

      <BoardSection boards={data.boards} busy={busy} act={act} />
    </div>
  );
}

/* --- resumes ------------------------------------------------------------------------- */

function ResumeSection({
  resumes, profile, busy, act, onError,
}: {
  resumes: Resume[];
  profile: Profile | null;
  busy: boolean;
  act: (label: string, fn: () => Promise<unknown>) => Promise<void>;
  onError: (message: string) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const upload = (files: FileList | null) => {
    if (!files?.length) return;
    const file = files[0];
    void act(`Added ${file.name}`, () => api.uploadResume(file, resumes.length === 0));
  };

  return (
    <section className="setup-block">
      <h2>Resumes</h2>
      <p className="note">
        Upload the resumes you already maintain. The tool picks the best-fitting one for each
        role — it never rewrites them.
      </p>

      <div
        className={`dropzone${dragging ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); upload(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
      >
        <strong>Drop a resume here</strong>
        <span className="note">or click to choose — PDF, DOCX, Markdown or plain text</span>
        <input
          ref={input}
          type="file"
          accept=".pdf,.docx,.md,.txt"
          hidden
          onChange={(e) => { upload(e.target.files); e.target.value = ""; }}
        />
      </div>

      {resumes.length > 0 && (
        <table className="data compact">
          <thead>
            <tr><th>File</th><th>Emphasis</th><th>Master</th><th /></tr>
          </thead>
          <tbody>
            {resumes.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.filename}</td>
                <td className="note">{doc.emphasis_summary || "—"}</td>
                <td>
                  {doc.is_master ? (
                    <span className="badge confirm">master</span>
                  ) : (
                    <button
                      className="linkish"
                      disabled={busy}
                      onClick={() =>
                        void act(`${doc.filename} is now your master`, () =>
                          api.setMasterResume(doc.id))
                      }
                    >
                      set as master
                    </button>
                  )}
                </td>
                <td>
                  <button
                    className="linkish danger"
                    disabled={busy}
                    onClick={() =>
                      void act(`Removed ${doc.filename}`, () => api.deleteResume(doc.id))
                    }
                    title="Forgets the record. Your file is left alone."
                  >
                    remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {profile && (
        <details className="parsed">
          <summary>
            What was read from them — {profile.skills?.length ?? 0} skills,{" "}
            {profile.highest_degree_level ?? "degree unknown"},{" "}
            {profile.locations?.[0] ?? "location unknown"}
          </summary>
          <p className="note">
            The parse is a starting point, not an authority. Correct anything it got wrong —
            this is what roles are scored against.
          </p>
          <div className="kv">
            <label>
              Highest degree
              <input
                type="text"
                defaultValue={profile.highest_degree_level ?? ""}
                placeholder="bachelors"
                onBlur={(e) =>
                  void act("Profile saved", () =>
                    api.saveProfile({ ...profile, highest_degree_level: e.target.value || null }))
                }
              />
            </label>
            <label>
              Home location
              <input
                type="text"
                defaultValue={profile.locations?.[0] ?? ""}
                placeholder="Boston, MA"
                onBlur={(e) =>
                  void act("Profile saved", () =>
                    api.saveProfile({
                      ...profile,
                      locations: e.target.value ? [e.target.value] : [],
                    }))
                }
              />
            </label>
          </div>
          <label className="wide">
            Skills (comma separated)
            <textarea
              defaultValue={(profile.skills ?? []).join(", ")}
              onBlur={(e) =>
                void act("Profile saved", () =>
                  api.saveProfile({
                    ...profile,
                    skills: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  }))
              }
            />
          </label>
          <button
            className="ghost-btn"
            disabled={busy}
            onClick={() =>
              api.reparseProfile()
                .then(() => window.location.reload())
                .catch((err) => onError(String(err)))
            }
            title="Re-reads your resumes and discards edits made here"
          >
            Re-parse from resumes
          </button>
        </details>
      )}
    </section>
  );
}

/* --- interests ----------------------------------------------------------------------- */

function InterestsSection({
  draft, dirty, busy, onPatch, onPatchLocations, onSave, onRevert,
}: {
  draft: Draft;
  dirty: boolean;
  busy: boolean;
  onPatch: (patch: Partial<Draft>) => void;
  onPatchLocations: (patch: Partial<Draft["locations"]>) => void;
  onSave: () => void;
  onRevert: () => void;
}) {
  const families = draft.role_families;
  const places = draft.locations.places;

  const setFamily = (index: number, patch: Partial<RoleFamily>) =>
    onPatch({
      role_families: families.map((f, i) => (i === index ? { ...f, ...patch } : f)),
    });

  const setPlace = (index: number, patch: Partial<PlacePref>) =>
    onPatchLocations({ places: places.map((p, i) => (i === index ? { ...p, ...patch } : p)) });

  return (
    <section className="setup-block">
      <h2>What you're looking for</h2>
      <p className="note">
        Nothing is assumed. Roles are scored against this and what your resumes say — the tool
        has no built-in idea of which jobs are worth having.
      </p>

      <h3>Role families</h3>
      <p className="note">
        Weight is how much you want it. A lower weight ranks a family below others without
        excluding it; use the higher bar to say “only if it's a strong match”.
      </p>
      {families.map((family, i) => (
        <div className="family-row" key={i}>
          <input
            type="text"
            placeholder="aerospace &amp; defense software"
            value={family.name}
            onChange={(e) => setFamily(i, { name: e.target.value })}
          />
          <input
            type="text"
            placeholder="keywords, comma separated"
            value={(family.keywords ?? []).join(", ")}
            onChange={(e) =>
              setFamily(i, {
                keywords: e.target.value.split(",").map((k) => k.trim()).filter(Boolean),
              })
            }
          />
          <label className="tight">
            weight
            <input
              type="number" step="0.1" min="0" max="2"
              value={family.weight}
              onChange={(e) => setFamily(i, { weight: Number(e.target.value) })}
            />
          </label>
          <label className="tight" title="Only queue this family above this fit score">
            higher bar
            <input
              type="number" step="1" min="0" max="100"
              placeholder="—"
              value={family.min_fit ?? ""}
              onChange={(e) =>
                setFamily(i, { min_fit: e.target.value ? Number(e.target.value) : null })
              }
            />
          </label>
          <button
            className="linkish danger"
            onClick={() => onPatch({ role_families: families.filter((_, j) => j !== i) })}
          >
            remove
          </button>
        </div>
      ))}
      <button
        className="ghost-btn"
        onClick={() =>
          onPatch({
            role_families: [...families, { name: "", weight: 1.0, keywords: [], min_fit: null }],
          })
        }
      >
        Add a role family
      </button>

      <h3>Where you'll work</h3>
      <div className="kv">
        <label className="check">
          <input
            type="checkbox"
            checked={draft.locations.remote}
            onChange={(e) => onPatchLocations({ remote: e.target.checked })}
          />
          I'll take remote roles
        </label>
        <label>
          Home base
          <input
            type="text"
            placeholder="from your resume"
            value={draft.locations.home ?? ""}
            onChange={(e) => onPatchLocations({ home: e.target.value || null })}
          />
        </label>
        <label title="Anything closer than this counts as local, whichever state it's in">
          Local within (miles)
          <input
            type="number" min="0" step="5"
            placeholder="off"
            value={draft.locations.max_distance_miles ?? ""}
            onChange={(e) =>
              onPatchLocations({
                max_distance_miles: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
        <label>
          Relocation
          <select
            value={draft.locations.relocation}
            onChange={(e) => onPatchLocations({ relocation: e.target.value })}
          >
            <option value="no">not relocating</option>
            <option value="willing">would relocate</option>
            <option value="preferred">would prefer to</option>
          </select>
        </label>
      </div>

      <p className="note">
        Named places and states, each weighted. Weight only raises a location's score — to rule
        somewhere out, leave it off this list.
      </p>
      {places.map((place, i) => (
        <div className="place-row" key={i}>
          <select
            value={place.state ? "state" : "place"}
            onChange={(e) =>
              setPlace(i, e.target.value === "state"
                ? { place: null, state: place.place ?? "" }
                : { place: place.state ?? "", state: null })
            }
          >
            <option value="place">city</option>
            <option value="state">state</option>
          </select>
          <input
            type="text"
            placeholder={place.state !== null && place.state !== undefined ? "CO" : "Boston, MA"}
            value={place.state ?? place.place ?? ""}
            onChange={(e) =>
              setPlace(i, place.state !== null && place.state !== undefined
                ? { state: e.target.value }
                : { place: e.target.value })
            }
          />
          <label className="tight">
            weight
            <input
              type="number" step="0.1" min="0" max="1"
              value={place.weight}
              onChange={(e) => setPlace(i, { weight: Number(e.target.value) })}
            />
          </label>
          <button
            className="linkish danger"
            onClick={() => onPatchLocations({ places: places.filter((_, j) => j !== i) })}
          >
            remove
          </button>
        </div>
      ))}
      <button
        className="ghost-btn"
        onClick={() =>
          onPatchLocations({ places: [...places, { place: "", state: null, weight: 1.0 }] })
        }
      >
        Add a place
      </button>

      <h3>Hard filters</h3>
      <p className="note">These remove roles outright rather than ranking them low.</p>
      <div className="kv">
        <label>
          Minimum degree
          <select
            value={draft.hard_filters.degree_level_min ?? ""}
            onChange={(e) =>
              onPatch({
                hard_filters: {
                  ...draft.hard_filters,
                  degree_level_min: e.target.value || null,
                },
              })
            }
          >
            <option value="">no requirement</option>
            <option value="highschool">high school</option>
            <option value="associate">associate</option>
            <option value="bachelors">bachelors</option>
            <option value="masters">masters</option>
            <option value="doctorate">doctorate</option>
          </select>
        </label>
        <label>
          Seniority (comma separated)
          <input
            type="text"
            placeholder="intern, new-grad, junior"
            value={(draft.hard_filters.seniority ?? []).join(", ")}
            onChange={(e) =>
              onPatch({
                hard_filters: {
                  ...draft.hard_filters,
                  seniority: e.target.value.split(",").map((v) => v.trim()).filter(Boolean),
                },
              })
            }
          />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.hard_filters.clearance_required_ok ?? false}
            onChange={(e) =>
              onPatch({
                hard_filters: {
                  ...draft.hard_filters,
                  clearance_required_ok: e.target.checked,
                },
              })
            }
          />
          I can hold a security clearance
        </label>
        <label title="Applications you intend to send per day. The queue surfaces more, because you reject some.">
          Submissions per day
          <input
            type="number" min="1" max="50"
            value={draft.throughput.submissions_per_day}
            onChange={(e) =>
              onPatch({ throughput: { submissions_per_day: Number(e.target.value) } })
            }
          />
        </label>
      </div>

      <h3>Never show me</h3>
      <div className="kv">
        <label>
          Companies
          <input
            type="text"
            placeholder="comma separated"
            value={(draft.exclusions.companies ?? []).join(", ")}
            onChange={(e) =>
              onPatch({
                exclusions: {
                  ...draft.exclusions,
                  companies: e.target.value.split(",").map((v) => v.trim()).filter(Boolean),
                },
              })
            }
          />
        </label>
        <label>
          Title keywords
          <input
            type="text"
            placeholder="staffing, commission-only"
            value={(draft.exclusions.title_keywords ?? []).join(", ")}
            onChange={(e) =>
              onPatch({
                exclusions: {
                  ...draft.exclusions,
                  title_keywords: e.target.value.split(",").map((v) => v.trim()).filter(Boolean),
                },
              })
            }
          />
        </label>
      </div>

      <div className="save-row">
        <button className="act primary" style={{ width: "auto" }} disabled={busy || !dirty}
                onClick={onSave}>
          {dirty ? "Save" : "Saved"}
        </button>
        {dirty && (
          <button className="ghost-btn" onClick={onRevert}>Discard changes</button>
        )}
      </div>
    </section>
  );
}

/* --- boards -------------------------------------------------------------------------- */

function BoardSection({
  boards, busy, act,
}: {
  boards: Board[];
  busy: boolean;
  act: (label: string, fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [url, setUrl] = useState("");

  const add = () => {
    const value = url.trim();
    if (!value) return;
    void act("Board added", async () => {
      await api.addBoard(value);
      setUrl("");
    });
  };

  return (
    <section className="setup-block">
      <h2>Job boards</h2>
      <p className="note">
        Companies polled directly. These accumulate on their own — when an aggregator turns up a
        role hosted on a known ATS, that board registers itself and its full descriptions become
        available from then on.
      </p>

      <div className="place-row">
        <input
          type="text"
          placeholder="https://boards.greenhouse.io/company"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          style={{ flex: 1 }}
        />
        <button className="ghost-btn" disabled={busy || !url.trim()} onClick={add}>
          Add board
        </button>
      </div>

      {boards.length === 0 ? (
        <p className="note">None yet. Add one above, or let a run discover them.</p>
      ) : (
        <table className="data compact">
          <thead>
            <tr>
              <th>Source</th><th>Company</th><th>Found via</th><th>Last poll</th><th />
            </tr>
          </thead>
          <tbody>
            {boards.map((board) => (
              <tr key={board.id} className={board.enabled ? "" : "off"}>
                <td>{board.source}</td>
                <td>{board.company || board.token}</td>
                <td className="note">{board.discovered_via ?? "—"}</td>
                <td className="note">{board.last_status ?? "not yet"}</td>
                <td>
                  {board.enabled ? (
                    <button className="linkish danger" disabled={busy}
                            onClick={() => void act("Board disabled",
                              () => api.removeBoard(board.id))}>
                      disable
                    </button>
                  ) : (
                    <button className="linkish" disabled={busy}
                            onClick={() => void act("Board enabled",
                              () => api.enableBoard(board.id))}>
                      enable
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
