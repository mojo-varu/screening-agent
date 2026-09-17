"""
Общая семантика статуса критерия — используется во всех трёх ролях
(engine/rules.py) и в decision.py.

Phase 2 (evidence-grounded evaluation): статус — четыре значения, ни одно из
которых не смешано со стоп-факторами (у тех — свой тип, StopFactorResult в
domain/evaluation.py, с полем triggered: bool, а не с этим enum — иначе
каждый потребитель вынужден был бы понимать, какие значения enum вообще
законны для стоп-фактора, а какие для критерия).

Ключевое структурное правило (Task 2 спецификации): критерий может получить
NOT_MET, только если у него есть хотя бы один evidence span, который его
прямо опровергает. Пустой evidence -> UNCLEAR, никогда не NOT_MET и не MET.
Это правило применяется в engine/rules.py при построении CriterionResult
(build_criterion), а не здесь — этот модуль только определяет словарь и
инфраструктуру (EvidenceSpan, worst()), не знает, откуда взялось значение.
"""
from dataclasses import dataclass, field
from enum import Enum


class CriterionStatus(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    UNCLEAR = "unclear"
    NOT_APPLICABLE = "not_applicable"


# "Мягкий" провал (bool3 "partial" — частичное/неполное соответствие,
# отличается от явного false) — decision.py использует именно эту строку,
# а не сам факт NOT_MET, чтобы решить RESERVE или REJECT. Общий тег, а не
# литерал в трёх местах (engine/rules.py, domain/decision.py) — иначе
# опечатка в одном из них тихо ломает hard/soft различение.
PARTIAL_PROVENANCE = "rule:partial_signal"


# Ярлыки для конечного пользователя (recruiter-facing).
STATUS_LABEL_RU = {
    CriterionStatus.MET: "выполнено",
    CriterionStatus.NOT_MET: "не выполнено",
    CriterionStatus.UNCLEAR: "не подтверждено — резюме не даёт однозначного ответа",
    CriterionStatus.NOT_APPLICABLE: "неприменимо",
}

# Серьёзность по возрастанию — используется в worst() для сведения нескольких
# сигналов (например ssr+meta_forms_responsive) в один критерий.
_SEVERITY = {
    CriterionStatus.MET: 0,
    CriterionStatus.NOT_APPLICABLE: 0,
    CriterionStatus.UNCLEAR: 1,
    CriterionStatus.NOT_MET: 2,
}


@dataclass(frozen=True)
class EvidenceSpan:
    """Task 1: цитата + её точное положение в исходном тексте резюме.
    text — это ФАКТИЧЕСКИЙ фрагмент raw_text[start:end], не то, что
    "хотела" процитировать модель — так гарантируется, что
    cv_text[span.start:span.end] == span.text ВСЕГДА, по построению, а не
    как факт, который можно случайно нарушить."""
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    text: str
    status: CriterionStatus
    evidence: tuple = ()          # tuple[EvidenceSpan, ...] — Task 1
    reason: str = ""              # Task 3: одно предложение, почему такой статус
    provenance: str = ""          # Task 3: каким механизмом получен статус, обязателен

    @property
    def evidence_text(self) -> str:
        """Удобство для рендеринга — склеенные тексты всех evidence spans."""
        return " / ".join(e.text for e in self.evidence) if self.evidence else ""


def worst(*statuses: CriterionStatus) -> CriterionStatus:
    """Сводит несколько статусов (уже вычисленных per-поле) в один — берётся
    наихудший. Раньше worst() принимал сырые значения и сам вызывал
    status_of(); теперь вызывающий код (engine/rules.py) явно строит статус
    через build_criterion для каждого под-сигнала и сводит готовые статусы —
    так провenance/evidence каждого под-сигнала остаются прослеживаемыми
    вплоть до момента свода, а не теряются внутри worst()."""
    return max(statuses, key=lambda s: _SEVERITY[s])
