# Decisions

Non-obvious choices, recorded in the step where they were made.

## Step 1: Scaffold

- **The canonical data is a file set, not a seed.** The CSVs behind the first article reproduce
  every published count, but their run metadata records seed `1789766283574`, not 42. The same
  jar records `42` when given `-s 42`, and a pinned seed-42 run produced a different population
  (1,146 patients, counts 75/94/462/47/128, overlap 13). Since the goal is to reproduce the
  article's numbers, the original files are canonical and pinned by SHA-256. See `data/README.md`.
- **Only three CSVs are copied.** Those three are the only tables in scope, 151 MB of the 818 MB
  export.
- **The frontend is scaffolded now.** The plan has no separate frontend scaffold step, and the
  Makefile has to run both apps from the start.
- **`/health` exists before the real API.** It gives the frontend something to call, which proves
  the dev proxy works before step 3.
- **The frontend calls `/api/*` and Vite strips the prefix.** Backend routes stay as the plan names
  them, and there is no CORS setup to maintain.
- **The backend uses port 8010, not 8000.** Port 8000 is often taken by other local services. When
  it was, the proxy got a healthy-looking response from the wrong app. The proxy targets
  `127.0.0.1` directly because `localhost` can resolve to a different listener over IPv6.

## Step 2: Cohort logic

- **Two judgments were added to the planned four.** The text search for "type 2 diabetes"
  (definition 2) matches exactly four complication codes and not the diagnosis, whose description
  reads "Diabetes mellitus type 2". `include_complications` alone can't express that, so
  `include_diagnosis` and `include_other_complications` are explicit. The second covers two
  complications the text search misses, one of them spelled "type II".
- **Presets stay faithful to the first article.** Definition 2 keeps `include_diagnosis` off even
  though that probably wasn't the search's intent. Its count stays 115 and its rationale states the
  gap, so the comparison with the article still holds.
- **Code groups instead of stored text patterns.** A pattern hides what it matches, which is how
  this gap went unnoticed. A test requires the listed codes to equal the "diabet" codes in the data.
- **The 14-patient overlap is largely a result of definition 2's wording.** With the diagnosis and
  all complications, the coded cohort is 169 patients and contains all 41 high-HbA1c patients. A
  test keeps this fact visible.
- **`both` means either source.** This matches definition 5.
- **Inapplicable judgments are rejected.** A codes-only definition can't carry a threshold, so no
  definition appears to rely on evidence it ignores. The builder has to omit those fields.
- **Tables in memory, not views over the CSVs.** The explorer reruns queries on every toggle, and
  rescanning a 150 MB file each time would be too slow. Loading takes under a second.
- **`source_line` is the row identifier.** Condition and observation rows have no primary key. The
  CSV line number is stable for the pinned files and lets a reader find the exact row. It was
  checked against every row of all three files.
- **Everything is read as text, then dates are typed.** Type inference could turn SNOMED codes into
  integers, and `VALUE` mixes numbers with free text. `TRY_CAST` matches the first article's
  `to_numeric(errors="coerce")`.
- **Data tests skip when the CSVs are absent.** The data is gitignored, so a fresh clone can't run
  them. `make data-check` confirms the data is present and unchanged.

## Step 3: API

- **`GET /patients/{id}/evidence` takes the judgments as query parameters.** A patient's qualifying
  rows depend on the definition, so the route needs them. This keeps it a plain GET with no server
  session.
- **A patient outside the cohort returns 200 with no evidence.** That is a valid answer: nothing
  qualifies them under this definition. Only an unknown patient id returns 404.
- **`POST /cohort` returns ids and row counts, not the evidence.** The patient list needs only
  these, and the evidence panel fetches rows for one patient on click.
- **Each request gets its own DuckDB cursor.** FastAPI runs sync handlers on a thread pool, and a
  single shared connection isn't safe across threads.
- **`GET /agent-runs` returns `available: false` before step 4.** The app has to work without saved
  results, so a missing file isn't an error.

## Step 4: Agents

- **`make dev` never calls an LLM, and no key is needed to run it.** The agents are a separate optional
  command, and the app reads the committed results. A test confirms that importing the API loads
  neither the SDK nor the agent code. Live mode, added later, is a separate opt-in.
- **A thin wrapper replaces the earlier "no abstraction" rule.** `llm.py` translates requests and
  responses for Anthropic and Ollama, and all agent logic and tools are shared.
- **Ollama calls use the standard library.** It's one JSON endpoint, so a client package would add a
  dependency for very little.
