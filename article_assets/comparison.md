# Agent comparison

Question: "How many diabetics are in this dataset?"

Backend: ollama. Model: `qwen2.5:7b-instruct`. Generated 2026-11-05 20:33 UTC.

| | Naive | Context-aware |
|---|---|---|
| Runs | 10 | 10 |
| Answered | 10 | 10 |
| Failed | 0 | 0 |
| Gave a count | 10 | 5 |
| Stated a definition (phrase rule) | 0 | 3 |
| Flagged ambiguity (phrase rule) | 0 | 7 |
| Reported numbers no tool returned | 0 | 0 |
| Mean tool calls | 1.0 | 1.3 |
| Input tokens | 10042 | 23995 |
| Output tokens | 782 | 4742 |

## Numbers returned

- Naive: 465 (x6), 474 (x2), 748 (x2)
- Context-aware: no single number (x5), 74 (x4), 41 (x1)

## What the numbers really counted

| Answer | Runs | What it counted | In the builder |
|---|---:|---|---|
| 465 | 6 | Every diabetes-related code except the diagnosis, from a case-sensitive search | Everything on except the diagnosis |
| 474 | 2 | All eight codes, including prediabetes | Definition 3 |
| 748 | 2 | Records, not patients | None, it isn't a valid count |

For 465 and 474, a test confirms the settings select exactly the same patients as the agent's SQL.

## Answer review

The table above comes from the script. This section comes from reading all 20 answers and queries.
That reading hasn't been independently checked.

| | Naive | Context-aware |
|---|---|---|
| Gave a valid patient count | 8 of 10 | 5 of 10 |
| Named the definition behind its count | 0 of 10 | 3 of 5 counts |
| Said the answer depends on the definition | 0 of 10 | 5 of 10 |
| Showed how the count changes across definitions | 0 of 10 | 0 of 10 |
| Invented a number | 0 of 10 | 0 of 10 |

**Where the context layer helped.** Every count it reported matched a real, stated cohort. It never
produced the row-count error, and half its runs said the question was ambiguous. The naive agent
never did, and always gave one confident number.

**Where it didn't help.**

- Half of its runs gave no count at all. The system prompt told it to show how the count changes
  across definitions, and no run did.
- No run called `list_presets`, so it never saw the presets' rationales.
- 2 of its 5 counts named no definition, which breaks its main rule.
- 8 tool calls failed validation, and it used about 2.4 times the input tokens.
- An earlier run of this setup, replaced after the scoring changed, had a context run invent four of
  its five numbers. This run had none, but small runs vary.

**Naive errors.** 748 is a count of rows reported as patients. 465 comes from a case-sensitive
match, and 474 is the same search done case-insensitively. Both include prediabetes, and no answer
said so.

**Limits.** One small local model, one seed, one question, and 10 runs each. These results say
little about what a stronger model would do, and they would likely differ on one. The phrase rules
are crude and the review isn't independent, so the transcripts are in `data/agent_runs.json` for
anyone to check.
