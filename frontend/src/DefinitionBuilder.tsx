import type { Evidence, Preset } from "./api";
import type { Draft } from "./definition";

const EVIDENCE_OPTIONS: { value: Evidence; label: string }[] = [
  { value: "codes", label: "Diagnosis records" },
  { value: "labs", label: "Lab results" },
  { value: "both", label: "Either one" },
];

type CodeGroupKey =
  | "includeDiagnosis"
  | "includeComplications"
  | "includeOtherComplications"
  | "includePrediabetes";

const CODE_GROUPS: { key: CodeGroupKey; label: string; detail: string }[] = [
  {
    key: "includeDiagnosis",
    label: "Type 2 diabetes diagnosis",
    detail: "The diagnosis itself",
  },
  {
    key: "includeComplications",
    label: "Type 2 complications",
    detail: "Kidney, nerve, and eye problems recorded as due to type 2 diabetes",
  },
  {
    key: "includeOtherComplications",
    label: "Other diabetic complications",
    detail: 'Worded differently, so a search for "type 2 diabetes" misses them',
  },
  {
    key: "includePrediabetes",
    label: "Prediabetes",
    detail: "High blood sugar, below the diabetes range",
  },
];

interface Props {
  presets: Preset[];
  presetCounts: Record<string, number>;
  activePreset: Preset | undefined;
  draft: Draft;
  onChange: (draft: Draft) => void;
  onSelectPreset: (preset: Preset) => void;
}

const SECTION_TITLE = "font-serif text-xl font-semibold";

export default function DefinitionBuilder({
  presets,
  presetCounts,
  activePreset,
  draft,
  onChange,
  onSelectPreset,
}: Props) {
  const usesCodes = draft.evidence !== "labs";
  const usesLabs = draft.evidence !== "codes";
  const largest = Math.max(1, ...Object.values(presetCounts));

  return (
    <section aria-label="Definition" className="min-w-0 space-y-10">
      <div>
        <h2 className={SECTION_TITLE}>Five defensible answers</h2>
        <p className="mt-1 text-sm text-ink-soft">Pick one, then change it below.</p>
        <div className="mt-4 space-y-2">
          {presets.map((preset) => {
            const count = presetCounts[preset.id];
            return (
              <button
                key={preset.id}
                type="button"
                aria-pressed={preset.id === activePreset?.id}
                onClick={() => onSelectPreset(preset)}
                className="group relative flex w-full items-center justify-between gap-4 overflow-hidden rounded-lg bg-card px-4 py-3 text-left text-sm ring-1 ring-line transition-shadow hover:ring-ink-faint aria-pressed:ring-2 aria-pressed:ring-accent"
              >
                <span
                  aria-hidden="true"
                  className="absolute inset-y-0 left-0 bg-accent-soft/60 transition-[width] duration-500 group-aria-pressed:bg-accent-soft"
                  style={{ width: `${((count ?? 0) / largest) * 100}%` }}
                />
                <span className="relative font-medium">{preset.name}</span>
                <span className="relative font-serif text-xl font-semibold tabular-nums">
                  {count ?? ""}
                </span>
              </button>
            );
          })}
        </div>
        {activePreset && (
          <p className="mt-4 border-l-[3px] border-amber pl-4 text-sm leading-6 text-ink-soft">
            {activePreset.rationale}
          </p>
        )}
      </div>

      <div className="rounded-xl bg-card p-5 ring-1 ring-line sm:p-6">
        <h2 className={SECTION_TITLE}>Make your own decisions</h2>

        <fieldset className="mt-5">
          <legend className="text-sm font-medium">What can qualify a patient?</legend>
          <div className="mt-2 inline-flex max-w-full rounded-lg bg-paper p-1">
            {EVIDENCE_OPTIONS.map((option) => (
              <label
                key={option.value}
                className="cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap text-ink-soft transition-colors has-checked:bg-ink has-checked:text-on-ink has-focus-visible:outline-2 has-focus-visible:outline-accent sm:px-4"
              >
                <input
                  type="radio"
                  name="evidence"
                  value={option.value}
                  checked={draft.evidence === option.value}
                  onChange={() => onChange({ ...draft, evidence: option.value })}
                  className="sr-only"
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>

        {usesCodes && (
          <fieldset className="mt-6 border-t border-line pt-5">
            <legend className="float-left w-full text-sm font-medium">Which records count?</legend>
            <div className="clear-both space-y-1 pt-2">
              {CODE_GROUPS.map((group) => (
                <label
                  key={group.key}
                  className="flex cursor-pointer items-center justify-between gap-4 rounded-lg py-2 text-sm"
                >
                  <span>
                    <span className="font-medium">{group.label}</span>
                    <span className="block text-ink-faint">{group.detail}</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={draft[group.key]}
                    onChange={(event) => onChange({ ...draft, [group.key]: event.target.checked })}
                    className="peer sr-only"
                  />
                  <span
                    aria-hidden="true"
                    className="relative h-6 w-10 shrink-0 rounded-full bg-line transition-colors peer-checked:bg-accent peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:after:translate-x-4"
                  />
                </label>
              ))}
            </div>
          </fieldset>
        )}

        {usesLabs && (
          <fieldset className="mt-6 border-t border-line pt-5">
            <legend className="float-left w-full text-sm font-medium">HbA1c at or above</legend>
            <div className="clear-both flex items-center gap-4 pt-3">
              <input
                type="range"
                aria-label="HbA1c threshold"
                min={5}
                max={10}
                step={0.1}
                value={draft.threshold}
                onChange={(event) => onChange({ ...draft, threshold: Number(event.target.value) })}
                className="w-full accent-accent"
              />
              <output className="w-16 shrink-0 text-right font-serif text-xl font-semibold tabular-nums">
                {draft.threshold.toFixed(1)}%
              </output>
            </div>
            <p className="mt-1 text-sm text-ink-faint">
              HbA1c is a blood sugar test. One result at this level qualifies a patient.
            </p>
          </fieldset>
        )}
      </div>
    </section>
  );
}
