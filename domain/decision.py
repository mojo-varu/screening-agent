"""
Решение принимается ТОЛЬКО здесь, и только из EvaluationResult — этот модуль
никогда не видит сырой текст резюме и никогда не вызывает LLM. Это дословно
реализация требования задания: "нужен отбор, который можно проверить".

Политика (в этом порядке):
  1. любой сработавший стоп-фактор -> REJECT, дальше не проверяем;
  2. любой "жёсткий" NOT_MET must-have (explicit_false) -> REJECT;
  3. кросс-роль: любой UNCLEAR must-have на чужой профессии -> REJECT (см.
     _cross_role_reject ниже — это решение ПОЛИТИКИ, не статус критерия:
     критерий остаётся честно UNCLEAR, мы не выдумываем опровергающую
     цитату, которой не существует, только чтобы получить NOT_MET);
  4. любой "мягкий" NOT_MET (provenance=rule:partial_signal) ИЛИ зарплата
     выше вилки -> RESERVE;
  5. любой UNCLEAR must-have (в рамках своей профессии) -> TAKE, но с
     пониженной уверенностью и явным списком неподтверждённого;
  6. иначе -> TAKE с высокой уверенностью.

nice_to_have на решение НЕ влияет — см. TECH_SPEC.md, раздел про "веса":
это осознанный выбор, а не то, что забыли реализовать.
"""
from dataclasses import dataclass
from enum import Enum

from domain.candidate import CandidateProfile
from domain.criteria import CriterionStatus, PARTIAL_PROVENANCE
from domain.evaluation import EvaluationResult
from domain.vacancy import Vacancy


class Decision(str, Enum):
    TAKE = "TAKE"
    RESERVE = "RESERVE"
    REJECT = "REJECT"


DECISION_RU = {Decision.TAKE: "берём", Decision.RESERVE: "в резерв", Decision.REJECT: "отказ"}


@dataclass(frozen=True)
class DecisionTrace:
    candidate_id: str
    vacancy_id: str
    vacancy_title: str
    decision: Decision
    reason: str
    concerns: tuple
    evaluation: EvaluationResult
    confidence: str = "высокая"  # высокая | средняя — см. decide(), не путать с LLM confidence полей

    @property
    def decision_ru(self) -> str:
        return DECISION_RU[self.decision]


def decide(vacancy: Vacancy, candidate: CandidateProfile, evaluation: EvaluationResult,
           cross_role: bool = False) -> DecisionTrace:
    must = evaluation.must_have

    hard_fails = [m for m in must if m.status == CriterionStatus.NOT_MET and m.provenance != PARTIAL_PROVENANCE]
    soft_fails = [m for m in must if m.status == CriterionStatus.NOT_MET and m.provenance == PARTIAL_PROVENANCE]
    unclear = [m for m in must if m.status == CriterionStatus.UNCLEAR]

    stop = evaluation.stop_factors_triggered
    if stop:
        decision = Decision.REJECT
        reason = "Сработал стоп-фактор: " + "; ".join(s.text for s in stop)
        confidence = "высокая"
    elif hard_fails:
        decision = Decision.REJECT
        reason = "Не выполнен must-have: " + "; ".join(m.text for m in hard_fails)
        confidence = "высокая"
    elif cross_role and unclear:
        # Внутри заявленной профессии кандидата UNCLEAR не блокирует TAKE
        # (см. правило ниже) — но это НЕ действует на чужой роли: отсутствие
        # данных о чужой профессии — это отсутствие подтверждения, а не
        # компетенция. КРИТЕРИЙ остаётся честно UNCLEAR (не NOT_MET) —
        # правило Task 2 требует опровергающую evidence для NOT_MET, которой
        # на чужой роли просто нет. REJECT здесь — решение ПОЛИТИКИ decide(),
        # а не переобозначение факта.
        decision = Decision.REJECT
        reason = "На чужой профессии нет подтверждения: " + "; ".join(m.text for m in unclear)
        confidence = "высокая"
    elif soft_fails or evaluation.compensation_status == "above_range":
        decision = Decision.RESERVE
        reasons = [m.text for m in soft_fails]
        if evaluation.compensation_status == "above_range":
            reasons.append("ожидания по зарплате выше вилки")
        reason = "Требует уточнения: " + "; ".join(reasons)
        confidence = "средняя"
    elif unclear:
        decision = Decision.TAKE
        reason = (f"Must-have не провалены и не частичны; {len(unclear)} из них "
                  f"не подтверждены цитатой из резюме (см. критерии ниже) — "
                  f"стоп-факторов нет, зарплата в вилке.")
        confidence = "средняя"
    else:
        decision = Decision.TAKE
        reason = "Все must-have подтверждены резюме явно, стоп-факторов нет, зарплата в вилке."
        confidence = "высокая"

    concerns = list(candidate.get("weaknesses") or [])
    concerns += [f"требует проверки (нет подтверждающей цитаты): {m.text}" for m in unclear]

    return DecisionTrace(
        candidate_id=candidate.candidate_id, vacancy_id=vacancy.id, vacancy_title=vacancy.title,
        decision=decision, reason=reason, concerns=tuple(concerns), evaluation=evaluation,
        confidence=confidence,
    )
