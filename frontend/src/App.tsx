import { useEffect, useMemo, useState } from "react";

import AgentComparison from "./AgentComparison";
import {
  fetchCohort,
  fetchPresets,
  type Cohort,
  type DecodedAnswer,
  type Preset,
} from "./api";
import CohortCount from "./CohortCount";
import DefinitionBuilder from "./DefinitionBuilder";
import { draftFromJudgments, judgmentsFromDraft, matchingPreset, type Draft } from "./definition";
import EvidencePanel from "./EvidencePanel";
import PatientList from "./PatientList";

// Long enough to skip intermediate slider values, short enough to feel live.
const COUNT_DELAY_MS = 80;

type Tab = "build" | "patients" | "agents";

export default function App() {
  const [tab, setTab] = useState<Tab>("build");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetCounts, setPresetCounts] = useState<Record<string, number>>({});
  const [presetsError, setPresetsError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [cohort, setCohort] = useState<Cohort | null>(null);
  const [loading, setLoading] = useState(false);
  const [cohortError, setCohortError] = useState<string | null>(null);
  const [selectedPatient, setSelectedPatient] = useState<string | null>(null);
  const [agentAnswer, setAgentAnswer] = useState<DecodedAnswer | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchPresets()
      .then(async (loaded) => {
        setPresets(loaded);
        setDraft(draftFromJudgments(loaded[0].judgments));
        const counted = await Promise.all(
          loaded.map(async (preset) => {
            const judgments = judgmentsFromDraft(draftFromJudgments(preset.judgments));
            const result = await fetchCohort(judgments!, controller.signal);
            return [preset.id, result.count] as const;
          }),
        );
        setPresetCounts(Object.fromEntries(counted));
      })
      .catch((error: Error) => {
        if (error.name !== "AbortError") {
          setPresetsError(error.message);
        }
      });
    return () => controller.abort();
  }, []);

  const judgments = useMemo(() => (draft ? judgmentsFromDraft(draft) : null), [draft]);

  useEffect(() => {
    if (!judgments) {
      setLoading(false);
      setCohortError(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      fetchCohort(judgments, controller.signal)
        .then((result) => {
          setCohort(result);
          setCohortError(null);
          setLoading(false);
        })
        .catch((error: Error) => {
          if (error.name !== "AbortError") {
            setCohortError(error.message);
            setLoading(false);
          }
        });
    }, COUNT_DELAY_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [judgments]);

  const activePreset = draft ? matchingPreset(draft, presets) : undefined;
  const definitionName = activePreset?.name ?? "Custom definition";
  const validCohort = judgments !== null && cohortError === null ? cohort : null;

  const tabs: { id: Tab; label: string }[] = [
    { id: "build", label: "Definition" },
    { id: "patients", label: validCohort ? `Patients (${validCohort.count})` : "Patients" },
    { id: "agents", label: "What AI assumed" },
  ];

  const counts = Object.values(presetCounts);

  const openInBuilder = (answer: DecodedAnswer) => {
    if (answer.judgments) {
      setDraft(draftFromJudgments(answer.judgments));
      setAgentAnswer(answer);
      setTab("build");
      window.scrollTo({ top: 0 });
    }
  };

  // The banner only claims these are the agent's settings while they still are.
  const showingAgentAnswer =
    agentAnswer?.judgments &&
    JSON.stringify(judgments) ===
      JSON.stringify(judgmentsFromDraft(draftFromJudgments(agentAnswer.judgments)));

  return (
    <div className="min-h-screen pb-16">
      <header className="bg-ink text-on-ink">
        <div className="mx-auto max-w-6xl px-4 pt-7 sm:px-6">
          <p className="text-xs font-medium tracking-widest text-amber uppercase">
            Cohort definition explorer
          </p>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-x-10 gap-y-3">
            <div className="max-w-2xl">
              <h1 className="font-serif text-3xl leading-tight font-semibold sm:text-4xl">
                How many diabetics are there?
              </h1>
              <p className="mt-2 text-on-ink-soft">
                It depends on what you decide counts. Change a decision and watch the answer move.
                All patients here are synthetic.
              </p>
            </div>
            {counts.length > 0 && (
              <p className="pb-1 text-sm text-on-ink-soft">
                <span className="block font-serif text-3xl font-semibold text-on-ink tabular-nums">
                  {Math.min(...counts)} to {Math.max(...counts)}
                </span>
                from the same {cohort?.population.toLocaleString() ?? ""} patients
              </p>
            )}
          </div>

          <div role="tablist" className="mt-5 flex gap-6">
            {tabs.map((item) => (
              <button
                key={item.id}
                role="tab"
                type="button"
                aria-selected={tab === item.id}
                onClick={() => setTab(item.id)}
                className="border-b-[3px] border-transparent pb-3 text-sm font-medium whitespace-nowrap text-on-ink-soft hover:text-on-ink aria-selected:border-amber aria-selected:text-on-ink"
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 sm:px-6">
        {presetsError && (
          <p role="alert" className="mt-8 rounded-lg bg-card p-4 text-sm">
            Couldn't reach the API: {presetsError}. Check that the backend is running.
          </p>
        )}

        {tab === "build" && showingAgentAnswer && (
          <div className="mt-6 flex flex-wrap items-center justify-between gap-x-6 gap-y-1 rounded-lg bg-accent-wash px-4 py-3 text-sm ring-1 ring-accent-soft">
            <p>
              These are the decisions behind the {agentAnswer.agent === "naive" ? "SQL" : "definition-aware"}{" "}
              agent's answer of <span className="font-semibold">{agentAnswer.number}</span>.
            </p>
            <button
              type="button"
              onClick={() => setTab("agents")}
              className="font-medium text-accent underline underline-offset-2"
            >
              Back to what AI assumed
            </button>
          </div>
        )}

        {tab === "build" && draft && (
          <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_23rem] lg:items-start">
            <div className="sticky top-0 z-10 -mx-4 bg-paper px-4 py-2 sm:mx-0 sm:px-0 lg:top-6 lg:order-last lg:bg-transparent lg:py-0">
              <CohortCount
                cohort={cohort}
                incomplete={judgments === null}
                loading={loading}
                error={cohortError}
                name={definitionName}
                presetCounts={counts}
                onViewPatients={() => setTab("patients")}
              />
            </div>
            <DefinitionBuilder
              presets={presets}
              presetCounts={presetCounts}
              activePreset={activePreset}
              draft={draft}
              onChange={setDraft}
              onSelectPreset={(preset) => setDraft(draftFromJudgments(preset.judgments))}
            />
          </div>
        )}

        {tab === "patients" && (
          <div className="mt-8">
            {validCohort && judgments ? (
              <>
                <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
                  <h2 className="font-serif text-2xl font-semibold">
                    {validCohort.count.toLocaleString()} patients
                  </h2>
                  <p className="text-sm text-ink-soft">
                    {definitionName}
                    {" · "}
                    <button
                      type="button"
                      onClick={() => setTab("build")}
                      className="font-medium text-accent underline underline-offset-2"
                    >
                      Change
                    </button>
                  </p>
                </div>
                <div className="mt-5 grid gap-6 lg:grid-cols-[21rem_minmax(0,1fr)] lg:items-start">
                  <PatientList
                    patients={validCohort.patients}
                    selectedId={selectedPatient}
                    loading={loading}
                    onSelect={setSelectedPatient}
                  />
                  {selectedPatient ? (
                    <EvidencePanel
                      patientId={selectedPatient}
                      judgments={judgments}
                      onClose={() => setSelectedPatient(null)}
                    />
                  ) : (
                    <div className="hidden rounded-xl border border-dashed border-line p-12 text-center lg:block">
                      <p className="font-serif text-xl">Why does this patient count?</p>
                      <p className="mt-2 text-sm text-ink-soft">
                        Select a patient to see the exact records behind them.
                      </p>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-ink-soft">
                There's no valid definition yet.{" "}
                <button
                  type="button"
                  onClick={() => setTab("build")}
                  className="font-medium text-accent underline underline-offset-2"
                >
                  Go back and build one.
                </button>
              </p>
            )}
          </div>
        )}

        {tab === "agents" && <AgentComparison onOpenInBuilder={openInBuilder} />}
      </main>
    </div>
  );
}
