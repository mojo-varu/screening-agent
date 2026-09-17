# HR Candidate Screening Agent — "Akvatoriya"

## What this project does

A deterministic screening engine for three job openings (BA, Fullstack,
UX/UI) with full decision traceability: why a candidate was taken /
reserved / rejected, against which exact criterion, backed by a grounded
(verifiable) quote from the résumé — not "the model said so," but "here's
the exact line in the résumé, here's where it sits in the text."

The decision (`берём` / `в резерв` / `отказ` — take / reserve / reject) is
made by a deterministic rule over structured data (`domain/decision.py`),
not by an LLM — that module never sees raw résumé text and never calls an
LLM. The LLM is involved in exactly two places: picking the matching vacancy
from the résumé text (`classify_role`) and extracting fields against a
fixed schema (`extract_candidate`) — both in `extractors/`.

**The working pipeline is `screen.py`**: one résumé in → a live LLM → the
deterministic engine → an explanation out (see "Quickstart" below). Separately,
the repo also has demo/test infrastructure built around a manually labelled
set of 10 résumés (`report.py`, `fixtures/candidates_golden.json`) — none of
it is used by `screen.py` or the live path at all; what it is and what it's
for gets its own honest, dedicated section, "Golden set: what it is and
what it's for," below — not just a line in a list.

The architectural principle and its target state (what's already built vs.
still planned) — `TECH_ARCHITECTURE.en.md` / `TECH_ARCHITECTURE.ru.md`. This
file is about how to run it, what assumptions were made, and what's still
open.

---

## Status and limitations

