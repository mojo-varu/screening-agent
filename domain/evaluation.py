"""
Ролеагностичная часть оценки: стоп-факторы и зарплата — эти две проверки
одинаковы для всех трёх вакансий, поэтому живут здесь, а не в engine/rules.py
(которое знает только про ролеспецифичные must/nice поля).

Task 2: стоп-факторы НЕ используют CriterionStatus (met/not_met/unclear/
not_applicable) — у них свой тип, StopFactorResult, с полем triggered: bool.
Смешивать их в одном enum значило бы заставлять каждого потребителя понимать,
какие значения вообще законны для стоп-фактора (только True/False), а какие —
для критерия (четыре значения) — разные по смыслу множества, разные типы.
"""
from dataclasses import dataclass

from domain.candidate import CandidateProfile
from domain.criteria import EvidenceSpan
from domain.vacancy import Vacancy
from validation.grounding import locate


@dataclass(frozen=True)
class StopFactorResult:
    stop_factor_id: str
    text: str
    triggered: bool
    evidence: tuple = ()      # tuple[EvidenceSpan, ...]
    confidence: float = None
    reason: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    must_have: tuple
    nice_to_have: tuple
    stop_factors_triggered: tuple   # tuple[StopFactorResult, ...] — только triggered=True
    compensation_status: str  # "in_range" | "above_range" | "below_range" | "unknown"


def eval_stop_factors(vacancy: Vacancy, candidate: CandidateProfile, raw_text: str = None) -> tuple:
    """Экстрактор отдаёт один общий stop_notes_evidence на весь список
    сработавших id (схема этого не детализирует по каждому id отдельно) —
    поэтому одна и та же цитата (если заземлена) прикрепляется к каждому
    сработавшему стоп-фактору в этом прогоне. Это честнее, чем ничего не
    показывать, и не хуже, чем было до Phase 2 (там evidence у стоп-факторов
    не было вообще)."""
    notes = candidate.get("stop_notes") or []
    quote = candidate.get("stop_notes_evidence")
    conf = candidate.get("stop_notes_confidence")

    span = ()
    if quote and raw_text:
        gr = locate(raw_text, quote)
        if gr.grounded and gr.start >= 0:
            span = (EvidenceSpan(gr.text, gr.start, gr.end),)

    return tuple(
        StopFactorResult(
            sf.id, sf.text, True, span, conf,
            reason=f"экстрактор отметил стоп-фактор «{sf.id}» в stop_notes",
        )
        for sf in vacancy.stop_factors if sf.id in notes
    )


def eval_compensation(vacancy: Vacancy, candidate: CandidateProfile) -> str:
    """Task 7: ниже вилки — тоже не 'in_range', а отдельный, видимый сигнал
    (дешёвый найм или риск, что кандидат передумает на большей цифре), а не
    молчаливо смешанный с 'всё в порядке'."""
    salary = candidate.get("salary_expectation")
    if salary is None:
        return "unknown"
    lower, upper = vacancy.salary_range
    if salary > upper:
        return "above_range"
    if salary < lower:
        return "below_range"
    return "in_range"


def build_evaluation(vacancy: Vacancy, candidate: CandidateProfile, must: tuple, nice: tuple,
                      raw_text: str = None) -> EvaluationResult:
    return EvaluationResult(
        must_have=must,
        nice_to_have=nice,
        stop_factors_triggered=eval_stop_factors(vacancy, candidate, raw_text),
        compensation_status=eval_compensation(vacancy, candidate),
    )
