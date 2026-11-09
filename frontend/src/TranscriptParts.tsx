import type { Judgments, TranscriptStep } from "./api";

const LONG_RESULT = 400;

/** Shows a single-value SQL result as that value, instead of raw JSON. */
function readableResult(result: string): string {
  try {
    const parsed = JSON.parse(result);
    if (parsed.rows?.length === 1 && parsed.rows[0].length === 1) {
      return String(parsed.rows[0][0]);
    }
  } catch {
    // Not JSON, so show it as it is.
  }
  return result;
}

function readableInput(input: unknown): string {
  const query = (input as { query?: unknown } | undefined)?.query;
  return typeof query === "string" ? query : JSON.stringify(input, null, 2);
}

function ToolCallStep({ step }: { step: TranscriptStep }) {
  const result = readableResult(step.result ?? "");
  return (
    <div className="rounded-lg bg-ink p-3 text-xs text-on-ink">
      <p className="font-medium text-amber">
        {step.name}
        {step.is_error && <span className="font-normal text-on-ink-soft"> failed</span>}
      </p>
      <pre className="mt-2 font-mono break-words whitespace-pre-wrap">
        {readableInput(step.input)}
      </pre>
      {result.length > LONG_RESULT ? (
        <details className="mt-2 border-t border-ink-raised pt-2">
          <summary className="cursor-pointer text-on-ink-soft">Show the full result</summary>
          <pre className="mt-1 font-mono break-words whitespace-pre-wrap">{result}</pre>
        </details>
      ) : (
        <pre className="mt-2 border-t border-ink-raised pt-2 font-mono break-words whitespace-pre-wrap">
          → {result}
        </pre>
      )}
    </div>
  );
}

export function QuestionBubble({ text }: { text: string }) {
  return (
    <p className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-br-sm bg-paper px-4 py-2 text-sm">
      {text}
    </p>
  );
}

export function StepView({ step }: { step: TranscriptStep }) {
  return step.type === "text" ? (
    <p className="w-fit max-w-[92%] rounded-2xl rounded-bl-sm bg-accent-wash px-4 py-2 text-sm leading-6 break-words whitespace-pre-wrap">
      {step.text}
    </p>
  ) : (
    <ToolCallStep step={step} />
  );
}

function decisions(judgments: Judgments): { label: string; included: boolean }[] {
  const codes = [
    { label: "Diagnosis", included: Boolean(judgments.include_diagnosis) },
    { label: "Type 2 complications", included: Boolean(judgments.include_complications) },
    { label: "Other complications", included: Boolean(judgments.include_other_complications) },
    { label: "Prediabetes", included: Boolean(judgments.include_prediabetes) },
  ];
  const lab = { label: `HbA1c at or above ${judgments.hba1c_threshold}%`, included: true };
  if (judgments.evidence === "labs") {
    return [{ label: "Diagnosis records", included: false }, lab];
  }
  return judgments.evidence === "both" ? [...codes, lab] : codes;
}

export function DecisionChips({ judgments }: { judgments: Judgments }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {decisions(judgments).map((item) => (
        <li
          key={item.label}
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
            item.included ? "bg-accent-soft text-ink" : "bg-paper text-ink-faint line-through"
          }`}
        >
          <span className="sr-only">{item.included ? "Included: " : "Left out: "}</span>
          {item.label}
        </li>
      ))}
    </ul>
  );
}
