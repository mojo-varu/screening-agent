"""
Явные acceptance-тесты из спецификации Phase 2 (evidence-grounded criterion
evaluation) — по одному на Task 2, 4, 5A, 5B, 6, 7. Не дублируют
test_decisions.py/test_missing_evidence.py/test_stop_factors.py — те проверяют
решения end-to-end, эти — конкретные механизмы, которые спецификация назвала
по имени как критерий приёмки.
"""
import dataclasses

from domain.criteria import CriterionStatus
from domain.evaluation import eval_compensation
from domain.vacancy import Vacancy, Criterion
from engine.evaluator import evaluate
from engine.rules import build_criterion
from validation.relevance import apply_relevance_judge
from validation.report import ValidationReport


# --- Task 2: критерий не может быть MET/NOT_MET без evidence ---------------

def test_task2_no_empty_evidence_met_or_not_met(vacancies, golden, resumes):
    violations = []
    for cid, c in golden.items():
        evaluation, vr = evaluate(vacancies[c.vacancy_id], c, resumes.get(cid, ""))
        for m in evaluation.must_have:
            if not m.evidence and m.status in (CriterionStatus.NOT_MET, CriterionStatus.MET):
                violations.append((cid, m.criterion_id, m.status.value))
    assert not violations, f"критерии без evidence, но с MET/NOT_MET: {violations}"


# --- Task 4: фабрикация цитаты ловится и понижает до UNCLEAR ---------------

def test_task4_fabricated_quote_downgraded_to_unclear():
    vr = ValidationReport()
    raw_text = "Системный аналитик, 2 года. Русский — рабочий."
    result = build_criterion(
        "russian_quality", "Русский язык: технические тексты без кальки",
        True, "Отличное владение русским литературным языком с 2010 года",
        raw_text, vr,
    )
    assert result.status == CriterionStatus.UNCLEAR
    assert result.provenance == "validation:ungrounded_downgrade"
    assert len(vr.for_criterion("russian_quality")) == 1
    assert vr.issues[0].kind == "ungrounded"


def test_task4_real_quote_not_downgraded():
    vr = ValidationReport()
    raw_text = "Системный аналитик, 2 года. Русский — рабочий."
    result = build_criterion(
        "russian_quality", "Русский язык: технические тексты без кальки",
        True, "Русский — рабочий", raw_text, vr,
    )
    assert result.status == CriterionStatus.MET
    assert not vr.issues


# --- Task 5A: эскалация на ту же модель не выполняется, а не тихо повторяется ---

def test_task5a_escalation_skipped_without_distinct_model(monkeypatch):
    import extractors.llm_extractor as le

    calls = []

    def fake_call_llm(prompt, model, provider):
        calls.append(model)
        return {
            "years_total": 2, "years_total_confidence": 0.9, "years_total_evidence": "2 года",
            "requirements_authorship": True, "requirements_authorship_confidence": 0.3,
            "requirements_authorship_evidence": None,
            "integrations_experience": False, "integrations_experience_confidence": 0.9,
            "integrations_experience_evidence": None,
            "russian_native": True, "russian_native_confidence": 0.9, "russian_native_evidence": "русский родной",
            "domain_match": True, "domain_match_confidence": 0.9, "domain_match_evidence": None,
            "bpmn": False, "bpmn_confidence": 0.9, "bpmn_evidence": None,
            "usm": False, "usm_confidence": 0.9, "usm_evidence": None,
            "english": None, "english_confidence": 0.9, "english_evidence": None,
            "work_format": "hybrid", "work_format_confidence": 0.9, "work_format_evidence": None,
            "salary_expectation": 250000, "salary_expectation_confidence": 0.9, "salary_expectation_evidence": None,
            "stop_notes": [], "stop_notes_confidence": 0.9, "stop_notes_evidence": None,
            "weaknesses": [], "weaknesses_confidence": 0.9, "weaknesses_evidence": None,
        }

    monkeypatch.setattr(le, "call_llm", fake_call_llm)
    # strong == cheap (текущая конфигурация всех реальных провайдеров) -> эскалация должна быть отключена
    monkeypatch.setattr(le, "MODELS", {"ollama": {"cheap": "small", "strong": "small"}})

    profile = le.extract_candidate("V1", "TEST", "Test", "2 года. русский родной.", provider="ollama")
    assert len(calls) == 1, "эскалация не должна была вызывать модель повторно"
    assert "_escalation_disabled_reason" in profile.fields


