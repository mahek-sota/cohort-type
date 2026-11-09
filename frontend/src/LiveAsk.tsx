import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  askLive,
  fetchLiveStatus,
  type AgentName,
  type DecodedAnswer,
  type LiveAnswer,
  type LiveDecoding,
  type LiveStatus,
} from "./api";
import { DecisionChips, QuestionBubble, StepView } from "./TranscriptParts";

const SUGGESTIONS = [
  "How many diabetics are in this dataset?",
  "How many patients have type 2 diabetes?",
  "What share of patients have high blood sugar?",
];

interface Props {
  agents: { name: AgentName; label: string }[];
  onOpenInBuilder: (answer: DecodedAnswer) => void;
}

function decodingMessage(decoding: LiveDecoding, usedTools: boolean): string {
  switch (decoding.status) {
    case "match":
      return `These settings select exactly the ${decoding.patients} patients behind this answer.`;
    case "rows_not_patients":
      return `This counted ${decoding.reported} records, which are ${decoding.patients} patients. Its answer is not a patient count.`;
    case "no_match":
      if (decoding.patients === 0) {
        return "Its query matched no patients at all. That says more about the search than the data.";
      }
      return "No combination in the builder selects these patients, or the query is too complex to check.";
    case "no_count":
      return usedTools
        ? "This answer doesn't report a count from its last query, so there's nothing to decode."
        : "No tool ran, so any number in this answer didn't come from the data.";
  }
}

export default function LiveAsk({ agents, onOpenInBuilder }: Props) {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [agent, setAgent] = useState<AgentName>(agents[0].name);
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const [answer, setAnswer] = useState<LiveAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchLiveStatus()
      .then(setStatus)
      .catch(() => setStatus({ enabled: false, backend: null, model: null }));
    return () => request.current?.abort();
  }, []);

  if (!status?.enabled) {
    return null;
  }

  const ask = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) {
      return;
    }
    const controller = new AbortController();
    request.current = controller;
    setAsked(trimmed);
    setAnswer(null);
    setError(null);
    setLoading(true);
    askLive(trimmed, agent, controller.signal)
      .then(setAnswer)
      .catch((reason: Error) => {
        if (reason.name !== "AbortError") {
          setError(reason.message);
        }
      })
      .finally(() => setLoading(false));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    ask(question);
  };

  const decoding = answer?.decoding;

  return (
    <div className="mt-8 rounded-xl bg-ink p-5 text-on-ink sm:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
        <h3 className="font-serif text-2xl font-semibold">Ask it yourself</h3>
        <p className="text-xs font-medium text-amber">Live: {status.model}</p>
      </div>
      <p className="mt-1 text-sm text-on-ink-soft">
        A real model answers from the data. Answers vary, and it can be wrong.
      </p>

      <div className="mt-4 inline-flex max-w-full rounded-lg bg-ink-raised p-1">
        {agents.map((item) => (
          <button
            key={item.name}
            type="button"
            aria-pressed={item.name === agent}
            disabled={loading}
            onClick={() => setAgent(item.name)}
            className="rounded-md px-3 py-1.5 text-sm font-medium whitespace-nowrap text-on-ink-soft transition-colors aria-pressed:bg-on-ink aria-pressed:text-ink"
          >
            {item.label}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input
          type="text"
          value={question}
          maxLength={300}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this dataset"
          aria-label="Your question"
          className="min-w-0 flex-1 rounded-lg bg-on-ink px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-2 focus:outline-amber"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="shrink-0 rounded-lg bg-amber px-4 py-2 text-sm font-semibold text-ink transition-colors hover:bg-[#f6c260] disabled:opacity-50"
        >
          {loading ? "Asking" : "Ask"}
        </button>
      </form>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((text) => (
          <button
            key={text}
            type="button"
            disabled={loading}
            onClick={() => {
              setQuestion(text);
              ask(text);
            }}
            className="rounded-full px-3 py-1 text-xs text-on-ink-soft ring-1 ring-ink-raised transition-colors hover:text-on-ink hover:ring-on-ink-soft disabled:opacity-50"
          >
            {text}
          </button>
        ))}
      </div>

      {asked && (
        <div className="mt-5 space-y-3 rounded-lg bg-card p-4 text-ink" aria-live="polite">
          <QuestionBubble text={asked} />
          {answer?.steps.map((step, index) => (
            <StepView key={index} step={step} />
          ))}
          {loading && (
            <p className="flex items-center gap-2 px-2 py-1 text-sm text-ink-soft">
              <span className="size-1.5 animate-pulse rounded-full bg-ink-faint" />
              Thinking. A local model can take a little while.
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm">
              Couldn't get an answer: {error}
            </p>
          )}
          {answer?.error && (
            <p role="alert" className="text-sm">
              This run failed: {answer.error}
            </p>
          )}
          {decoding && (
            <div className="border-t border-line pt-3 text-sm leading-6">
              <p className="font-medium">What it really counted</p>
              <p className="text-ink-soft">{decodingMessage(decoding, answer.used_tools)}</p>
              {decoding.judgments && (
                <>
                  <div className="mt-2">
                    <DecisionChips judgments={decoding.judgments} />
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      onOpenInBuilder({
                        agent,
                        number: decoding.patients ?? 0,
                        runs: 1,
                        said: answer.answer ?? "",
                        counted: "",
                        disclosed: "",
                        judgments: decoding.judgments,
                      })
                    }
                    className="mt-3 rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-on-ink transition-colors hover:bg-ink-raised"
                  >
                    Open in the builder
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
