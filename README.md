# HR Candidate-Screening Agent

*Русская версия: [README.ru.md](README.ru.md)*

## What this project does

A deterministic screening engine for three job openings (BA, Fullstack,
UX/UI) with full decision traceability: why a candidate was taken /
reserved / rejected, against which exact criterion, backed by a grounded
(verifiable) quote from the résumé — not "the model said so," but the exact
line in the résumé and its position in the text.

The decision (`берём` / `в резерв` / `отказ` — take / reserve / reject) is
made by a deterministic rule over structured data (`domain/decision.py`),
not by an LLM — that module never sees raw résumé text and never calls an
LLM. The LLM is involved in exactly two places: picking the matching vacancy
from the résumé text (`classify_role`) and extracting fields against a
fixed schema (`extract_candidate`) — both in `extractors/`.

The working pipeline is `screen.py`: one résumé in, a live LLM call, the
deterministic engine, an explanation out (see Quickstart below). The repo
also includes demo and test infrastructure built around a hand-labelled
set of 10 résumés (`report.py`, `fixtures/candidates_golden.json`); it is
not used by `screen.py` or the live path — see "The golden set" below.

The architectural principle and its target state (what's already built vs.
still planned) are in `TECH_ARCHITECTURE.en.md` / `TECH_ARCHITECTURE.ru.md`.
This file covers how to run the project, what assumptions it makes, and
what's still open.

---

## Status and limitations

- 37 `pytest` tests, all passing: regression against the hand-labelled set
  of 10 résumés (see "The golden set" below for what that does and doesn't
  establish), stop factors as a veto, regression tests for two real bugs,
  and acceptance tests for evidence-grounding (quote grounding, relevance
  judge, empty-evidence penalties).