# --- Task 5B: confidence не может "вылечить" пустой evidence ---------------

def test_task5b_high_confidence_with_empty_evidence_still_needs_review(monkeypatch):
    import extractors.llm_extractor as le

    calls = []

    def fake_call_llm(prompt, model, provider):
        calls.append(model)
        if len(calls) == 1:
            return {
                "years_total": 2, "years_total_confidence": 0.9, "years_total_evidence": "2 года",
                "requirements_authorship": True, "requirements_authorship_confidence": 0.9,
                "requirements_authorship_evidence": None,
                "integrations_experience": False, "integrations_experience_confidence": 0.3,
                "integrations_experience_evidence": None,
                "russian_native": True, "russian_native_confidence": 0.9, "russian_native_evidence": "русский родной",
                "domain_match": True, "domain_match_confidence": 0.9, "domain_match_evidence": None,
                "bpmn": False, "bpmn_confidence": 0.9, "bpmn_evidence": None,
                "usm": False, "usm_confidence": 0.9, "usm_evidence": None,
                "english": None, "english_confidence": 0.9, "english_evidence": None,
                "work_format": "hybrid", "work_format_confidence": 0.9, "work_format_evidence": None,
                "salary_expectation": 250000, "salary_expectation_confidence": 0.9,
                "salary_expectation_evidence": None,
                "stop_notes": [], "stop_notes_confidence": 0.9, "stop_notes_evidence": None,
                "weaknesses": [], "weaknesses_confidence": 0.9, "weaknesses_evidence": None,
            }
        # эскалация: confidence подскочила, evidence так и остался пустым
        return {"integrations_experience": False, "integrations_experience_confidence": 0.95,
                "integrations_experience_evidence": None}

    monkeypatch.setattr(le, "call_llm", fake_call_llm)
    monkeypatch.setattr(le, "MODELS", {"ollama": {"cheap": "small", "strong": "big"}})  # различные -> эскалация разрешена

    profile = le.extract_candidate("V1", "TEST", "Test", "2 года. русский родной.", provider="ollama")
    assert len(calls) == 2, "эскалация должна была произойти (различные модели настроены)"
    assert profile.fields.get("integrations_experience_confidence") == 0.95
    assert profile.fields.get("_needs_human_review") is True
    assert "integrations_experience" in (profile.fields.get("_empty_evidence_critical_fields") or [])


# --- Task 6: судья по релевантности понижает реальные ground-truth случаи ---

def test_task6_relevance_judge_downgrades_known_bad_evidence(vacancies, golden, resumes, monkeypatch):
    """Использует ручную разметку fixtures/candidates_golden.json
    (criteria_evidence_labels) как ground truth — R01.integrations и
    R01.usm размечены 'insufficient' (реальные, не синтетические случаи,
    найденные при ревью golden-набора: верная дословная цитата, но не о том,
    что требует критерий)."""
    c = golden["R01"]
    evaluation, vr = evaluate(vacancies["V1"], c, resumes["R01"])

    def fake_judge(criterion_text, quote, provider, model):
        if "интеграциями" in criterion_text:
            return {"verdict": "insufficient", "reason": "брифы — не hands-on интеграция"}
        if criterion_text == "User Story Mapping":
            return {"verdict": "insufficient", "reason": "User Story != User Story Mapping"}
        return {"verdict": "supports", "reason": "ok"}

    import validation.relevance as relevance_mod
    monkeypatch.setattr(relevance_mod, "judge_relevance", fake_judge)

    new_must = apply_relevance_judge(evaluation.must_have, "ollama", "fake-model", vr)
    integrations = next(m for m in new_must if m.criterion_id == "integrations")
    assert integrations.status == CriterionStatus.UNCLEAR
    assert integrations.provenance == "judge:relevance"

    new_nice = apply_relevance_judge(evaluation.nice_to_have, "ollama", "fake-model", vr)
    usm = next(m for m in new_nice if m.criterion_id == "usm")
    assert usm.status == CriterionStatus.UNCLEAR
    assert usm.provenance == "judge:relevance"


