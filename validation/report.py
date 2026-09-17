"""
Task 4: ValidationIssue — единый список того, что не прошло проверку
(grounding сейчас, relevance — Task 6), с быстрым поиском по criterion_id.
Ничего не решает сам — только собирает факты для decision-уровня и отчёта.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ValidationIssue:
    criterion_id: str
    kind: str      # "ungrounded" | "not_relevant" | "relevance_insufficient"
    detail: str


@dataclass
class ValidationReport:
    issues: list = field(default_factory=list)

    def add(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)

    def for_criterion(self, criterion_id: str) -> list:
        return [i for i in self.issues if i.criterion_id == criterion_id]

    def as_dicts(self) -> list:
        return [{"criterion_id": i.criterion_id, "kind": i.kind, "detail": i.detail} for i in self.issues]
