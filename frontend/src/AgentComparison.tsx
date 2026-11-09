import { useEffect, useState } from "react";

import {
  fetchAgentRuns,
  type AgentName,
  type AgentResults,
  type AgentRun,
  type AgentSummary,
  type DecodedAnswer,
} from "./api";
import LiveAsk from "./LiveAsk";
import Replay from "./Replay";
import { DecisionChips, QuestionBubble, StepView } from "./TranscriptParts";

const AGENTS: { name: AgentName; label: string; detail: string }[] = [
  { name: "naive", label: "SQL agent", detail: "One SQL tool and a schema description" },
  {
    name: "context",
    label: "Definition-aware agent",
    detail: "Definition tools, and told to name its definition",
  },
];

function NumberBars({ summary }: { summary: AgentSummary }) {
  return (
    <dl className="mt-4 space-y-3">
      {Object.entries(summary.headline_numbers).map(([number, count]) => (
        <div key={number} className="grid grid-cols-[6.5rem_1fr_1.5rem] items-center gap-3 text-sm">
          <dt
            className={
              /^\d+$/.test(number)
                ? "font-serif text-lg font-semibold tabular-nums"
                : "text-xs text-ink-soft"
            }
          >
            {number}
          </dt>
          <dd aria-hidden="true" className="h-2.5 rounded-full bg-paper">
            <div
              className="h-2.5 rounded-full bg-accent"
              style={{ width: `${(count / summary.runs) * 100}%` }}
            />
          </dd>
          <dd className="text-right text-ink-soft tabular-nums">
            <span className="sr-only">{number}: </span>
            {count}
            <span className="sr-only"> of {summary.runs} runs</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function comparisonRows(results: AgentResults): { label: string; naive: number; context: number }[] {
  const { naive, context } = results.summary;
  if (!results.review) {
    return [
      { label: "Gave a count", naive: naive.gave_a_count, context: context.gave_a_count },
      {
        label: "Stated a definition (phrase rule)",
        naive: naive.stated_definition,
        context: context.stated_definition,
      },
      {
        label: "Flagged ambiguity (phrase rule)",
        naive: naive.flagged_ambiguity,
        context: context.flagged_ambiguity,
      },
      {
        label: "Reported a number no tool returned",
        naive: naive.invented_numbers,
        context: context.invented_numbers,
      },
    ];
  }
  const counts = results.review.counts;
  return [
    {
      label: "Gave a valid patient count",
      naive: counts.naive.gave_valid_count,
      context: counts.context.gave_valid_count,
    },
    {
      label: "Named the definition behind its count",
      naive: counts.naive.named_definition,
      context: counts.context.named_definition,
    },
    {
      label: "Said the answer depends on the definition",
      naive: counts.naive.flagged_ambiguity,
      context: counts.context.flagged_ambiguity,
    },
    {
      label: "Showed the count across definitions",
      naive: counts.naive.compared_definitions,
      context: counts.context.compared_definitions,
    },
    {
      label: "Invented a number",
      naive: counts.naive.invented_numbers,
      context: counts.context.invented_numbers,
    },
  ];
}

function Transcript({ label, run, question }: { label: string; run: AgentRun; question: string }) {
  return (
    <article className="min-w-0 rounded-xl bg-card p-5 ring-1 ring-line">
      <h4 className="font-serif text-lg font-semibold">{label}</h4>
      <p className="text-xs text-ink-faint">Run {run.run}</p>
      <div className="mt-4 space-y-3">
        <QuestionBubble text={question} />
        {run.steps.map((step, index) => (
          <StepView key={index} step={step} />
        ))}
      </div>
    </article>
  );
}

function DecodedCard({
  answer,
  totalRuns,
  onOpen,
}: {
  answer: DecodedAnswer;
  totalRuns: number;
  onOpen: () => void;
}) {
  return (
    <article className="grid gap-4 rounded-xl bg-card p-5 ring-1 ring-line sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-6 sm:p-6">
      <div className="flex items-baseline gap-3 sm:block">
        <p className="font-serif text-5xl leading-none font-semibold tabular-nums">
          {answer.number}
        </p>
        <p className="text-xs text-ink-faint sm:mt-2">
          {answer.runs} of {totalRuns} runs
        </p>
      </div>
      <div className="min-w-0">
        <p className="font-serif text-lg leading-snug">"{answer.said}"</p>
        <p className="mt-3 text-sm leading-6">
          <span className="font-medium">What it really counted: </span>
          {answer.counted}
        </p>
        {answer.judgments && (
          <div className="mt-3">
            <DecisionChips judgments={answer.judgments} />
          </div>
        )}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <p className="text-sm text-ink-soft">{answer.disclosed}</p>
          {answer.judgments ? (
            <button
              type="button"
              onClick={onOpen}
              className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-on-ink transition-colors hover:bg-ink-raised"
            >
              Open in the builder
            </button>
          ) : (
            <p className="text-sm font-medium text-ink-soft">No definition gives this number</p>
          )}
        </div>
      </div>
    </article>
  );
}

function FullResults({ results }: { results: AgentResults }) {
  return (
    <>
      <div className="grid gap-5 md:grid-cols-2">
        {AGENTS.map((agent) => (
          <div key={agent.name} className="min-w-0 rounded-xl bg-card p-5 ring-1 ring-line">
            <h3 className="font-serif text-lg font-semibold">{agent.label}</h3>
            <p className="text-sm text-ink-faint">{agent.detail}</p>
            <NumberBars summary={results.summary[agent.name]} />
          </div>
        ))}
      </div>

      <h3 className="mt-10 font-serif text-xl font-semibold">
        {results.review ? "What an AI review of every answer found" : "What the scoring rules found"}
      </h3>
      <div className="mt-4 overflow-hidden rounded-xl bg-card ring-1 ring-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-ink-faint">
              <th scope="col" className="px-5 py-3 font-normal">
                Out of {results.summary.naive.runs} runs
              </th>
              <th scope="col" className="px-5 py-3 text-right font-normal">
                SQL
              </th>
              <th scope="col" className="px-5 py-3 text-right font-normal">
                Definition
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {comparisonRows(results).map((row) => (
              <tr key={row.label}>
                <th scope="row" className="px-5 py-3 text-left font-normal">
                  {row.label}
                </th>
                <td className="px-5 py-3 text-right font-serif text-lg font-semibold tabular-nums">
                  {row.naive}
                </td>
                <td className="px-5 py-3 text-right font-serif text-lg font-semibold tabular-nums">
                  {row.context}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {results.review && (
        <>
          <h3 className="mt-10 font-serif text-xl font-semibold">What these numbers leave out</h3>
          <ul className="mt-3 max-w-3xl list-disc space-y-2 pl-5 text-sm leading-6 text-ink-soft">
            {results.review.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </>
      )}

      <h3 className="mt-10 font-serif text-xl font-semibold">Example transcripts</h3>
      <p className="mt-1 text-sm text-ink-faint">
        The first answered run for each agent, chosen by that fixed rule.
      </p>
      <div className="mt-4 grid gap-5 md:grid-cols-2 md:items-start">
        {AGENTS.map((agent) => {
          const run = results.examples[agent.name];
          return run ? (
            <Transcript
              key={agent.name}
              label={agent.label}
              run={run}
              question={results.question}
            />
          ) : (
            <p key={agent.name} className="text-sm text-ink-soft">
              No answered run for the {agent.label.toLowerCase()}.
            </p>
          );
        })}
      </div>
    </>
  );
}

export default function AgentComparison({
  onOpenInBuilder,
}: {
  onOpenInBuilder: (answer: DecodedAnswer) => void;
}) {
  const [results, setResults] = useState<AgentResults | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAgentRuns()
      .then(setResults)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const decoded = results?.review?.decoded ?? [];
  const totalRuns = results?.summary.naive.runs ?? 0;
  const contextNoNumber = results?.summary.context.headline_numbers["no single number"] ?? 0;

  return (
    <section aria-label="Agent comparison" className="mt-8">
      <h2 className="font-serif text-3xl font-semibold">An AI gives a number. What did it decide?</h2>

      {error && (
        <p role="alert" className="mt-3 text-sm">
          Couldn't load the saved agent runs: {error}.
        </p>
      )}
      {results === null && (
        <p className="mt-3 text-sm text-ink-soft">
          No saved agent runs yet. The README explains how to generate them.
        </p>
      )}

      {results && decoded.length === 0 && (
        <>
          <p className="mt-2 max-w-2xl text-ink-soft">
            Two agents were asked "{results.question}" {totalRuns} times each. One model and a small
            sample, so read this as an example, not a benchmark.
          </p>
          <LiveAsk agents={AGENTS} onOpenInBuilder={onOpenInBuilder} />
          <Replay results={results} agents={AGENTS} onOpenInBuilder={onOpenInBuilder} />
          <div className="mt-10">
            <FullResults results={results} />
          </div>
        </>
      )}

      {results && decoded.length > 0 && (
        <>
          <p className="mt-2 max-w-2xl text-ink-soft">
            Two agents were asked "{results.question}" {totalRuns} times each. Behind most answers
            sits a set of decisions, the same ones you can make in the builder. Open any answer to
            see them.
          </p>

          <LiveAsk agents={AGENTS} onOpenInBuilder={onOpenInBuilder} />
          <Replay results={results} agents={AGENTS} onOpenInBuilder={onOpenInBuilder} />

          <h3 className="mt-12 font-serif text-2xl font-semibold">Every answer, decoded</h3>

          {AGENTS.map((agent) => (
            <div key={agent.name} className="mt-6">
              <h4 className="font-serif text-xl font-semibold">{agent.label}</h4>
              <p className="text-sm text-ink-faint">{agent.detail}</p>
              <div className="mt-4 space-y-4">
                {decoded
                  .filter((answer) => answer.agent === agent.name)
                  .map((answer) => (
                    <DecodedCard
                      key={answer.number}
                      answer={answer}
                      totalRuns={totalRuns}
                      onOpen={() => onOpenInBuilder(answer)}
                    />
                  ))}
                {agent.name === "context" && contextNoNumber > 0 && (
                  <p className="rounded-xl border border-dashed border-line p-5 text-sm leading-6 text-ink-soft">
                    <span className="font-medium text-ink">
                      {contextNoNumber} of {totalRuns} runs gave no number.
                    </span>{" "}
                    They asked what "diabetic" should mean. That's honest, but none showed how the
                    count changes across definitions, as they were told to.
                  </p>
                )}
              </div>
            </div>
          ))}

          <p className="mt-8 border-l-[3px] border-amber pl-4 text-sm leading-6 text-ink-soft">
            One small local model and {totalRuns} runs each, so read this as an example, not a
            benchmark. The decoding hasn't been independently checked.
          </p>

          <details className="mt-8">
            <summary className="cursor-pointer text-sm font-medium text-accent">
              Full results, caveats, and transcripts
            </summary>
            <div className="mt-6">
              <FullResults results={results} />
            </div>
          </details>
        </>
      )}

      {results && (
        <p className="mt-8 text-xs text-ink-faint">
          Saved results from {results.model} on {results.backend}, generated {results.generated_at}.
        </p>
      )}
    </section>
  );
}