- Evidence-grounding (locating quotes in the source text, type checking) is
  built and tested. The relevance judge ("does this quote actually support
  this criterion?") is implemented but runs only behind a flag
  (`--judge-relevance`), not in the default path. Cross-field evidence
  consistency checking is not implemented. See `TECH_ARCHITECTURE.*.md` for
  the full target-architecture breakdown.
- Four LLM providers are implemented and live-tested: Ollama (self-hosted
  default), Anthropic, Groq, Gemini — behind one interface, no SDKs, only
  `urllib`/`curl`.
- The rendered report (`.explain.md`) loses some detail present in the
  JSON — see "Status vocabulary and lossy rendering" under Known Issues
  before relying on `.explain.md` labels alone.

---

## Requirements

- **Python 3.9+** — the engine uses only the standard library.
- **pytest** — required only for `tests/`; the engine runs without it.
- **Ollama**, installed and running, for the local provider.
- An API key (Anthropic and/or Groq and/or Gemini) for the cloud providers;
  none is required — `--provider ollama` works fully offline.
- No provider SDK is required (`anthropic`, `google-generativeai`, `groq`,
  etc.) — all four providers are implemented directly over HTTP
  (`extractors/providers.py`).

---

## Conda environment setup

```bash
conda env create -f environment.yml
conda activate screening-agent
```

`environment.yml` declares two dependencies: Python 3.9+ and pytest.
Pytest is required only to run `tests/`; the engine itself uses nothing
outside the standard library.

Without conda — a plain `python3` on PATH (3.9+) works; install `pytest`
separately (`pip install pytest`) if you want to run the tests.

---

## Quickstart: cloud providers

Put keys in `.env` at the repo root (only the providers you plan to use are
needed):

```
ANTHROPIC_API_KEY=...
GROQ_API_KEY=...
GEMINI_API_KEY=...
```

`.env` is loaded automatically (`extractors/providers.py`) and is in
`.gitignore` — never committed.

One live résumé run through a cloud provider:

```bash
python3 screen.py fixtures/resumes/R02.txt --provider gemini
python3 screen.py fixtures/resumes/R02.txt --provider anthropic
python3 screen.py fixtures/resumes/R02.txt --provider groq
```

Full cycle: the LLM picks the matching vacancy → the LLM extracts fields
against the role's schema → the deterministic engine decides → the report is
written to `screening_results/R02.evidence.json` / `R02.explain.md`.

Optional — the evidence relevance judge (one extra LLM call per non-empty
quote, off by default — see Known Issues):

```bash
python3 screen.py fixtures/resumes/R02.txt --provider gemini --judge-relevance
```

---

## Local: Ollama run

```bash
ollama serve                              # if not already running as a service
ollama pull phi4-mini:3.8b-q4_K_M         # default model
python3 screen.py fixtures/resumes/R02.txt --provider ollama
```

`phi4-mini:3.8b-q4_K_M` is the default model, not `qwen2.5:3b` — a
head-to-head comparison via `eval_extraction.py` on the 10 labelled résumés
showed higher decision-level agreement and fewer hallucinated stop factors
(details under Known Issues). No API key is needed; candidate data never
leaves your infrastructure.

---

## Test commands

```bash
python3 -m pytest tests/ -v
```

37 tests, no network, no live LLM calls (synthetic and golden data, with
mocked model calls where needed):

- `tests/test_decisions.py` — the golden decision table across all 10
  candidates;
- `tests/test_stop_factors.py` — stop factors as a veto, not just another
  must-have;
- `tests/test_missing_evidence.py` — regression tests for two real bugs
  (`None` instead of `[]`/`0` from a live model; `unclear` on the wrong
  profession, which used to be incorrectly counted as passing);
- `tests/test_validation.py` — evidence-grounding acceptance tests: offsets
  ground exactly (`cv_text[start:end] == text`, checked across all 46
  evidence spans in the golden set), a fabricated quote is caught and
  downgrades to `unclear`, escalation never fires without a genuinely
  different model, confidence can't rescue empty evidence, and the
  relevance judge downgrades real cases labelled in the golden data (not
  synthetic ones).

The deterministic golden run (`python3 report.py`, see Outputs below) is a
second, slower verification path: 10 decisions you can read directly in
`report.md`.

---

## Outputs

**`python3 report.py`** — batch run over the 10 golden candidates, no LLM:

- `report.md` — summary table across all 10;
- `screening_results/<id>.evidence.json` — the full per-candidate artifact
  (extraction → criteria → decision → validation, one JSON);
- `screening_results/<id>.explain.md` — the same artifact rendered into a
  readable form (rendered from this JSON, not from separate live objects,
  so `.md` and `.json` can't drift — though the render omits some detail
  present in the JSON; see "Status vocabulary and lossy rendering");
- `evidence_full_matrix.json` — cross-run of all 10 candidates against all 3
  roles (see "Decision rules and assumptions" → "Cross-role check").

**`python3 screen.py <resume.txt> --provider ...`** — one live run, writes
the same `screening_results/<id>.evidence.json` / `<id>.explain.md` (shares
the renderer with `report.py`).

**`python3 extract.py` / `python3 eval_extraction.py`** — Stage-1 over all
résumés at once and comparison against the golden set (field/decision
agreement) — for comparing providers and models, not for everyday use.

---

## The golden set

`fixtures/candidates_golden.json` is a hand-labelled dataset, not an answer
key supplied with the assignment. The assignment states this directly:
*"There is no 'correct list' reference in this file: you define the
criteria"* — no correct list exists, from the assignment or elsewhere.

The file holds the 10 résumés from `02_вакансии_и_резюме.md`, labelled into
the same structured-field schema the live extractor uses (`FIELD_SPECS` in
`domain/candidate.py`). In status it is no different from an LLM's
extraction output — a human labelled it once, rather than a model producing
it fresh on every run.

It serves three purposes:

1. **Regression.** The 37 `pytest` tests compare the engine's decision
   against a decision made from these same labels. That catches a change
   like "`combine_worst()` silently changed R10's decision" — it does not
   assert that R10 "should" be RESERVE in any absolute sense.
2. **A deterministic demo with no LLM.** `python3 report.py` produces the
   engine's decisions in seconds, with no network access and no API keys.
3. **Measuring extraction quality.** `eval_extraction.py` compares the
   LLM's extraction against the hand-labelled values — a measure of how
   closely the extractor matches the manual labels, not of candidate
   quality.

`screen.py` and the live path do not read or import
`candidates_golden.json`; the file plays no role in a live run, and it is
not a claim that any of the 10 candidates should receive a particular
decision in an absolute sense.

`poc.py` is a one-time script from development that confirmed a live Ollama
call returns valid JSON against the schema, before `extract.py` was built
on that assumption. Nothing in the repository imports it; it is not part of
the pipeline.

---

## Decision rules and assumptions

### Criteria model

For each vacancy (`fixtures/vacancies/roles.json`):

- **must-have** — required criteria. A "hard" failure (explicit false,
  backed by a quote) → `отказ` (reject).
- **stop factors** — explicit incompatibilities from the brief ("only Java
  enterprise, no web," etc.), a type separate from criteria
  (`StopFactorResult`). Any match → `отказ`, even if every must-have is
  formally satisfied.
- **nice-to-have** — never affects the decision, shown only as context for
  the human reviewer.
- **salary range** — not a stop factor, a separate flag: `in_range` /
  `above_range` / `below_range` / `unknown`. Above range with nothing else
  wrong → `в резерв` (reserve); below range doesn't block the decision, it's
  just a visible signal.

### Criterion status and evidence-grounding

Every criterion: status `met` / `not_met` / `unclear` / `not_applicable`,
plus mandatory `reason` and `provenance` (which mechanism produced the
status).

**The core rule:** a criterion can only be `met` or `not_met` if it has a
quote that's genuinely locatable in the résumé text (exact character
offsets, `raw_text[start:end] == quote text`). No quote, or one that can't
be found verbatim, and the criterion is `unclear` — never guessed.
`unclear` within a candidate's own stated profession does not block `берём`
(take) — the decision still goes through, at lower confidence, with an
explicit list of what's unconfirmed. A `partial` signal (a bool3 value —
e.g. "delegated the integration work to the architect") produces a
`not_met` status tagged in `provenance` (`rule:partial_signal`) — a "soft"
failure (→ `в резерв`), distinct from a "hard" `not_met` with
`provenance=rule:explicit_false` (an explicit contradiction → `отказ`).
Status is always one of exactly four values; "soft" vs. "hard" lives in
`provenance`, not a fifth status value — and that's exactly what gets lost
in rendering (see Known Issues).