def test_task6_judge_never_upgrades_status(vacancies, golden, resumes, monkeypatch):
    """Downgrade-only: даже если судья (ошибочно или нет) говорит 'supports'
    на критерий, который и так уже MET — статус не может стать 'более MET',
    чем он есть; а на UNCLEAR судья вообще не запускается (нет evidence)."""
    c = golden["R02"]
    evaluation, vr = evaluate(vacancies["V1"], c, resumes["R02"])
    unclear_before = [m.criterion_id for m in evaluation.must_have if m.status == CriterionStatus.UNCLEAR]

    def fake_judge(criterion_text, quote, provider, model):
        return {"verdict": "supports", "reason": "ok"}

    import validation.relevance as relevance_mod
    monkeypatch.setattr(relevance_mod, "judge_relevance", fake_judge)

    new_must = apply_relevance_judge(evaluation.must_have, "ollama", "fake-model", vr)
    unclear_after = [m.criterion_id for m in new_must if m.status == CriterionStatus.UNCLEAR]
    assert unclear_before == unclear_after, "судья не должен вызываться и не может повышать статус там, где evidence нет"


# --- Task 7: below_range — отдельный, видимый статус -----------------------

def test_task7_salary_below_range_is_distinct_status():
    vacancy = Vacancy(id="V1", title="test", salary_range=(220000, 280000))

    class _C:
        def get(self, key, default=None):
            return {"salary_expectation": 150000}.get(key, default)

    assert eval_compensation(vacancy, _C()) == "below_range"


def test_task7_below_range_does_not_force_reserve(vacancies, make_candidate, make_raw_text):
    """below_range — видимый сигнал, но не стоп-фактор и не авто-RESERVE
    (в отличие от above_range) — спецификация просит его 'surface', не
    добавлять новую политику решения."""
    c = make_candidate("V1", salary_expectation=100000)
    raw_text = make_raw_text(c.fields)
    from engine.evaluator import decide_candidate
    trace = decide_candidate(vacancies["V1"], c, raw_text)
    assert trace.evaluation.compensation_status == "below_range"
    assert trace.decision.value == "TAKE"


# --- Post-Phase-2 FIX 1/2: offsets всегда самовычисляются, никогда не
# принимаются от модели; grounding реально asserts на всех 10 golden ------

def test_fix1_every_evidence_span_matches_source_text_exactly(vacancies, golden, resumes):
    """Формальный acceptance-тест ('это должен быть тест, а не ручная
    проверка'): для каждого evidence span у каждого критерия у каждого из
    10 golden-кандидатов cv_text[start:end] == text — точно, не приближённо."""
    checked = 0
    for cid, c in golden.items():
        raw = resumes.get(cid, "")
        evaluation, vr = evaluate(vacancies[c.vacancy_id], c, raw)
        for m in list(evaluation.must_have) + list(evaluation.nice_to_have):
            for e in m.evidence:
                checked += 1
                assert raw[e.start:e.end] == e.text, (
                    f"{cid}.{m.criterion_id}: raw[{e.start}:{e.end}]={raw[e.start:e.end]!r} != {e.text!r}"
                )
    assert checked > 0, "тест должен реально пройтись по ненулевому числу spans"


def test_fix1_prompt_schema_never_requests_offsets():
    """Структурная гарантия: модель физически не может 'прислать' start/end,
    потому что схема их не запрашивает — locate() в engine/rules.py всегда
    вычисляет offsets сам по (raw_text, quote), другого пути в код нет."""
    from extractors.llm_extractor import build_prompt
    prompt = build_prompt("V1", "TEST", "тестовое резюме")
    assert '"start"' not in prompt and '"end"' not in prompt


# --- FIX 3: старая «gap -> pass» формулировка убрана -----------------------

def test_fix3_no_gap_to_pass_phrasing_anywhere(vacancies, golden, resumes):
    from engine.evaluator import decide_candidate
    banned = "нет сигнала → не фейлим"
    for cid, c in golden.items():
        trace = decide_candidate(vacancies[c.vacancy_id], c, resumes.get(cid, ""))
        assert banned not in trace.reason, f"{cid}: reason содержит устаревшую формулировку"
        for concern in trace.concerns:
            assert banned not in concern, f"{cid}: concern содержит устаревшую формулировку"
