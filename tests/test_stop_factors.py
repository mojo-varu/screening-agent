"""
Стоп-факторы — это вето, а не ещё один must-have: проверяем, что срабатывание
стоп-фактора отклоняет кандидата ДАЖЕ когда все must-have формально закрыты,
и что перечисленные причины отказа именно те стоп-факторы, а не что-то ещё.

Phase 2: стоп-факторы больше не CriterionStatus — свой тип StopFactorResult
(domain/evaluation.py) с полем stop_factor_id (не id) и triggered: bool.
"""
from engine.evaluator import decide_candidate


def test_stop_factor_overrides_clean_must_have(vacancies, make_candidate, make_raw_text):
    """Изолированный случай: кандидат идеален по всем must-have, но триггерит
    стоп-фактор — ожидаем REJECT именно из-за него, не из-за провала must-have."""
    c = make_candidate("V2", stop_notes=["java_enterprise_only"],
                        stop_notes_evidence="только Java enterprise без веба")
    raw_text = make_raw_text(c.fields)
    trace = decide_candidate(vacancies["V2"], c, raw_text)
    assert trace.decision.value == "REJECT"
    assert all(m.status.value != "not_met" for m in trace.evaluation.must_have), \
        "must-have не должны были провалиться в этом тесте — reject обязан быть из-за стоп-фактора"
    assert len(trace.evaluation.stop_factors_triggered) == 1
    assert "Java enterprise" in trace.reason


def test_multiple_stop_factors_all_reported(vacancies, golden, resumes):
    """R06: 12 лет Java, хочет в fullstack, NDA без релизов — два независимых
    стоп-фактора одновременно, оба должны быть в trace, не только первый."""
    c = golden["R06"]
    trace = decide_candidate(vacancies["V2"], c, resumes["R06"])
    assert trace.decision.value == "REJECT"
    triggered_ids = {sf.stop_factor_id for sf in trace.evaluation.stop_factors_triggered}
    assert triggered_ids == {"java_enterprise_only", "no_releases"}


def test_no_stop_factor_no_veto(vacancies, make_candidate, make_raw_text):
    c = make_candidate("V1", stop_notes=[])
    raw_text = make_raw_text(c.fields)
    trace = decide_candidate(vacancies["V1"], c, raw_text)
    assert trace.decision.value == "TAKE"
    assert trace.evaluation.stop_factors_triggered == ()


def test_unknown_stop_note_id_is_ignored_not_crashed(vacancies, make_candidate, make_raw_text):
    """Если экстрактор вернёт id стоп-фактора, которого нет в этой вакансии
    (например, перепутал схему другой роли) — не должно падать, просто не
    засчитывается."""
    c = make_candidate("V1", stop_notes=["no_releases"])  # это id из V2, не из V1
    raw_text = make_raw_text(c.fields)
    trace = decide_candidate(vacancies["V1"], c, raw_text)
    assert trace.evaluation.stop_factors_triggered == ()
    assert trace.decision.value == "TAKE"