- 37 `pytest` tests, all passing: regression against a manually labelled set
  of 10 résumés (what that means, and why it isn't "the assignment's answer
  key" — see "Golden set: what it is and what it's for" below), stop factors
  as a veto, regression tests for two real bugs, explicit acceptance tests
  for evidence-grounding (quote grounding, relevance judge, empty-evidence
  penalties).
- Evidence-grounding (locating quotes in the source text + type checking) is
  built and tested. The relevance judge ("does this quote actually support
  this specific criterion?") is implemented but only runs behind a flag
  (`--judge-relevance`), not in the default path. Cross-field evidence
  consistency checking isn't implemented at all. Full target-architecture
  breakdown, what's built vs. planned — `TECH_ARCHITECTURE.*.md`.
- Four LLM providers are implemented and live-tested: Ollama (self-hosted
  default), Anthropic, Groq, Gemini — behind one interface, no SDKs, just
  `urllib`/`curl`.
- The rendered report (`.explain.md`) loses some detail that's present in
  the JSON — see "Status vocabulary and lossy rendering" under Known Issues
  below; read that before taking the `.explain.md` labels at face value.

---

## Requirements

- **Python 3.9+** — the engine itself uses only the standard library.
- **pytest** — only for `tests/`; the engine runs fine without it.
- **Ollama**, installed and running, for the local provider.
- An API key (Anthropic and/or Groq and/or Gemini) for the cloud providers;
  none is required — `--provider ollama` works fully offline.
- Not required: `pip install` of any provider SDK (`anthropic`,
  `google-generativeai`, `groq`, etc.) — all four providers are implemented
  directly over HTTP (`extractors/providers.py`); no SDK is used anywhere.

---

## Conda environment setup

```bash
conda env create -f environment.yml
conda activate screening-agent
```

`environment.yml` is at the repo root — the only real dependency there is
`pytest`; the engine needs nothing else (verified by grepping every
`import`/`from` across the whole repository — see the comment in the file
itself).

Without conda — a plain `python3` on PATH (3.9+) works fine; `pytest` is
then installed separately (`pip install pytest`) and is only needed to run
the tests, not the engine itself.

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
quote, not on by default — see Known Issues):

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

The default model is `phi4-mini:3.8b-q4_K_M`, not `qwen2.5:3b` (switched
after a head-to-head comparison via `eval_extraction.py` on the golden
set — higher decision-level agreement, noticeably fewer hallucinated stop
factors; details under Known Issues). No API key needed; candidate PII never
leaves your infrastructure.

---

## Test commands

```bash
python3 -m pytest tests/ -v
```

37 tests, no network, no live LLM calls (everything runs against
synthetic/golden data, with mocked model calls where needed):

- `tests/test_decisions.py` — the golden decision table across all 10
  candidates;
- `tests/test_stop_factors.py` — stop factors as a veto, not just another
  must-have;
- `tests/test_missing_evidence.py` — regression tests for two real bugs
  (`None` instead of `[]`/`0` from a live model; `unclear` on the wrong
  profession, which used to be incorrectly counted as passing);
- `tests/test_validation.py` — explicit evidence-grounding acceptance tests:
  offsets ground exactly (`cv_text[start:end] == text`, checked across all
  46 evidence spans in the golden set), a fabricated quote is caught and
  downgrades to `unclear`, escalation never fires without a genuinely
  different model, confidence can't "rescue" empty evidence, the relevance
  judge downgrades real cases found in the golden set (not synthetic ones —
  labelled directly in the golden data).

The deterministic golden run (`python3 report.py`, see Outputs below) is a
second, slower verification path: 10 decisions you can eyeball directly in
`report.md`.

---

## Outputs

**`python3 report.py`** — batch run over the 10 golden candidates, no LLM:

- `report.md` — summary table across all 10;
- `screening_results/<id>.evidence.json` — the full per-candidate artifact
  (extraction → criteria → decision → validation, one JSON);
- `screening_results/<id>.explain.md` — the same thing, rendered into a
  readable form (rendered FROM this JSON, not from separate live objects —
  so `.md` and `.json` can't drift apart, though the render does lose some
  detail present in the JSON — see "Status vocabulary and lossy rendering");
- `evidence_full_matrix.json` — cross-run of all 10 candidates against all 3
  roles (why — see "Decision rules and assumptions" → "Cross-role check").

**`python3 screen.py <resume.txt> --provider ...`** — one live run, writes
the same `screening_results/<id>.evidence.json` / `<id>.explain.md` (shares
the renderer with `report.py`).

**`python3 extract.py` / `python3 eval_extraction.py`** — Stage-1 over all
résumés at once and comparison against golden (field/decision agreement) —
for comparing providers/models, not for everyday use.

---

## Golden set: what it is and what it's for

`fixtures/candidates_golden.json` is NOT the assignment's answer key and not
an external ground truth. The assignment says so explicitly: *"There is no
'correct list' reference in this file: you define the criteria"* — a correct
list doesn't exist in principle, not from a reviewer, not from anywhere else.

**What it actually is:** the 10 résumés from `02_вакансии_и_резюме.md`,
hand-labelled by me into the same structured-field schema the live extractor
uses (`FIELD_SPECS` in `domain/candidate.py`) — in other words, my own
reading of the assignment text turned into JSON, no different in status from
an LLM's output except that it was labelled once by a human instead of by a
model on every run.

**Why it's useful, given it isn't "the right answers":**

1. **Regression.** The 37 `pytest` tests check that `engine/`+`domain/`
   don't change behavior unintentionally when code changes — by comparing
   the engine's decision against a decision made against THE SAME LABELS,
   not against some external truth. That catches "I changed
   `combine_worst()` and R10's decision silently changed," not "R10 should
   be RESERVE in some absolute sense."
2. **A deterministic demo with no LLM.** `python3 report.py` shows the
   engine's decisions in seconds, no network, no keys — useful for seeing
   the selection logic in action without waiting on a live model call.
3. **Measuring extraction quality.** `eval_extraction.py` compares what the
   LLM extracted from the raw text against what I extracted by hand — a
   metric of "how closely does the extractor match my manual labelling," not
   "how good is the candidate."

**What it does NOT do:** it is not used by the working pipeline, `screen.py`,
at all (verified — a `grep` across the whole repository confirms `screen.py`
never imports or reads `candidates_golden.json` in any form), and it is not
a claim that any of the 10 candidates "should" actually get a particular
decision — that would be overselling what 10 pytest tests can prove in the
first place.

`poc.py` follows the same principle: a minimal script I used once, by hand,
to confirm that a live Ollama call really does return valid JSON against the
schema, before building the full `extract.py` on top of that assumption.
Nothing in the repository imports it (verified with `grep`) — it's not part
of `screen.py`, the tests, or `report.py`. It's a one-time development
diagnostic artifact, not part of the pipeline.

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
be found verbatim — the criterion is honestly `unclear`, never silently
guessed. `unclear` within a candidate's own stated profession **does not
block** `берём` (take) — the decision still goes through, just at lower
confidence with an explicit list of what's unconfirmed. A `partial` signal
(a bool3 value — e.g. "delegated the integration work to the architect")
produces a `not_met` status tagged in `provenance`
(`rule:partial_signal`) — a "soft" failure (→ `в резерв`), distinct from a
"hard" `not_met` with `provenance=rule:explicit_false` (an explicit
contradiction → `отказ`). Status is always one of exactly four values;
"soft" vs. "hard" lives in `provenance`, not a fifth status value — and
that's exactly what gets lost in rendering (see Known Issues).

### Cross-role check

`evidence_full_matrix.json` runs every candidate against all three roles.
`unclear` on the wrong profession doesn't get a free pass —
`domain/decision.py` with `cross_role=True` rejects such a candidate without
relabelling the criterion's status (a BA résumé genuinely has no
contradicting quote about TypeScript — it simply isn't there, but there's no
confirming one either). Without this split, a business analyst's résumé
would formally pass Fullstack's and UX/UI's must-haves simply because a
résumé for the wrong profession has no negative signals about a field it
never discusses — there are none there at all.

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
  → `отказ`, both listed in the trace, not just the first one.