### Cross-role check

`evidence_full_matrix.json` runs every candidate against all three roles.
`unclear` on the wrong profession doesn't get a free pass —
`domain/decision.py` with `cross_role=True` rejects such a candidate without
relabelling the criterion's status (a BA résumé genuinely has no
contradicting quote about TypeScript — it isn't there, but there's no
confirming one either). Without this split, a business analyst's résumé
would formally pass Fullstack's and UX/UI's must-haves simply because a
résumé for the wrong profession has no negative signals about a field it
never discusses.

### Disputed cases, walked through (10 labelled résumés)

- **R03 (Anna Kim, BA, 300k against a 220–280k range, integrations
  "usually delegated to the architect")** — a strong candidate on domain and
  requirements, but `integrations` is a soft `not_met`, and salary is above
  range → `в резерв`.
- **R10 (Nikita Frolov, fullstack, strong LLM-agent experience, self-reports
  "frontend is workable, not premium")** — passes on tenure and stack, but
  `frontend_quality` is a soft `not_met` by the candidate's own admission →
  `в резерв`: a strong nice-to-have doesn't offset a weakened must-have.
- **R05 (Elena Zhukova, frontend, willing to fly to Moscow at company
  expense)** — `stack` and `frontend_quality` are hard `not_met` (explicitly
  never configured SSR, stack has no TS/Python on production work) →
  `отказ`; work format logistics are secondary.
- **R06 (Pavel Chernov, 12 years of Java, wants to "switch to fullstack")** —
  two independent stop factors fire (`java_enterprise_only`, `no_releases`)
  → `отказ`, both listed in the trace.
