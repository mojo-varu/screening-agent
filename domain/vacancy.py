"""
Вакансия — типизированная, загружается из fixtures/vacancies/roles.json.
Ничего не знает про кандидатов; must_have/nice_to_have здесь — это только
(id, текст), какие именно поля резюме за ними стоят решает engine/rules.py.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Criterion:
    id: str
    text: str


@dataclass(frozen=True)
class StopFactor:
    id: str
    text: str


@dataclass(frozen=True)
class Vacancy:
    id: str
    title: str
    salary_range: tuple  # (min, max), рублей
    must_have: tuple = field(default_factory=tuple)
    nice_to_have: tuple = field(default_factory=tuple)
    stop_factors: tuple = field(default_factory=tuple)


def _load_one(vid: str, raw: dict) -> Vacancy:
    return Vacancy(
        id=vid,
        title=raw["title"],
        salary_range=tuple(raw["salary_range"]),
        must_have=tuple(Criterion(c["id"], c["text"]) for c in raw.get("must_have", [])),
        nice_to_have=tuple(Criterion(c["id"], c["text"]) for c in raw.get("nice_to_have", [])),
        stop_factors=tuple(StopFactor(s["id"], s["text"]) for s in raw.get("stop_factors", [])),
    )


def load_vacancies(path) -> dict:
    """path: fixtures/vacancies/roles.json"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {vid: _load_one(vid, v) for vid, v in raw.items()}
