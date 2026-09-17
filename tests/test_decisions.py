"""
Регрессия по всем 10 golden-кандидатам. Если это падает — кто-то поменял
engine/rules.py, domain/decision.py или fixtures/candidates_golden.json без
осознанного намерения; см. CLAUDE.md, "Правила при любых изменениях кода".
"""
import pytest

from domain.candidate import CandidateProfile
from engine.evaluator import decide_candidate

EXPECTED = {
    "R01": ("V1", "TAKE"), "R02": ("V1", "REJECT"), "R03": ("V1", "RESERVE"),
    "R04": ("V2", "TAKE"), "R05": ("V2", "REJECT"), "R06": ("V2", "REJECT"),
    "R07": ("V3", "TAKE"), "R08": ("V3", "REJECT"), "R09": ("V3", "REJECT"),
    "R10": ("V2", "RESERVE"),
}


@pytest.mark.parametrize("candidate_id,expected", EXPECTED.items())
def test_golden_decision(vacancies, golden, resumes, candidate_id, expected):
    expected_vacancy, expected_decision = expected
    c = golden[candidate_id]
    assert c.vacancy_id == expected_vacancy
    trace = decide_candidate(vacancies[c.vacancy_id], c, resumes.get(candidate_id, ""))
    assert trace.decision.value == expected_decision, (
        f"{candidate_id}: expected {expected_decision}, got {trace.decision.value} — {trace.reason}"
    )


def test_all_ten_covered():
    """Если кто-то добавит/удалит golden-кандидата, эта таблица должна быть
    обновлена осознанно, а не молча разойтись с fixtures."""
    assert len(EXPECTED) == 10


def test_take_requires_no_stop_factors_and_no_hard_fails(vacancies, golden, resumes):
    """Task 2: NOT_MET с provenance=rule:partial_signal — "мягкий" провал
    (-> RESERVE), а не полноценный отказ; TAKE не должен встречаться рядом
    ни со стоп-фактором, ни с "жёстким" NOT_MET (explicit_false)."""
    for cid, c in golden.items():
        trace = decide_candidate(vacancies[c.vacancy_id], c, resumes.get(cid, ""))
        if trace.decision.value == "TAKE":
            assert not trace.evaluation.stop_factors_triggered, f"{cid}: TAKE with a stop factor triggered"
            hard_fails = [m for m in trace.evaluation.must_have
                          if m.status.value == "not_met" and m.provenance != "rule:partial_signal"]
            assert not hard_fails, f"{cid}: TAKE with a hard must-have failure: {hard_fails}"


def test_nice_to_have_never_changes_decision(vacancies, make_candidate, make_raw_text):
    """Осознанный дизайн-выбор (см. TECH_SPEC.md, 'веса'): nice-to-have не
    взвешивается и не может компенсировать провал must-have. Проверяем явно,
    а не полагаемся, что оно 'просто не используется' в decision.py."""
    weak = make_candidate("V2", years_total=1, years_total_evidence="1 год опыта")  # проваливает must-have "опыт"
    raw_text = make_raw_text(weak.fields)
    strong_nice = dict(weak.fields, framework_next=True, external_api=True, ux_taste=True, llm_agents=True)
    weak_with_nice = CandidateProfile.from_raw("TEST", "Test", "V2", strong_nice)
    trace = decide_candidate(vacancies["V2"], weak_with_nice, raw_text)
    assert trace.decision.value == "REJECT", "сильные nice-to-have не должны перекрывать проваленный must-have"