- **`AGENT_BACKEND` is an added setting.** `OLLAMA_MODEL` needs a default, but "neither configured"
  must also be detectable, so the default can't apply on its own. Setting `AGENT_BACKEND=ollama`
  opts in without naming a model. Without it, a key selects Anthropic and `OLLAMA_MODEL` selects
  Ollama, with Anthropic winning if both are set.
- **The default local model was chosen before any results existed.** `qwen2.5:7b-instruct` is small
  and supports tools. It isn't swapped to improve either agent's result.
- **Ollama's context is set explicitly.** Its default is small and it truncates silently, which would
  cut prompts or tool results with no error.
- **Saved results are only replaced by a run that produced answers.** Configuration errors, and runs
  where nothing answered, stop before saving.
- **Both agents get the same setup.** Same backend, model, turn limit, question, data, and a fresh
  conversation per run. A test checks the question and prompts are handled identically.
- **The naive prompt is an accurate schema and nothing else.** It is generated from the database, so
  it can't drift, and a test confirms it has no diabetes hints. It isn't told to be brief, so the
  agent is free to explain itself or flag ambiguity.
- **The naive tool is limited only for safety.** One SELECT at a time, no file access, 200 rows with
  a `truncated` flag. Errors go back to the model so it can correct its query.
- **The context agent's advantage comes from the tools, and that's disclosed.** Its preset rationales
  name the gaps found in step 2, so it starts with knowledge the naive agent has to discover.
- **Scoring is split between a model and fixed rules.** A model call extracts the numbers, because
  regex can't tell a headline number from one mentioned in passing, and each number is checked
  against the text. "Stated a definition" and "flagged ambiguity" are fixed phrase rules. A small
  local model got both wrong in testing, even when made to quote its evidence. The rules are blind
  to the agent, identical on both backends, and save what they matched. They are crude, so every
  saved answer is also read and disagreements are reported.
- **Reported numbers are checked against tool results.** A count no tool returned is flagged as
  invented. In one run the context agent made up four of five numbers, and neither the model scorer
  nor the phrase rules noticed.
- **The answer review sits in the saved results, and `make agents` drops it.** It describes one
  specific run, so regenerating has to remove it. Review the new answers before committing them.
- **The review is labelled as unverified.** It hasn't been independently checked, and it says so
  wherever it appears.
- **Example transcripts are chosen by a fixed rule:** the lowest-numbered answered run for each agent.
- **Failed runs are kept and counted.** They aren't retried, beyond the SDK's normal retries on
  Anthropic, so the saved runs are the runs that happened.
- **No server-side model fallback.** A refused request is recorded as a failure, because a fallback
  would quietly mix models in a single-model comparison.
- **A stub client in tests isn't a provider abstraction.** `run_once` takes the Anthropic client as
  an argument, so tests can script responses. There is no interface in between.

## Step 5: Definition builder

- **The UI keeps a draft separate from the judgments it sends.** The API rejects inapplicable
  judgments, but switching from codes to labs and back shouldn't erase the user's choices. The draft
  keeps them, and `judgmentsFromDraft` sends only what applies.
- **"both" is labelled "Either" in the UI.** It means either source qualifies a patient, and "Both"
  would read as requiring both.
- **No count is shown when there isn't a valid one.** A dimmed old number beside a definition's name
  still pairs that definition with the wrong count, so the card shows a dash instead.
- **The preset highlight follows the judgments, not the last click.** Changing any control turns the
  title into "Custom definition" and removes the rationale, so a changed definition can't keep
  claiming a preset's name.
- **Slider range is 5.0 to 10.0.** It covers the prediabetes range through the data's maximum of 9.7.
- **No frontend test runner.** The plan's stack doesn't include one, so this step was checked by
  driving the page in a real browser.

## Step 6: Patient list and evidence panel

- **The evidence panel follows the definition.** It refetches when the judgments change, and says so
  when the selected patient no longer qualifies. Closing it silently would hide the most useful
  thing the app can show: the same patient counted under one definition and not another.
- **Results are keyed by patient and definition.** Rows from an earlier request can't appear under
  the current selection, even for a moment.
- **Paging happens in the browser, 20 per page.** `POST /cohort` already returns every id, and the
  largest preset is 474 patients, so server paging would add code without a benefit.
- **Short ids in the list, the full id in the panel.** Synthea's patient names are synthetic but look
  like real people's, and the id is what ties a patient to the CSV.
- **The panel scrolls to its top after its rows load.** Scrolling earlier fails on phones, because
  the page isn't tall enough until the rows arrive. It scrolls only when the patient changes, so
  moving a toggle never shifts the page.

## Data for a fresh clone

