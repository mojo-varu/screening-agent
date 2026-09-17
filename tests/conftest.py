import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from domain.candidate import CandidateProfile, load_golden_candidates, load_resumes
from domain.vacancy import load_vacancies

FIXTURES = ROOT / "fixtures"

# Phase 2: критерии не могут получить MET/NOT_MET без заземлённой evidence
# (см. engine/rules.py build_criterion) — синтетические кандидаты в тестах
# теперь несут *_evidence, и make_raw_text() собирает из них текст резюме,
# который реально СОДЕРЖИТ эти цитаты, чтобы заземление проходило.
_MAKE_DEFAULTS = {
    "V1": dict(years_total=5, years_total_evidence="5 лет опыта аналитиком",
               requirements_authorship=True, requirements_authorship_evidence="пишет требования и сценарии",
               integrations_experience=True, integrations_experience_evidence="вела интеграции с CRM",
               russian_native=True, russian_native_evidence="русский родной",
               domain_match=True, salary_expectation=250000, stop_notes=[], weaknesses=[]),
    "V2": dict(years_total=5, years_total_evidence="5 лет коммерческой разработки",
               stack_ts=True, stack_ts_evidence="TypeScript на боевых задачах",
               stack_python=True, stack_python_evidence="Python на проде",
               ssr=True, ssr_evidence="настраивал SSR",
               meta_forms_responsive=True, meta_forms_responsive_evidence="адаптив и формы готовы",
               git=True, git_evidence="использует Git",
               review=True, review_evidence="код-ревью в команде",
               deploy=True, deploy_evidence="сам деплоит",
               salary_expectation=280000, stop_notes=[], weaknesses=[]),
    "V3": dict(years_total=5, years_total_evidence="5 лет в UX/UI",
               relevant_cases=True, relevant_cases_evidence="кейсы промо-сайтов",
               figma=True, figma_evidence="владеет Figma",
               design_system=True, design_system_evidence="строила дизайн-системы",
               responsive=True, responsive_evidence="адаптивный дизайн",
               explainability=True, explainability_evidence="объясняет решения",
               salary_expectation=230000, stop_notes=[], weaknesses=[]),
}


@pytest.fixture
def vacancies():
    return load_vacancies(FIXTURES / "vacancies" / "roles.json")


@pytest.fixture
def golden():
    return load_golden_candidates(FIXTURES / "candidates_golden.json")


@pytest.fixture
def resumes():
    """candidate_id -> сырой текст резюме — нужен для заземления evidence
    у golden-кандидатов (без этого decide_candidate(..., raw_text="")
    честно понижает всё в UNCLEAR из-за rule:no_evidence/ungrounded)."""
    return load_resumes(FIXTURES / "resumes")


def _make_raw_text(fields: dict) -> str:
    quotes = [v for k, v in fields.items() if k.endswith("_evidence") and isinstance(v, str)]
    return ". ".join(quotes) + "."


@pytest.fixture
def make_candidate():
    def _make(vacancy_id: str, **overrides) -> CandidateProfile:
        fields = dict(_MAKE_DEFAULTS[vacancy_id])
        fields.update(overrides)
        return CandidateProfile.from_raw("TEST", "Test", vacancy_id, fields)
    return _make


@pytest.fixture
def make_raw_text():
    """Синтетический текст резюме, гарантированно содержащий все *_evidence
    цитаты кандидата — так синтетические (не golden) кандидаты в тестах
    проходят заземление, а не молча уходят в UNCLEAR."""
    return _make_raw_text
