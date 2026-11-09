import { useEffect, useRef, useState } from "react";

import { fetchEvidence, type EvidenceRow, type Judgments } from "./api";

function plainName(row: EvidenceRow): string {
  return row.table === "observations" ? "HbA1c result" : row.description.replace(/ \(.*\)$/, "");
}

interface Props {
  patientId: string;
  judgments: Judgments;
  onClose: () => void;
}

interface Loaded {
  key: string;
  rows: EvidenceRow[] | null;
  error: string | null;
}

export default function EvidencePanel({ patientId, judgments, onClose }: Props) {
  const panel = useRef<HTMLElement>(null);
  const scrolledTo = useRef<string | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = JSON.stringify([patientId, judgments]);

  useEffect(() => {
    const controller = new AbortController();
    fetchEvidence(patientId, judgments, controller.signal)
      .then((rows) => setLoaded({ key, rows, error: null }))
      .catch((error: Error) => {
        if (error.name !== "AbortError") {
          setLoaded({ key, rows: null, error: error.message });
        }
      });
    return () => controller.abort();
  }, [key, patientId, judgments]);

  // Results for an earlier patient or definition must not appear under the current one.
  const current = loaded?.key === key ? loaded : null;

  // Scroll once the rows are in, since the page may be too short before that. Changing the
  // definition keeps the same patient, so it shouldn't move the page.
  useEffect(() => {
    if (current && scrolledTo.current !== patientId) {
      scrolledTo.current = patientId;
      panel.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }, [current, patientId]);

  return (
    <section
      ref={panel}
      aria-label="Evidence"
      className="scroll-mt-6 min-w-0 rounded-xl bg-card p-6 ring-1 ring-line lg:sticky lg:top-6"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-serif text-2xl font-semibold">
            Patient <span className="font-mono text-xl">{patientId.slice(0, 6)}</span>
          </h2>
          {current?.rows && current.rows.length > 0 && (
            <p className="mt-1 text-sm text-ink-soft">
              Counts because of {current.rows.length}{" "}
              {current.rows.length === 1 ? "record" : "records"}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-md px-3 py-1 text-sm font-medium text-ink-soft ring-1 ring-line hover:ring-ink-faint"
        >
          Close
        </button>
      </div>

      {!current && <p className="mt-5 text-sm text-ink-soft">Loading the records.</p>}
      {current?.error && (
        <p role="alert" className="mt-5 text-sm">
          Couldn't load the records: {current.error}.
        </p>
      )}
      {current?.rows?.length === 0 && (
        <p className="mt-5 rounded-lg bg-paper p-4 text-sm">
          This patient doesn't count under the current definition.
        </p>
      )}
      {current?.rows && current.rows.length > 0 && (
        <ol className="mt-6 space-y-5 border-l-2 border-line pl-5">
          {current.rows.map((row) => (
            <li key={`${row.table}-${row.row}`} className="relative text-sm">
              <span
                aria-hidden="true"
                className={`absolute top-1 -left-[1.72rem] size-3 rounded-full ring-4 ring-card ${
                  row.table === "observations" ? "bg-amber" : "bg-accent"
                }`}
              />
              <p className="text-xs font-medium text-ink-faint tabular-nums">{row.date}</p>
              <div className="mt-0.5 flex items-baseline justify-between gap-4">
                <span className="font-medium">{plainName(row)}</span>
                {row.value && (
                  <span className="shrink-0 font-serif text-lg font-semibold tabular-nums">
                    {row.value}
                    {row.units}
                  </span>
                )}
              </div>
              <p className="mt-0.5 font-mono text-xs text-ink-faint">
                {row.table}.csv line {row.row}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