- **A small extract is committed so the app runs from a clone.** The full CSVs can't go in the repo,
  since `observations.csv` is over GitHub's file limit, and regenerating gives a different
  population. `data/extract/` holds only the rows the app reads, so counts match the article.
- **The full CSVs are used when present.** The extract is the fallback, not a separate mode.
- **The extract keeps each row's line number in the full CSV.** Evidence still points at the source
  file, and a test checks that the extract and the full data produce identical evidence.
- **`patients` keeps only `Id`.** The app reads nothing else, so names and addresses stay out of the
  repo, even though they are synthetic.
- **The agents refuse the extract.** It holds only diabetes rows, which would hand the naive agent
  the answer's shape. The fallback is skipped in code rather than left to the docs.

## Step 7: Agent comparison

- **The answer review is shown when present, and the script's numbers otherwise.** A regenerated run
  has no review, so the table then labels its rows as phrase rules instead of implying someone
  checked them.
- **The caveats sit beside the numbers.** The distribution alone makes 748 look like a real answer,
  so the review notes sit directly under the table, and the page names the backend, model, and run
  count.
- **The context example stays run 1, though it gives no count.** Transcripts are picked by a fixed
  rule, and half of the context runs behaved this way, so it's a fair sample.
- **Plain HTML bars, no chart library.** Each bar shows one number's share of runs, with every value
  labelled directly.

## UI pass

- **Three tabs replace one long page.** It ran to nearly five screens, and the count scrolled away
  once a patient was open.
- **Preset buttons show their counts.** The spread from 41 to 474 is the point of the project, and
  it was hidden behind five clicks.
- **Inapplicable settings are hidden, not greyed out.** A lab-only definition now shows no code
  choices.
- **Plain language first, source detail second.** Visitors see "Diagnosis records" and "HbA1c
  result". Dates and CSV line numbers stay visible in smaller text, because traceability is the
  purpose of the panel.
- **The count stays pinned on phones.** This removes the earlier limitation where it scrolled away
  while changing settings.
- **Review notes are collapsed but labelled "What these numbers leave out".** They are still one
  click from the table, so collapsing them doesn't hide the caveats.
- **The visual design is editorial, not a dashboard template.** A warm paper background, deep ink
  header, and a serif for headlines and key numbers suit a project tied to an article. Fonts are
  bundled with the app, so nothing loads from a third party.
- **Preset rows double as a bar chart.** Each bar is scaled to the largest count, so the spread reads
  as a picture before anyone clicks.

## Decoding the agents' answers

- **The agents tab shows what each answer decided, not only that it differed.** On its own the
  section was a static report that didn't connect to the app. Each answer now opens in the builder,
  which ties the two halves of the project together.
- **A match on the number isn't proof.** Two definitions can share a count by chance, so tests compare
  the builder's patient set with the patients returned by the agent's own SQL.
- **The decoding is stored with the answer review.** It's specific to one run, so `make agents` drops
  it and the tab falls back to plain results.
- **The agent is called "SQL agent" in the app.** "Naive" reads as a judgment to a visitor. The code
  and data keep `naive`.
- **The banner disappears once a setting changes.** It only claims "these are the agent's decisions"
  while that is true.

## Replay of saved runs

- **Replay is labelled as saved runs.** It looks like a chat, so the label states it isn't a live
  model. That keeps it honest for anyone who hasn't read the README.
- **Each run's button shows the number it returned.** All 20 runs are available, including the
  failures and non-answers, so the replay can't become a curated highlight reel.
- **Replay respects the reduced-motion setting.** Those visitors see the finished run at once.

## Live mode with decoding

- **The rule changed from "never calls an LLM" to "never requires one".** Live questions were added
  at the user's request, and `make dev` behaves exactly as before.
- **Live mode needs an explicit switch, not just a configured backend.** A stray API key must not
  quietly open a paid endpoint, so only `make live` sets `LIVE_MODE=on`.
- **Live mode needs the full CSVs.** The extract holds only diabetes rows, which would rig what the
  SQL agent finds.
- **Decoding compares patients, not counts.** It reruns the agent's query so it returns patients, and
  looks for a definition with exactly that set among all 831 the builder can express.
- **Unsupported queries report no match instead of guessing.** Rewriting SQL safely is hard, so it
  only handles the plain shape agents usually write.
- **The most inclusive setting wins a tie.** Some settings select identical patients, because one
  group can sit inside another, and the broadest describes what a search really covered.
- **An empty result never matches.** A query that found nobody isn't the same decision as a definition
  that happens to select nobody.
- **Live answers aren't scored.** Scoring would double the wait, and the decoding is the useful part.
