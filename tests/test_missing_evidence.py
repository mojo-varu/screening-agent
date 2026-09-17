"""
Реальные баги, пойманные вручную в ходе разработки — постоянная защита от
регрессии, а не разовое наблюдение в истории чата. Часть тестов здесь
обновлена в Phase 2 (evidence-grounded evaluation): два теста ниже
("does_not_crash") раньше ожидали REJECT там, где ПРОВЕРЯЛОСЬ только "не
падает" — с новым правилом "NOT_MET/MET требует evidence" честный результат
для нехватки данных — UNCLEAR, а не молчаливо предположенный провал; сами
тесты обновлены отражать это, поведение "не падает" не изменилось.
"""
import pytest

from domain.candidate import CandidateProfile
from domain.criteria import CriterionStatus
from engine.evaluator import decide_candidate


# --- Баг №1: LLM вернул null вместо [] для спискового поля -> TypeError ----

def test_none_in_list_field_does_not_crash(vacancies):
    """Живой Qwen вернул stop_notes=None, weaknesses=None вместо [] — раньше
    это падало на `sf['id'] in None` внутри eval_stop_factors. Теперь это
    защищено дважды и независимо: CandidateProfile.from_raw нормализует
    список при конструировании (domain/candidate.py), И eval_stop_factors
    использует `candidate.get(...) or []` (domain/evaluation.py) — так что
    даже если один из двух уровней защиты сломается, второй всё ещё держит.
    years_total=2 — реальное известное число, с evidence и заземляющим
    raw_text, поэтому решение остаётся REJECT (жёсткий NOT_MET по опыту),
    а не UNCLEAR — проверяем и "не падает", и корректный вердикт."""
    raw = {
        "years_total": 2, "years_total_evidence": "2 года опыта",
        "requirements_authorship": False, "integrations_experience": None,
        "russian_native": True, "russian_native_evidence": "русский родной",
        "salary_expectation": 210000,
        "stop_notes": None, "weaknesses": None,
    }
    c = CandidateProfile.from_raw("R02", "Test", "V1", raw)
    assert c.fields["stop_notes"] == []
    assert c.fields["weaknesses"] == []
    trace = decide_candidate(vacancies["V1"], c, "2 года опыта. русский родной.")  # не должно бросить исключение
    assert trace.decision.value == "REJECT"


def test_none_in_int_field_is_honestly_unclear_not_crash(vacancies):
    """years_total=None ломал бы прямое сравнение `>= 3` в rules.py, если бы
    не type-safety в domain/candidate.py._normalize(). Phase 2 update: когда
    экстрактор вообще не дал число (None, а не реальный 0), честный статус —
    UNCLEAR ('мы не знаем, сколько лет'), а не молчаливо предположенный
    REJECT по нулю лет — именно так, как это уже применяется к любому
    другому полю без evidence (rule:no_evidence). Регрессия, которую тест
    реально защищает — "не падает"; изменился только более честный вердикт."""
    c = CandidateProfile.from_raw("TEST", "Test", "V2",
                                   dict(years_total=None, stack_ts=True, stack_python=True,
                                        ssr=True, meta_forms_responsive=True, deploy=True,
                                        salary_expectation=280000, stop_notes=[], weaknesses=[]))
    trace = decide_candidate(vacancies["V2"], c, "")  # не должно бросить исключение
    experience = next(m for m in trace.evaluation.must_have if m.criterion_id == "experience")
    assert experience.status == CriterionStatus.UNCLEAR
    assert experience.provenance == "rule:no_evidence"


# --- Ожидаемое поведение при отсутствии evidence не меняется ---------------

def test_none_bool_field_is_unclear_not_not_met(vacancies, make_candidate, make_raw_text):
    """Раньше более широкая версия нормализации форсировала bool-поля с None
    в False — это тихо превращало 'нет данных' в 'явный отказ' и поменяло
    реальное решение (R10) при регрессионном прогоне. Здесь фиксируем
    ПРАВИЛЬНОЕ поведение: None на bool-поле — это UNCLEAR (без evidence),
    ЕСЛИ это единственная проблема — TAKE, не REJECT."""
    c = make_candidate("V2", deploy=None, deploy_evidence=None)
    raw_text = make_raw_text({k: v for k, v in c.fields.items() if k != "deploy_evidence"})
    trace = decide_candidate(vacancies["V2"], c, raw_text)
    deploy_result = next(m for m in trace.evaluation.must_have if m.criterion_id == "git_deploy")
    assert deploy_result.status == CriterionStatus.UNCLEAR
    assert trace.decision.value == "TAKE", "unclear без отрицательного сигнала не должен превращаться в REJECT"


# --- Баг №2: gap трактовался как pass даже на чужой роли -------------------

def test_within_role_unclear_is_take(vacancies, golden, resumes):
    """R04 (fullstack) не упоминает явно код-ревью — в рамках своей же
    профессии это UNCLEAR -> TAKE с пометкой, не блокирует решение."""
    c = golden["R04"]
    trace = decide_candidate(vacancies["V2"], c, resumes["R04"], cross_role=False)
    git_deploy = next(m for m in trace.evaluation.must_have if m.criterion_id == "git_deploy")
    assert git_deploy.status == CriterionStatus.UNCLEAR
    assert trace.decision.value == "TAKE"


def test_cross_role_unclear_is_reject(vacancies, golden, resumes):
    """Тот же принцип, что в пред. тесте, НЕ должен переноситься на чужую
    роль: резюме бизнес-аналитика (R01) не содержит TypeScript просто потому,
    что это резюме не про разработку — отсутствие данных здесь не должно
    трактоваться как компетенция. Критерий остаётся честно UNCLEAR (Task 2:
    NOT_MET требует опровергающую evidence, которой здесь нет) — REJECT
    получается через decision-level cross_role-политику, не переобозначение
    статуса критерия. Без этого разделения кросс-прогон
    (evidence_full_matrix.json) спуфился бы для всех кандидатов на все роли."""
    r01 = golden["R01"]
    assert r01.vacancy_id == "V1"
    trace = decide_candidate(vacancies["V2"], r01, resumes["R01"], cross_role=True)
    assert trace.decision.value == "REJECT"
    stack_result = next(m for m in trace.evaluation.must_have if m.criterion_id == "stack")
    assert stack_result.status == CriterionStatus.UNCLEAR


@pytest.mark.parametrize("candidate_id", ["R01", "R02", "R03"])
def test_full_matrix_never_lets_wrong_profession_pass(vacancies, golden, resumes, candidate_id):
    """Более широкая версия предыдущего теста: ни один BA-кандидат не должен
    формально пройти must-have чужой (не своей) роли за счёт unclear->take."""
    c = golden[candidate_id]
    for other_vacancy_id in ("V2", "V3"):
        trace = decide_candidate(vacancies[other_vacancy_id], c, resumes[candidate_id], cross_role=True)
        assert trace.decision.value != "TAKE", (
            f"{candidate_id} ({c.vacancy_id}) не должен получать TAKE на {other_vacancy_id}"
        )