- **R09 (Yulia Rakhmanova, 10 years of graphic design, "picked up Figma a
  year ago," no UX cases)** — the engine explicitly distinguishes "10 years
  in design" from "years specifically in UX/UI" (`0` for R09), plus the
  `graphic_design_only` stop factor fires.

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
  including the case where escalation returned high confidence but still no
  quote.
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
the JSON (`criteria.must_have[].provenance`) but NOT in the `.explain.md`
renderer — both cases print the same label, "не выполнено" ("not met").

Three consequences when reading the outputs:

1. **`partial` on a must-have is a soft miss**, routed to РЕЗЕРВ rather than
   ОТКАЗ — the renderer prints it as "не выполнено," which overstates it
   (R03's integrations, R10's front-end quality).
2. **A criterion showing "нет цитаты" ("no quote") may still have grounded
   sub-fields.** R10's `git_deploy` is `unclear` because Git and code review
   are ungrounded; `deploy` is explicitly confirmed ("Деплой на VPS." —
   "Deploys to a VPS"). But that quote, and the fact that `deploy` itself is
   `met`, disappears entirely from the aggregated criterion:
   `combine_worst()` in `engine/rules.py` only pulls evidence and reason
   from the sub-signals sharing the WORST status, and `deploy` isn't the
   worst one here. Verified against the real golden run for R10:
   `evidence: []`, and `reason` doesn't mention `deploy` at all — even
   though the quote sits right there in `extraction.deploy_evidence`.
3. **`compensation_status` is a fact, not a clarification item** — it
   affects the decision only via the stated rule (`above_range` → at best
   РЕЗЕРВ, never higher).

**Known gap:** reuse of one quote across several criteria is not detected.
A live Gemini run on R05 cited "SSR не настраивала, формы отправляла в
Formspree" ("didn't configure SSR, sent forms via Formspree") for four
fields at once, including `deploy`, about which the sentence says nothing at
all. The verdict doesn't depend on it (the rejection already rests on
`stack` and `frontend_quality`), but `git_deploy` would more honestly read
as `unclear` here, not `not_met` — right now a misattributed-but-genuinely-
grounded quote gives the criterion a "hard failure" status it doesn't
actually earn. Verified against the real live output
(`screening_results/R05.evidence.json` from that run): `status: not_met`,
`provenance: combine:worst(...,rule:explicit_false)`, evidence is that same
imprecise quote. Only a cross-field consistency check would catch this, and
it doesn't exist yet (see `TECH_ARCHITECTURE.*.md`).

