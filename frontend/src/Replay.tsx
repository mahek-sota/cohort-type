import { useEffect, useState } from "react";

import type { AgentName, AgentResults, AgentRun, DecodedAnswer } from "./api";
import { QuestionBubble, StepView } from "./TranscriptParts";

const STEP_DELAY_MS = 900;

interface Props {
  results: AgentResults;
  agents: { name: AgentName; label: string }[];
  onOpenInBuilder: (answer: DecodedAnswer) => void;
}

function runLabel(run: AgentRun): string {
  return run.score?.headline_number?.toString() ?? "no number";
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function Replay({ results, agents, onOpenInBuilder }: Props) {
  const [agent, setAgent] = useState<AgentName>(agents[0].name);
  const [runNumber, setRunNumber] = useState(1);
  const [shown, setShown] = useState(0);
  const [playing, setPlaying] = useState(false);

  const runs = results.runs.filter((item) => item.agent === agent);
  const run = runs.find((item) => item.run === runNumber) ?? runs[0];
  const total = run.steps.length;
  const finished = shown >= total;

  useEffect(() => {
    if (!playing) {
      return;
    }
    if (finished) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(() => setShown((count) => count + 1), STEP_DELAY_MS);
    return () => clearTimeout(timer);
  }, [playing, shown, finished]);

  const play = (nextAgent: AgentName, nextRun: number) => {
    setAgent(nextAgent);
    setRunNumber(nextRun);
    if (prefersReducedMotion()) {
      setShown(Number.MAX_SAFE_INTEGER);
      setPlaying(false);
    } else {
      setShown(0);
      setPlaying(true);
    }
  };

  const headline = run.score?.headline_number ?? null;
  const decoded = results.review?.decoded?.find(
    (answer) => answer.agent === agent && answer.number === headline,
  );

  return (
    <div className="mt-8 rounded-xl bg-card p-5 ring-1 ring-line sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="font-serif text-2xl font-semibold">Watch a run</h3>
        <p className="text-xs font-medium text-ink-faint">
          A replay of a saved run, not a live model
        </p>
      </div>

      <div className="mt-4 inline-flex max-w-full rounded-lg bg-paper p-1">
        {agents.map((item) => (
          <button
            key={item.name}
            type="button"
            aria-pressed={item.name === agent}
            onClick={() => play(item.name, 1)}
            className="rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap text-ink-soft transition-colors aria-pressed:bg-ink aria-pressed:text-on-ink"
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {runs.map((item) => (
          <button
            key={item.run}
            type="button"
            aria-pressed={item.run === run.run}
            aria-label={`Run ${item.run}, answer: ${runLabel(item)}`}
            onClick={() => play(agent, item.run)}
            className="rounded-full px-3 py-1 text-xs font-medium tabular-nums ring-1 ring-line transition-colors hover:ring-ink-faint aria-pressed:bg-accent aria-pressed:text-white aria-pressed:ring-accent"
          >
            {runLabel(item)}
          </button>
        ))}
      </div>

      <div className="mt-5 space-y-3" aria-live="polite">
        <QuestionBubble text={results.question} />
        {run.steps.slice(0, shown).map((step, index) => (
          <div key={`${agent}-${run.run}-${index}`} className="motion-safe:animate-[rise_250ms_ease-out]">
            <StepView step={step} />
          </div>
        ))}
        {playing && !finished && (
          <p aria-hidden="true" className="flex gap-1 px-2 py-2">
            {[0, 150, 300].map((delay) => (
              <span
                key={delay}
                className="size-1.5 animate-pulse rounded-full bg-ink-faint"
                style={{ animationDelay: `${delay}ms` }}
              />
            ))}
          </p>
        )}
      </div>

      {finished && (
        <div className="mt-4 border-t border-line pt-4 text-sm leading-6 motion-safe:animate-[rise_250ms_ease-out]">
          {decoded ? (
            <>
              <p>
                <span className="font-medium">What it really counted: </span>
                {decoded.counted}
              </p>
              {decoded.judgments && (
                <button
                  type="button"
                  onClick={() => onOpenInBuilder(decoded)}
                  className="mt-3 rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-on-ink transition-colors hover:bg-ink-raised"
                >
                  Open in the builder
                </button>
              )}
            </>
          ) : (
            <p className="text-ink-soft">
              {headline === null
                ? "This run gave no number, so there's nothing to decode."
                : "This answer hasn't been decoded."}
            </p>
          )}
        </div>
      )}

      {!playing && !finished && (
        <button
          type="button"
          onClick={() => play(agent, run.run)}
          className="mt-4 rounded-lg bg-amber px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-[#f6c260]"
        >
          Play this run
        </button>
      )}
      {playing && (
        <button
          type="button"
          onClick={() => {
            setPlaying(false);
            setShown(Number.MAX_SAFE_INTEGER);
          }}
          className="mt-3 text-sm font-medium text-accent underline underline-offset-2"
        >
          Skip to the end
        </button>
      )}
    </div>
  );
}
