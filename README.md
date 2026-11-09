# Cohort Definition Explorer

How many diabetics are in a dataset? It depends on decisions nobody writes down. This app turns
those decisions into explicit judgments: build a definition, watch the count change live, and see
exactly which rows qualified each patient.

It follows up [Counting Diabetics](https://medium.com/@maheksota56/how-many-diabetics-are-in-this-dataset-somewhere-between-41-and-474-816cb283baed) and [its implementation] (https://github.com/mahek-sota/counting-diabetes), which counted the same synthetic
population five defensible ways and got answers from 41 to 474. It also compares a naive LLM agent
with a context-aware one on the question "How many diabetics are in this dataset?"

## Run the app

No API keys are needed. `make dev` never calls an LLM, and the agent comparison is read from saved
results.

You need [uv](https://docs.astral.sh/uv/) and Node 20+. The data is included: `data/extract/` holds
the rows the app reads, so the counts match the first article.

```bash
make install
make dev
```

Then open <http://localhost:5173>. The API runs on port 8010.

## Ask a model live (optional)

`make dev` shows saved results only. To add an "Ask it yourself" box, run:

```bash
make live
```

You type a question and an agent answers from the data. The app then recovers the patients behind
the agent's query, and compares them with every combination of settings the builder can express. If
one matches exactly, you can open it in the builder. It also flags answers that counted records
instead of patients, and answers that used no tool.

This needs Ollama running with the model pulled (see below), or a backend set in `.env`, plus the
full Synthea CSVs. It is meant for your own machine, so don't expose it publicly. Answers vary, and
the model can be wrong.

## Regenerate the agent results (optional)

This is only for re-running the comparison. It replaces `data/agent_runs.json` and
`article_assets/`, which are committed so the results are available without running anything. The
current results came from Ollama with `qwen2.5:7b-instruct`, as recorded in those files.

This needs the full Synthea CSVs in `data/synthea/csv/`, because the agents explore all the data and
the extract holds only diabetes rows. [data/README.md](data/README.md) explains how to get them.

Copy `.env.example` to `.env` and pick one option.

**Option 1: a local Ollama model.** Free, with no account.

```bash
ollama pull qwen2.5:7b-instruct
```

```bash
# .env
AGENT_BACKEND=ollama
# OLLAMA_MODEL=another-model-with-tool-support
```

**Option 2: the Anthropic API.** Needs a key with credit.

```bash
# .env
ANTHROPIC_API_KEY=your-key
```

Then run it:

```bash
make agents          # 10 runs per agent
make agents RUNS=1   # a quick test
```

If both options are configured, Anthropic is used unless `AGENT_BACKEND=ollama` is set. With neither
configured, the command explains these options and exits.

A new run drops the saved answer review and decoding, so the tab falls back to plain results. Read
the new answers before committing them.

## Results

### Definitions

The population has 1,153 synthetic patients.

| Definition | Patients | % of population |
|---|---|---:|
| 1. Exact SNOMED 44054006 | 74 | 6.4% |
| 2. Description mentions "type 2 diabetes" | 115 | 10.0% |
| 3. Description mentions "diabet" | 474 | 41.1% |
| 4. Any HbA1c at or above 6.5 | 41 | 3.6% |
| 5. Definition 2 or definition 4 | 142 | 12.3% |

Making the judgments explicit changed how these numbers read:

- **Definition 2 doesn't include the diagnosis.** That code's description reads "Diabetes mellitus
  type 2", so a search for "type 2 diabetes" finds four complication codes and misses the code
  itself. 37 of the 74 patients with SNOMED 44054006 are left out.
- **The 14-patient overlap between definitions 2 and 4 is mostly that wording gap.** With the
  diagnosis and all complications included, the coded cohort is 169 patients, and it contains all 41
  patients with a high HbA1c.
- **The real disagreement runs one way.** 128 of those 169 coded patients never reach 6.5, but no
  patient reaches 6.5 without a code.
- **Prediabetes drives the top of the range.** 305 of the 474 patients in definition 3 have only
  that code.

### Agents

Each agent ran 10 times on the same question, using the same local model.

| Out of 10 runs | Naive | Context-aware |
|---|---:|---:|
| Gave a valid patient count | 8 | 5 |
| Named the definition behind its count | 0 | 3 |
| Said the answer depends on the definition | 0 | 5 |
| Showed the count across definitions | 0 | 0 |
| Invented a number | 0 | 0 |

The naive agent gave one confident number every time and never said what it had counted. Most of
those numbers turn out to be hidden definitions, which the app's "What AI assumed" tab decodes:

| Answer | Runs | What it really counted |
|---|---:|---|
| 465 | 6 | Every diabetes-related code except the diagnosis, because a case-sensitive search skipped "Diabetes mellitus type 2" |
| 474 | 2 | All eight codes, including prediabetes |
| 748 | 2 | Records, not patients, so it isn't a valid count |

The tab also replays all 20 saved runs step by step. These are saved runs, not a live model.

For 465 and 474, a test confirms the builder's settings select exactly the same patients as the
agent's SQL. Opening 465 in the builder and switching on the diagnosis gives 474, so that one
accidental decision is visible in a single click.

**Where the context layer helped.** Every count it gave came from a real cohort, it avoided the
row-count error, and half of its runs said the question was ambiguous.

**Where it didn't help.**

- Half of its runs gave no count and asked the user instead.
- No run compared definitions, although its instructions said to, and none called `list_presets`.
- 2 of its 5 counts named no definition, which breaks its main rule.
- 8 tool calls failed validation, and it used about 2.4 times the input tokens.
- In an earlier run of this setup, one answer invented four of five numbers. The tools didn't prevent
  that, and a saved result can't rule it out.

The full comparison is in [article_assets/comparison.md](article_assets/comparison.md).

## Limitations

- **Synthetic data.** Synthea generates patients from disease models, so codes and labs agree more
  neatly than they would in real records. The one-way disagreement above may not hold elsewhere.
- **One population.** Counts come from a single pinned run. [data/README.md](data/README.md) covers
  why it can't be regenerated exactly.
- **One small model, one question, 10 runs each.** These results say little about a stronger model.
  Treat them as an example, not a benchmark, and expect variation between runs.
- **The context agent starts with an advantage.** Its presets were written after studying this data,
  and their rationales name the gaps. A real context layer would take work to build.
- **Scoring is imperfect.** Phrase rules are crude, and the answer review and decoding haven't been
  independently checked. The transcripts are in `data/agent_runs.json`.
- **Decoding is deliberately cautious.** It handles a plain `SELECT` over one count, and reports no
  match for anything more complex. Some settings select identical patients, so it shows the most
  inclusive one.
- **Only the Ollama path has produced results.** The Anthropic path has been tested with fakes, and
  has not completed a real run.
- **Definitions are simple.** Stop dates are ignored, one HbA1c result is enough, and medications
  aren't considered.
- **The frontend has no automated tests.** It was checked in a browser.

## Next steps

- Active-as-of-date definitions, so a resolved condition stops counting.
- Reviewer approval of definitions before they can be used.
- Real EHR data, where messier records would test these judgments.
- More runs across stronger models, and more than one question.

## Development

```bash
make test         # needs no key and no network
make lint
make data-check   # with the full CSVs: confirms they are the canonical population
make extract      # with the full CSVs: rebuilds data/extract/
```

Choices worth explaining are in [DECISIONS.md](DECISIONS.md).
