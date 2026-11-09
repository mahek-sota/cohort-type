import type { Cohort } from "./api";

interface Props {
  cohort: Cohort | null;
  incomplete: boolean;
  loading: boolean;
  error: string | null;
  name: string;
  presetCounts: number[];
  onViewPatients: () => void;
}

function Spread({ counts, current }: { counts: number[]; current: number }) {
  const scale = Math.max(...counts, current);
  const position = (value: number) => `${(value / scale) * 100}%`;

  return (
    <div aria-hidden="true" className="relative mt-6 hidden h-5 lg:block">
      <div className="absolute top-2 h-1 w-full rounded-full bg-ink-raised" />
      {counts.map((value, index) => (
        <div
          key={index}
          className="absolute top-1 h-3 w-0.5 -translate-x-1/2 rounded-full bg-on-ink-soft"
          style={{ left: position(value) }}
        />
      ))}
      <div
        className="absolute top-0 size-5 -translate-x-1/2 rounded-full border-[3px] border-ink bg-amber transition-[left] duration-200"
        style={{ left: position(current) }}
      />
    </div>
  );
}

export default function CohortCount({
  cohort,
  incomplete,
  loading,
  error,
  name,
  presetCounts,
  onViewPatients,
}: Props) {
  // Never show a count beside a definition it doesn't belong to.
  const current = incomplete || error !== null ? null : cohort;

  return (
    <section
      aria-label="Cohort"
      className="rounded-xl bg-ink p-4 text-on-ink shadow-lg shadow-ink/15 lg:p-7"
    >
      <h2 className="text-sm font-medium text-on-ink-soft">{name}</h2>
      <div className="mt-1 flex items-baseline gap-3 lg:block">
        <p
          aria-live="polite"
          className={`font-serif text-5xl font-semibold tabular-nums transition-opacity lg:mt-3 lg:text-8xl lg:leading-none ${
            loading ? "opacity-70" : ""
          }`}
        >
          {current ? current.count.toLocaleString() : "–"}
        </p>
        <p className="text-sm text-on-ink-soft tabular-nums lg:mt-3">
          {current
            ? `${current.percent.toFixed(1)}% of ${current.population.toLocaleString()} patients`
            : "No count for this definition"}
        </p>
      </div>
      {current && presetCounts.length > 0 && (
        <Spread counts={presetCounts} current={current.count} />
      )}
      {current && presetCounts.length > 0 && (
        <p className="mt-2 hidden text-xs text-on-ink-soft lg:block">
          Marks show the five definitions.
        </p>
      )}
      {current && current.count > 0 && (
        <button
          type="button"
          onClick={onViewPatients}
          className="mt-6 hidden w-full rounded-lg bg-amber px-3 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-[#f6c260] lg:block"
        >
          See these {current.count.toLocaleString()} patients
        </button>
      )}
      {incomplete && (
        <p className="mt-2 text-sm text-amber">Choose at least one type of record to count.</p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-amber">
          Couldn't get the count: {error}.
        </p>
      )}
    </section>
  );
}