- **R09 (Yulia Rakhmanova, 10 years of graphic design, "picked up Figma a
  year ago," no UX cases)** — the engine distinguishes "10 years in design"
  from "years specifically in UX/UI" (`0` for R09); the
  `graphic_design_only` stop factor also fires.

### Assumptions

- **Decision semantics**: `берём` = no must-have is hard- or soft-failed, no
  stop factor fired; `в резерв` = a soft failure on at least one must-have
  OR salary above range, with no hard failures and no stop factors;
  `отказ` = a hard failure on at least one must-have OR a stop factor fired.
- **Salary above range is not a stop factor** (the brief never names it as a
  rejection reason); below range doesn't block either — just a visible
  signal.
- **`unclear` doesn't block `берём` within a candidate's own profession**,
  but does block it in the cross-role run — a deliberate, tested assumption.
- **Evidence is required for `met`/`not_met`**: a value with no groundable
  quote is `unclear`, never taken on the model's stated confidence alone —
  including when escalation returns high confidence but still no quote.
- **No cap on shortlist size** — each candidate's decision is made
  independently against the rules, not against a quota.
- **Résumé-to-vacancy routing**: for the golden set (`report.py`), the role
  comes from `primary_role` in the fixtures; for an arbitrary résumé
  (`screen.py`), a cheap live LLM classification pass runs before the main
  extraction.
- **Escalation requires a genuinely different model** — if a provider has
  the same model configured for "cheap" and "strong" (true for all four
  providers right now), escalation is explicitly disabled and this is
  recorded in the output, rather than silently becoming a repeat call to the
  same model.

### Combining roles

A candidate can be considered for two roles if the résumé explicitly
supports it. No such case appeared in this set — every candidate is
evaluated only against their primary specialization.

---

## Known issues

### Status vocabulary and lossy rendering

The engine distinguishes four criterion statuses — `met`, `not_met`,
`unclear`, `not_applicable` — but `not_met` is further split by
`provenance`: "hard" (`rule:explicit_false`, an explicit contradiction) and
"soft" (`rule:partial_signal`, a bool3 `partial` value — evidence supports
part of the criterion and explicitly limits the rest). This split exists in
the JSON (`criteria.must_have[].provenance`) but not in the `.explain.md`
renderer — both cases print the same label, "не выполнено" ("not met").

Three consequences when reading the outputs:

1. **`partial` on a must-have is a soft miss**, routed to РЕЗЕРВ rather than
   ОТКАЗ — the renderer prints it as "не выполнено," which overstates it
   (R03's integrations, R10's front-end quality).
2. **A criterion showing "нет цитаты" ("no quote") can still have grounded
   sub-fields.** R10's `git_deploy` is `unclear` because Git and code review
   are ungrounded; `deploy` is explicitly confirmed ("Деплой на VPS." —
   "Deploys to a VPS"). That quote, and the fact that `deploy` itself is
   `met`, disappears from the aggregated criterion: `combine_worst()` in
   `engine/rules.py` pulls evidence and reason only from the sub-signals
   sharing the worst status, and `deploy` isn't the worst one here. In the
   golden run for R10, the aggregated result has `evidence: []` and a
   `reason` that never mentions `deploy`, even though that quote is present
   in `extraction.deploy_evidence`.
3. **`compensation_status` is a fact, not a clarification item** — it
   affects the decision only via the stated rule (`above_range` → at best
   РЕЗЕРВ, never higher).

**Known gap:** reuse of one quote across several criteria is not detected.
A live Gemini run on R05 cited "SSR не настраивала, формы отправляла в
Formspree" ("didn't configure SSR, sent forms via Formspree") for four
fields at once, including `deploy`, which the sentence says nothing about.
The verdict doesn't depend on it (the rejection already rests on `stack`
and `frontend_quality`), but `git_deploy` would more accurately read as
`unclear` here, not `not_met` — a misattributed but genuinely grounded quote
currently gives the criterion a "hard failure" status it doesn't earn. In
that run's output (`screening_results/R05.evidence.json`): `status:
not_met`, `provenance: combine:worst(...,rule:explicit_false)`, and the
evidence is that same imprecise quote. Only a cross-field consistency
check would catch this, and it doesn't exist yet (see
`TECH_ARCHITECTURE.*.md`).

### The extraction evaluation harness is deliberately minimal

`eval_extraction.py` computes only field-level and decision-level agreement
against the hand-labelled set — nothing more sophisticated. On a real
résumé stream it would be worth replacing with an established
LLM-evaluation framework (DeepEval or similar) rather than growing a custom
one. That change addresses measuring extraction quality across a dataset,
not whether a given quote supports a given criterion — the latter remains
the job of the in-pipeline relevance judge (`validation/relevance.py`), not
the evaluation harness.

### Other

- **The model isn't always deterministic across identical calls.** Repeated
  runs of the same résumé through the same provider produced different
  evidence sets and different confidence values (`temperature=0` doesn't
  guarantee bit-for-bit reproducibility across all providers) — the final
  decision stayed stable across every observed repeat, but which quotes back
  it up, and which fields end up `unclear`, can vary run to run.
- **Escalation is a mechanism for the future, not today.** All four
  configured providers use the same model for "cheap" and "strong," so
  escalation currently produces no quality gain — it only records that a
  field remains unconfirmed (`_needs_human_review`). The code for real
  escalation exists and is tested (a mocked scenario in
  `tests/test_validation.py`); it has not run against a genuinely different
  model.
- **Extraction quality varies noticeably by provider/model.** On the 10
  labelled résumés, `phi4-mini:3.8b` produced higher decision-level
  agreement than `qwen2.5:3b`, and hallucinated far fewer stop factors —
  which is why it's the default model for Ollama.
- **Groq was occasionally blocked at the network level** in the sandbox
  where this was developed (a Cloudflare client-fingerprint block on
  `urllib.request`; worked around via a system `curl` call in
  `extractors/providers.py`) — an HTTP 403 "Access denied. Please check your
  network settings" from Groq is the same class of issue, not a bug in the
  code.
- **The blanket "Moscow, hybrid, 2–3 days a week" requirement is only
  partially checked.** It's stated once in the assignment, for all three
  vacancies at once, but the criteria cover only a narrow special case of
  it — V1's `remote_other_tz` stop factor ("100% remote from a different
  time zone with no hybrid component"). V2 and V3 have no work-format check
  at all — no must-have, no stop factor. It didn't change any of the 10
  decisions (the closest case, R06's "office only, 5/2," is already rejected
  on two independent stop factors), but the requirement is not covered in
  code for V2/V3 — a known open gap, not a forgotten detail.

---

## Repository structure

The working pipeline (this is the product):

```
domain/        pure data + role-agnostic rules
                (Vacancy, CandidateProfile, CriterionStatus, EvaluationResult,
                 decision.py — the ONLY place a decision gets made)