### The extraction evaluation harness is deliberately minimal

`eval_extraction.py` computes only field-level and decision-level agreement
against a hand-labelled set — nothing more sophisticated. On a real résumé
stream it would be worth replacing with an established LLM-evaluation
framework (DeepEval or similar) rather than growing our own. One caveat:
that addresses measuring extraction quality across a dataset, not checking
whether a given quote supports a given criterion — the latter remains the
job of the in-pipeline relevance judge (`validation/relevance.py`), not the
evaluation harness.

### Other

- **The model isn't always deterministic across identical calls.** Repeated
  runs of the same résumé through the same provider produced different
  evidence sets and different confidence values (`temperature=0` doesn't
  guarantee bit-for-bit reproducibility across all providers) — the final
  decision stayed stable across every observed repeat, but which quotes back
  it up, and which fields end up `unclear`, can vary run to run.
- **Escalation is a mechanism for the future, not today.** All four
  configured providers use the same model for "cheap" and "strong," so
  escalation currently produces no quality gain — it only honestly records
  that a field remains unconfirmed (`_needs_human_review`). The code for
  real escalation exists and is tested (a mocked scenario in
  `tests/test_validation.py`); it has never actually run against a genuinely
  different model.
- **Extraction quality varies noticeably by provider/model.** On the 10
  labelled résumés, `phi4-mini:3.8b` produced higher decision-level agreement
  than `qwen2.5:3b`, and hallucinated far fewer stop factors — which is why
  it's the default model for Ollama.
- **Groq was occasionally blocked at the network level** in the sandbox
  where this was developed (a Cloudflare client-fingerprint block on
  `urllib.request`; worked around via a system `curl` call in
  `extractors/providers.py`) — if you see an HTTP 403 "Access denied. Please
  check your network settings" from Groq on your own machine, that's the
  same class of issue, not a bug in the code.
- **The blanket "Moscow, hybrid, 2–3 days a week" requirement is only
  partially checked.** It's stated once in the assignment, for all three
  vacancies at once, but the criteria only cover a narrow special case of
  it — V1's `remote_other_tz` stop factor ("100% remote from a DIFFERENT
  time zone with no hybrid component"). V2 and V3 have no work-format check
  at all — no must-have, no stop factor. It didn't change any of the 10
  decisions (the closest case, R06's "office only, 5/2," is already rejected
  on two independent stop factors), but the assignment's requirement genuinely
  isn't covered in code for V2/V3 — that's not a forgotten detail, it's a
  knowingly open gap that deserves an explicit discussion rather than a quiet
  ad hoc fix.

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

screen.py      CLI: one résumé -> LLM -> engine -> report (WORKING PATH)
```

Demo / regression / extraction-quality measurement — NOT used by `screen.py`
(details — "Golden set: what it is and what it's for" above):

```
fixtures/candidates_golden.json   10 résumés, hand-labelled by me —
                NOT the assignment's answer key, no such thing exists (see above)
tests/         pytest — regression against manual labels + evidence-grounding
                acceptance tests
report.py      CLI: manual labels -> engine -> report (batch, no LLM,
                deterministic demo of the selection logic)
extract.py     Stage-1 over all résumés at once: concurrency, cache, escalation
poc.py         one-time development diagnostic script — checks that a live
                Ollama call returns valid JSON against the schema; nothing
                imports it, not part of the pipeline
eval_extraction.py   compares LLM extraction against manual labels
                (field/decision agreement) — an extractor metric, not a
                candidate metric

environment.yml       conda environment (the only dependency is pytest)
TECH_ARCHITECTURE.*.md   target architecture, what's built vs. what's planned
```
