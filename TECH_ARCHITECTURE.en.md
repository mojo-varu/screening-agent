# Target Architecture — Evidence-Grounded Screening

This diagram is the north star for where this system is heading. It isn't a
catalogue design pulled from an architecture reference — it's the original
pipeline diagram, extended by one gate (**EVIDENCE VALIDATION**) that three
separate live runs (R01 via local Ollama, R02 via Gemini, R05 via Gemini)
proved was missing. Each box below is either already built and covered by a
test, or marked ⚠ as a deliberate next step — and the difference matters: this
file is meant to be checked against the code, not taken on faith, so a claim
here that doesn't hold would be worse than not writing it down at all.

```
              VACANCY
                 │
                 ▼
         Structured criteria
                 │
                 │
CV ──────────────┤
                 ▼
        Evidence extraction
           (LLM + schema)
                 │
                 ▼
    ┌─────────────────────────┐
    │   EVIDENCE VALIDATION    │  ⚠ partial: grounding — built & tested;
    │  (grounding, schema,     │    semantics / cross-field — next step
    │   semantics, cross-      │
    │   field consistency)     │
    └────────────┬─────────────┘
                 │
          ┌──────┴───────┐
          ▼              ▼
    valid evidence    rejected
          │           (ungrounded quote)
          │              │
          │              ▼
          │         downgrade to UNCLEAR
          │         ⚠ "retry" and "confidence penalty
          │           carried forward" are NOT built —
          │           today it's binary: no groundable
          │           quote → criterion is UNCLEAR, full
          │           stop, nothing is carried forward
          ▼
    Criterion evaluation
          │
  ┌───────┼────────┐
  ▼       ▼        ▼
 MUST   NICE     STOP
  │       │        │
  └───────┼────────┘
          ▼
    Decision policy
          │
  ┌───────┼──────────┐
  ▼       ▼          ▼
БЕРЁМ  РЕЗЕРВ      ОТКАЗ
          │
          ▼
    Decision trace
          │
          ▼
     Explanation
```

Solid boxes are implemented and covered by tests. Boxes marked ⚠ are target
state; what exactly is deferred and why is in **Known limitations** below —
that section exists specifically so this diagram doesn't quietly overclaim.

## Box-by-box: what implements what

| Box | Implemented in | Status |
|---|---|---|
| VACANCY → Structured criteria | `domain/vacancy.py`, `fixtures/vacancies/roles.json` | built, tested |
| CV → Evidence extraction | `extractors/llm_extractor.py`, `extractors/providers.py` | built, tested |
| Evidence validation — grounding | `validation/grounding.py` (`locate()`), called from `engine/rules.py`'s `build_criterion()` | built, tested |
| Evidence validation — schema | `domain/candidate.py` (`_normalize()`, type coercion), the "no quote → no verdict" rule in `build_criterion()` | built, tested |
| Evidence validation — semantics | `validation/relevance.py` (`judge_relevance`, `apply_relevance_judge`) | built, **opt-in only** (`--judge-relevance`), not in the default path |
| Evidence validation — cross-field consistency | — | **not built** |
| rejected → downgrade | `build_criterion()`: ungrounded or missing evidence → `UNCLEAR`, `provenance="validation:ungrounded_downgrade"` or `"rule:no_evidence"` | built, tested |
| rejected → retry | — | **not built** |
| confidence penalty carried forward | — | **not built** (deliberately — see below) |
| Criterion evaluation → MUST / NICE / STOP | `engine/rules.py`, `domain/evaluation.py` (`StopFactorResult`, a type separate from the criterion status enum) | built, tested |
| Decision policy → БЕРЁМ / РЕЗЕРВ / ОТКАЗ | `domain/decision.py` | built, tested |
| Decision trace → Explanation | `report.py` (`build_artifact`, `render_markdown_from_artifact`), `screen.py` | built, tested |

## Known limitations (the ⚠ boxes, explained)

### 1. Semantics — implemented, not wired into the default path

`validation/relevance.py` asks a judge model one narrow question per
non-empty evidence span: *does this quote support this specific criterion?*
It's real and it works — verified against real cases already present in the
golden set: R01's `usm` criterion was satisfied by the quote *"User Story."*,
which is a narrower technique than the *"User Story Mapping"* the criterion
actually asks for; R01's `integrations` criterion was satisfied by a quote
about writing integration briefs, not hands-on integration work. A mocked
judge correctly downgrades both to `UNCLEAR` in the test suite
(`tests/test_validation.py`), and one live verification call confirmed the
mechanism runs end to end against a real model.

It isn't in the default `screen.py`/`report.py` path — it costs one extra LLM
call per non-empty evidence field, and was scoped as opt-in
(`--judge-relevance`) from the start rather than something every run pays for
automatically.

### 2. Cross-field consistency — not built, and now has a concrete example

Grounding only answers "does this exact text exist in the résumé" — it can't
tell that the *same* real, correctly-grounded quote is being reused as
"evidence" for multiple, unrelated fields. A live Gemini run on candidate R05
did exactly this: the quote *"SSR не настраивала, формы отправляла в
Formspree"* (*"didn't configure SSR, sent forms via Formspree"*) came back as
the cited evidence for `ssr`, `meta_forms_responsive`, `deploy`, **and**
`external_api` — including a field (`deploy`) the sentence never mentions at
all. Grounding correctly did not flag this, because the quote genuinely is a
verbatim substring of the résumé; catching *this* class of error needs a
distinct check — something that looks across fields at how evidence is being
reused, not just whether each span individually resolves. Nothing in the
codebase does this yet.

### 3. Confidence penalty attached to evidence — deliberately not built

The current design is binary: a criterion either has a grounded, on-topic
quote and is evaluated at full trust, or it doesn't and becomes `UNCLEAR` —
model-reported confidence is persisted for visibility but never feeds
numerically into criterion status or the decision. A graded "penalize but
still use" path was explicitly scoped *out* of the evidence-grounding work
that preceded this diagram, for a specific reason: "model self-reported
confidence is not calibrated against real accuracy... prefer structural
triggers (empty evidence, failed grounding, judge says insufficient) over
invented cutoffs." Building the confidence-penalty box means deliberately
revisiting that call, not quietly reintroducing what it ruled out.

### 4. Retry — not built

A grounding failure goes straight to `downgrade`; there is no mechanism that
re-asks the model for a corrected quote before giving up. Every ungrounded or
missing-evidence field becomes `UNCLEAR` on the first attempt.

## Why this diagram, not a redesign

Every box added beyond the original pipeline traces to something a real run
actually did, not a hypothetical:

- **Grounding** exists because a Gemini run once claimed a candidate's name
  and city as "evidence" for their Russian-language proficiency — a real
  quote, attached to the wrong claim entirely.
- **The relevance judge** exists because two criteria in the hand-reviewed
  golden set (R01's `integrations` and `usm`) turned out to have real,
  grounded, but topically-imprecise evidence — grounding alone can't catch a
  quote that's genuinely from the résumé but doesn't say what it's cited for.
- **Cross-field consistency** is flagged as the next gap because R05 showed
  the same failure mode one level up: not a wrong quote, but one quote doing
  duty for several unrelated — and in places contradictory — claims.

The direction came from what the system actually got wrong, in order,
verified against live model output — not from browsing a catalogue of
validation patterns and picking ones that sounded thorough.
