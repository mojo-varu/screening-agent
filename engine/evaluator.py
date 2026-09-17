"""
Единственное место, которое знает про ВСЕ три модуля сразу: rules.py (какие
поля смотреть), evaluation.py (стоп-факторы/зарплата) и decision.py
(политика решения). Сам не содержит ни одного правила — только сборку.

Phase 2: каждой оценке требуется raw_text (сырой текст резюме) — без него
evidence нельзя заземлить (Task 1/4), критерии будут UNCLEAR с
provenance=rule:no_evidence не потому что данных нет, а потому что негде
проверить цитату. raw_text либо приходит от live-экстракции (screen.py,
extract.py уже держат его в руках), либо загружается из
fixtures/resumes/<id>.txt для golden-набора (report.py).
"""
from domain.candidate import CandidateProfile
from domain.decision import DecisionTrace, decide
from domain.evaluation import build_evaluation
from domain.vacancy import Vacancy
from engine.rules import MUST_HAVE_EVALUATORS, NICE_TO_HAVE_EVALUATORS
from validation.report import ValidationReport


def evaluate(vacancy: Vacancy, candidate: CandidateProfile, raw_text: str, vr: ValidationReport = None):
    vr = vr if vr is not None else ValidationReport()
    must = MUST_HAVE_EVALUATORS[vacancy.id](vacancy, candidate, raw_text, vr)
    nice = NICE_TO_HAVE_EVALUATORS[vacancy.id](vacancy, candidate, raw_text, vr)
    return build_evaluation(vacancy, candidate, must, nice, raw_text), vr


def decide_candidate(vacancy: Vacancy, candidate: CandidateProfile, raw_text: str = "",
                      cross_role: bool = False, vr: ValidationReport = None) -> DecisionTrace:
    evaluation, _vr = evaluate(vacancy, candidate, raw_text, vr)
    return decide(vacancy, candidate, evaluation, cross_role=cross_role)


def decide_candidate_with_validation(vacancy: Vacancy, candidate: CandidateProfile, raw_text: str = "",
                                      cross_role: bool = False) -> tuple:
    """Как decide_candidate, но дополнительно возвращает ValidationReport —
    нужен вызывающему коду (screen.py), который хочет показать, что именно
    не прошло заземление, а не только итоговый статус критериев."""
    vr = ValidationReport()
    evaluation, vr = evaluate(vacancy, candidate, raw_text, vr)
    trace = decide(vacancy, candidate, evaluation, cross_role=cross_role)
    return trace, vr


def run_primary(vacancies: dict, candidates: dict, resumes: dict = None) -> list:
    """Каждый кандидат оценивается на роль, соответствующую заявленной в
    резюме профессии (candidate.vacancy_id). resumes: candidate_id -> сырой
    текст резюме (для заземления evidence); без него критерии уйдут в
    UNCLEAR/no_evidence, даже если *_evidence проставлен в golden-наборе."""
    resumes = resumes or {}
    return [decide_candidate(vacancies[c.vacancy_id], c, resumes.get(cid, ""))
            for cid, c in candidates.items()]


def run_full_matrix(vacancies: dict, candidates: dict, resumes: dict = None) -> list:
    """Кросс-проверка: каждый кандидат — через все вакансии, не только свою.
    Ловит правила, подогнанные под ожидаемых кандидатов, а не под принцип —
    см. tests/test_missing_evidence.py::test_cross_role_gap_is_not_pass."""
    resumes = resumes or {}
    out = []
    for cid, c in candidates.items():
        raw_text = resumes.get(cid, "")
        for vid, vacancy in vacancies.items():
            out.append(decide_candidate(vacancy, c, raw_text, cross_role=(vid != c.vacancy_id)))
    return out