engine/        role-specific criteria (which résumé fields matter for
                BA/Fullstack/UX-UI) + build_criterion() — where a raw
                field value + evidence quote becomes a CriterionResult
extractors/    the only layer allowed to call an LLM
                (providers.py — 4 providers behind one interface;
                 llm_extractor.py — prompts, escalation, caching)
validation/     grounds quotes in the source text (grounding.py) and the
                LLM relevance judge (relevance.py) — see
                TECH_ARCHITECTURE.*.md, "Evidence validation"
fixtures/vacancies/   vacancy criteria (V1/V2/V3) — must-have/nice-to-have/
                stop-factor source, taken from 02_вакансии_и_резюме.md
fixtures/resumes/     10 raw résumés (.txt) — input for screen.py and extraction

screen.py      CLI: one résumé -> LLM -> engine -> report (working path)
```

Demo, regression, and extraction-quality measurement — not used by
`screen.py` (see "The golden set" above):

```
fixtures/candidates_golden.json   10 résumés, hand-labelled —
                not an assignment answer key; none exists (see above)
tests/         pytest — regression against manual labels + evidence-grounding
                acceptance tests
report.py      CLI: manual labels -> engine -> report (batch, no LLM,
                deterministic demo of the selection logic)
extract.py     Stage-1 over all résumés at once: concurrency, cache, escalation
poc.py         one-time development script checking that a live Ollama
                call returns valid JSON against the schema; nothing
                imports it, not part of the pipeline
eval_extraction.py   compares LLM extraction against manual labels
                (field/decision agreement) — an extractor metric, not a
                candidate metric

environment.yml       conda environment (the only dependency is pytest)
TECH_ARCHITECTURE.*.md   target architecture, what's built vs. what's planned
```
