import { useEffect, useState } from "react";

import type { CohortPatient } from "./api";

const PAGE_SIZE = 12;

interface Props {
  patients: CohortPatient[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
}

export default function PatientList({ patients, selectedId, loading, onSelect }: Props) {
  const [page, setPage] = useState(0);

  useEffect(() => setPage(0), [patients]);

  const pageCount = Math.max(1, Math.ceil(patients.length / PAGE_SIZE));
  const first = page * PAGE_SIZE;
  const visible = patients.slice(first, first + PAGE_SIZE);

  if (patients.length === 0) {
    return (
      <section aria-label="Patients">
        <p className="text-sm text-ink-soft">No patients match this definition.</p>
      </section>
    );
  }

  return (
    <section aria-label="Patients" className={loading ? "opacity-70" : undefined}>
      <ul className="divide-y divide-line overflow-hidden rounded-xl bg-card ring-1 ring-line">
        {visible.map((patient) => (
          <li key={patient.id}>
            <button
              type="button"
              aria-pressed={patient.id === selectedId}
              onClick={() => onSelect(patient.id)}
              className="flex w-full items-center justify-between gap-4 px-4 py-2.5 text-left text-sm transition-colors hover:bg-paper aria-pressed:bg-ink aria-pressed:text-on-ink"
            >
              <span className="font-medium">
                Patient <span className="font-mono text-[0.8rem]">{patient.id.slice(0, 6)}</span>
              </span>
              <span className="text-xs opacity-70 tabular-nums">
                {patient.evidence_rows} {patient.evidence_rows === 1 ? "record" : "records"}
              </span>
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-3 flex items-center justify-between text-sm text-ink-soft">
        <span className="tabular-nums">
          {first + 1}–{first + visible.length} of {patients.length.toLocaleString()}
        </span>
        <span className="flex gap-2">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => setPage(page - 1)}
            className="rounded-md bg-card px-3 py-1 font-medium ring-1 ring-line enabled:hover:ring-ink-faint disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={page >= pageCount - 1}
            onClick={() => setPage(page + 1)}
            className="rounded-md bg-card px-3 py-1 font-medium ring-1 ring-line enabled:hover:ring-ink-faint disabled:opacity-40"
          >
            Next
          </button>
        </span>
      </div>
    </section>
  );
}
