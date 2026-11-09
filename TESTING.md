# Sample prompts for live mode

Prompts for checking the "Ask it yourself" box. Start the app with `make live` (see the
[README](README.md#ask-a-model-live-optional)), open **What AI assumed**, and try each prompt on both
the **SQL agent** and the **Definition-aware agent**.

Answers come from a model and vary between runs, so treat the expected results below as what to
look for, not exact outputs.

## Should decode cleanly

Each of these maps onto one definition the builder can express, so the app should find an exact
match.

| Prompt | What it tests |
| --- | --- |
| How many patients have a diagnosis of type 2 diabetes? | The narrowest code-only definition. |
| How many patients have an HbA1c of 6.5% or higher? | Labs only, at the standard threshold. |
| Count patients with a type 2 diabetes diagnosis OR an HbA1c ≥ 6.5. | Codes and labs together. |
| How many patients have type 2 diabetes or any diabetic complication? | Whether the agent finds codes like "Disorder of kidney due to diabetes", which a search for "type 2 diabetes" misses. |
| Include prediabetes too. How many patients is that? | A broad definition, so the count should land near the top of the 41 to 474 range. |

## Threshold sensitivity

| Prompt | What it tests |
| --- | --- |
| How many patients have an HbA1c above 7? | Try 5.7 and 8 as well and watch the count move. |

## Traps the app should flag

| Prompt | Expected |
| --- | --- |
| How many diabetes records are there? | Invites counting rows instead of patients. The app should flag it. |
| How many diabetes diagnoses are in the conditions table? | The same trap, phrased more subtly. |
| Roughly what percentage of people in the US have diabetes? | Invites an answer with no tool use. The app should flag it. |

## Ambiguity

| Prompt | What it tests |
| --- | --- |
| How many diabetics are in this dataset? | The baseline question. The definition-aware agent often asks a follow-up instead of answering. |
| Just give me your best single number for diabetics, don't ask me questions. | Forces a choice, so you can see which definition the agent picks. |
| How many patients have type 1 diabetes? | The data has only type 2 codes. A good answer says so instead of producing a number. |

## Outside the builder

The builder can't express these, so the app should report no exact match.

| Prompt | What it tests |
| --- | --- |
| How many living patients have type 2 diabetes? | Filters on whether patients are alive. |
| How many patients were diagnosed with diabetes after 2015? | Filters on diagnosis date. |

The most useful checks are the traps and the type 1 question. They test whether the app catches bad
answers, not just whether it decodes good ones.
