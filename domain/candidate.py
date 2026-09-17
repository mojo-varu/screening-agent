"""
Кандидат — типизированный, провалидированный на границе объект, а не голый
dict, который каждая функция engine.py могла трактовать по-своему.

FIELD_SPECS тоже здесь: это схема, которую кандидат обязан соблюдать, и одно
и то же описание используется и для валидации (CandidateProfile.from_raw),
и для построения LLM-промпта в extractors/llm_extractor.py — схема кандидата
и схема извлечения это буквально одно и то же, поэтому не разносим по файлам.

КЛЮЧЕВОЙ АРХИТЕКТУРНЫЙ СДВИГ ПРОТИВ ПРЕДЫДУЩЕЙ ВЕРСИИ: раньше нормализация
("что делать, если LLM вернул null для списка") жила в отдельной функции
normalize_fields(), которую нужно было не забыть вызвать в нужном месте
extract.py/poc.py — и её пропуск как раз и уронил engine.py на живом Qwen.
Теперь эта проверка встроена в конструктор CandidateProfile.from_raw и
происходит один раз, при создании объекта — невозможно получить
CandidateProfile с None вместо списка, потому что такого объекта просто не
существует после конструктора.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


FIELD_SPECS = {
    "V1": [
        ("years_total", "int", "Сколько лет кандидат(ка) отработал(а) в роли BA или системного аналитика — ЦЕЛОЕ ЧИСЛО лет "
         "(например 0, 2, 5, 12), а НЕ true/false. НЕ отвечай на вопрос «выполнено ли требование 3+ года» — это отдельная "
         "проверка, которую делает не модель, а код после извлечения; здесь нужно просто число лет из текста"),
        ("requirements_authorship", "bool", "Сам(а) писал(а) ТРЕБОВАНИЯ и ПОЛЬЗОВАТЕЛЬСКИЕ СЦЕНАРИИ, а не только оформлял(а) готовое. "
         "ВАЖНО: 'постановка задачи для бэкенда/разработки' или 'писал(а) тикеты' — это НЕ то же самое, что требования и пользовательские сценарии; "
         "нужно явное упоминание именно требований/сценариев/ТЗ для конечного пользователя или продукта, а не техническая постановка для другой команды"),
        ("integrations_experience", "bool3", "Есть опыт работы с интеграциями (CRM/билетные/PMS — любой стек). 'partial' если делегировал(а) или работал(а) с лёгкими интеграциями"),
        ("russian_native", "bool", "Русский — рабочий/родной уровень (не A2/начальный). Верни true ТОЛЬКО если в резюме есть "
         "ЯВНАЯ фраза об уровне русского языка (например «русский — родной», «русский — рабочий», «русский язык: без кальки»), "
         "и evidence — это именно эта фраза. Если такой явной фразы нет — верни null, ДАЖЕ ЕСЛИ остальной текст резюме "
         "выглядит грамотным и связным по-русски: качество прозы резюме — это не то же самое, что явное заявление об уровне "
         "языка, и не является основанием для true. Общий текст резюме (описание опыта, стек, обязанности) НИКОГДА не "
         "является evidence для этого поля"),
        ("domain_match", "bool", "Домен: hospitality / недвижимость / ритейл"),
        ("bpmn", "bool", "Владение BPMN"),
        ("usm", "bool", "User Story Mapping"),
        ("english", "str_or_null", "Уровень английского, если указан (например 'B2'), иначе null"),
        ("work_format", "str", "Формат работы: 'hybrid' / 'remote_only' / 'office_only_5x2' и т.п."),
        ("salary_expectation", "int", "Зарплатные ожидания в рублях, числом"),
        ("stop_notes", "list[str]", "Список id сработавших стоп-факторов из: junior_only, finance_only, remote_other_tz"),
        ("weaknesses", "list[str]", "Явно упомянутые в резюме слабости/оговорки, короткими фразами"),
    ],
    "V2": [
        ("years_total", "int", "Сколько лет коммерческой разработки — ЦЕЛОЕ ЧИСЛО лет, а НЕ true/false"),
        ("stack_ts", "bool", "Есть TypeScript на боевых задачах"),
        ("stack_python", "bool3", "Есть Python на боевых задачах. 'partial' если только на уровне скриптов"),
        ("ssr", "bool", "Явно настраивал(а) SSR"),
        ("meta_forms_responsive", "bool3", "Мета-теги/формы/адаптив на боевых проектах"),
        ("git", "bool_or_null", "Явно упомянут Git, иначе null"),
        ("review", "bool_or_null", "Явно упомянуто код-ревью, иначе null"),
        ("deploy", "bool", "Есть самостоятельный деплой"),
        ("framework_next", "bool", "Next.js / Nuxt / Remix"),
        ("external_api", "bool_or_null", "Интеграции с внешними API, иначе null"),
        ("ux_taste", "bool_or_null", "Базовый UX-вкус, иначе null"),
        ("llm_agents", "bool_or_null", "Опыт с LLM-агентами, иначе null"),
        ("public_release", "bool3", "Есть публичный или описываемый релиз"),
        ("work_format", "str", "Формат работы"),
        ("salary_expectation", "int", "Зарплатные ожидания в рублях"),
        ("stop_notes", "list[str]", "id стоп-факторов из: markup_only, java_enterprise_only, no_releases"),
        ("weaknesses", "list[str]", "Явные слабости из текста резюме"),
    ],
    "V3": [
        ("years_total", "int", "Сколько лет именно UX/UI (НЕ графического дизайна вообще) — ЦЕЛОЕ ЧИСЛО лет, а НЕ true/false"),
        ("relevant_cases", "bool3", "Кейсы промо-сайтов или hospitality/luxury/девелопмент"),
        ("figma", "bool3", "Владение Figma"),
        ("design_system", "bool", "Опыт создания дизайн-систем"),
        ("responsive", "bool", "Опыт адаптивной вёрстки/дизайна"),
        ("explainability", "bool_or_null", "Явно умеет объяснить решения, иначе null если не упомянуто"),
        ("animation", "bool3", "Опыт анимации/motion"),
        ("3d_webgl", "bool_or_null", "Опыт постановки 3D/WebGL как задачи для разработчика (сама/сам не обязательно "
         "реализует — именно способность грамотно сформулировать такую задачу), иначе null если не упомянуто"),
        ("research", "bool3", "Опыт исследований/интервью"),
        ("ai_gen_only", "bool3", "Портфолио преимущественно на нейрогенерации без проектной рамки"),
        ("work_format", "str", "Формат работы"),
        ("salary_expectation", "int", "Зарплатные ожидания в рублях"),
        ("stop_notes", "list[str]", "id стоп-факторов из: graphic_design_only, mobile_only, ai_gen_only_risk"),
        ("weaknesses", "list[str]", "Явные слабости из текста резюме"),
    ],
}

# Поля, от которых напрямую зависит must-have/стоп-фактор — на них имеет
# смысл тратить эскалацию к более сильной модели при низкой уверенности.
DECISION_CRITICAL = {
    "V1": {"years_total", "requirements_authorship", "integrations_experience", "russian_native", "stop_notes"},
    "V2": {"years_total", "stack_ts", "stack_python", "ssr", "meta_forms_responsive", "deploy", "stop_notes"},
    "V3": {"years_total", "relevant_cases", "figma", "design_system", "responsive", "stop_notes"},
}


def _normalize(vacancy_id: str, raw: dict) -> dict:
    """Приводит сырые значения к безопасным типам ТОЛЬКО там, где иначе
    engine упадёт (список используется через `in`, int — в сравнении).
    Всё остальное (bool/bool3/*_or_null/str, и любые ключи вне схемы —
    например *_note поля с текстом-обоснованием) проходит как есть: engine
    уже корректно трактует None как GAP через criteria.status_of(), и
    насильно превращать None в False здесь означало бы тихо менять решение
    "нет данных" на "явный отказ" — это чинили и ловили регрессией ранее.

    Отдельный тип-баг: `isinstance(True, int)` — True в Python (bool — подкласс
    int), поэтому наивная проверка `not isinstance(val, (int, float))` НЕ
    ловит случай, когда экстрактор вернул bool вместо числа лет (реальный
    случай: Gemini однажды вернул years_total=False вместо years_total=2,
    судя по всему подменив "сколько лет" на "выполнено ли требование 3+
    года"). Здесь это ловится явно, а не молча пропускается как валидный int."""
    out = dict(raw)
    coerced = []
    for name, typ, _ in FIELD_SPECS.get(vacancy_id, []):
        if name not in out:
            continue
        val = out[name]
        if typ == "list[str]" and not isinstance(val, list):
            out[name] = []
            coerced.append(name)
        elif typ == "int" and (isinstance(val, bool) or not isinstance(val, (int, float))):
            out[name] = 0
            coerced.append(name)
    if coerced:
        out["_type_coerced_fields"] = list(raw.get("_type_coerced_fields") or []) + coerced
    return out


@dataclass(frozen=True)
class CandidateProfile:
    candidate_id: str
    name: str
    vacancy_id: str
    fields: dict  # провалидированные структурированные факты + свободные *_note поля

    def get(self, key, default=None):
        return self.fields.get(key, default)

    @classmethod
    def from_raw(cls, candidate_id: str, name: str, vacancy_id: str, raw: dict) -> "CandidateProfile":
        return cls(candidate_id, name, vacancy_id, _normalize(vacancy_id, raw))


def load_golden_candidates(path) -> dict:
    """path: fixtures/candidates_golden.json — эталонный, размеченный вручную набор."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for cid, c in raw.items():
        vacancy_id = c["primary_role"]
        fields = {k: v for k, v in c.items() if k not in ("name", "age", "city", "primary_role")}
        out[cid] = CandidateProfile.from_raw(cid, c["name"], vacancy_id, fields)
    return out


def load_resumes(resumes_dir) -> dict:
    """Читает .txt файлы (имя файла = id кандидата) — так же работает и на
    10 резюме, и на произвольном количестве, без изменений кода."""
    d = Path(resumes_dir)
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(d.glob("*.txt"))}
