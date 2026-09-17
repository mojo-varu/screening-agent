"""
Единственный слой, которому разрешено вызывать LLM. Вход — сырой текст
резюме, выход — валидированный domain.candidate.CandidateProfile (через
CandidateProfile.from_raw, где и происходит нормализация типов — см.
domain/candidate.py). engine/ этот модуль не импортирует и про него не знает.
"""
import hashlib
import json
import random
import re
from pathlib import Path

from domain.candidate import CandidateProfile, FIELD_SPECS, DECISION_CRITICAL
from extractors.providers import MODELS, call_llm

CONFIDENCE_THRESHOLD = 0.7


def build_prompt(vacancy_id: str, candidate_id: str, raw_text: str, only_fields=None) -> str:
    specs = FIELD_SPECS[vacancy_id]
    if only_fields:
        specs = [s for s in specs if s[0] in only_fields]
    field_lines = "\n".join(f'  - "{n}" ({t}): {i}' for n, t, i in specs)
    schema_fields = ",\n".join(
        f'    "{n}": <значение>, "{n}_confidence": <0..1>, "{n}_evidence": <дословная цитата или null>'
        for n, _, _ in specs
    )
    return (
        "Ты извлекаешь факты из текста резюме в строго заданную JSON-схему. "
        "Не оценивай кандидата, не делай вывод о найме — только извлекай то, что явно "
        "написано или прямо следует из текста. Не придумывай фактов, которых нет в тексте, "
        "и не обобщай сильнее, чем позволяет текст (например «делал брифы для интеграции» — "
        "это не то же самое, что «вёл интеграцию»; сохраняй эту разницу).\n\n"
        "ПРАВИЛО, СВЯЗЫВАЮЩЕЕ значение и evidence — обязательно к соблюдению:\n"
        "  - Если в резюме ЕСТЬ предложение, относящееся к полю — верни значение (true/false/"
        "partial) И *_evidence — ОБЯЗАТЕЛЬНУЮ дословную цитату этого предложения.\n"
        "  - Если в резюме НЕТ ничего по теме поля — верни ЗНАЧЕНИЕ null И *_evidence null. "
        "Отсутствие темы в резюме — это тоже утверждение ('в этом резюме об этом ничего нет'), "
        "и его нужно вернуть явно, а не гадать true/false наугад.\n"
        "  - ЗАПРЕЩЕНО возвращать true или false с *_evidence = null — если значение не null, "
        "цитата обязана быть. Формально bool3-поля используют false при отсутствии позитивного "
        "сигнала — но и тогда, если в тексте есть релевантное (хоть и негативное) предложение, "
        "процитируй именно его; если по теме вообще ничего нет — используй null, а не false.\n\n"
        "ТРЕБОВАНИЯ К ЦИТАТЕ (*_evidence), когда она не null:\n"
        "  - дословный фрагмент, скопированный символ-в-символ из резюме — без перефразирования, "
        "без added слов, без многоточий (...) и без склейки двух несоседних предложений в одну "
        "цитату — цитата обязана быть НЕПРЕРЫВНЫМ фрагментом исходного текста;\n"
        "  - ФИО кандидата, возраст, город или другая идентифицирующая информация НЕ являются "
        "содержательным evidence ни для какого поля, кроме буквально поля о ФИО/городе.\n\n"
        f"Резюме кандидата {candidate_id}:\n{raw_text}\n\n"
        f"Извлеки поля:\n{field_lines}\n\n"
        f"Ответь ТОЛЬКО JSON вида:\n{{\n{schema_fields}\n}}\n"
        "Без пояснений, без markdown-обрамления."
    )


def build_role_prompt(candidate_id: str, raw_text: str, vacancies: dict) -> str:
    role_lines = "\n".join(
        f'  - "{vid}" ({v.title}): ' + "; ".join(c.text for c in v.must_have)
        for vid, v in vacancies.items()
    )
    return (
        "Ты определяешь, на какую из вакансий лучше всего подходит кандидат по тексту "
        "резюме — по заявленной профессии/специализации, а не по формальному совпадению "
        "отдельных навыков. Выбери ровно один id вакансии из списка. Если резюме не "
        "подходит уверенно ни под одну — всё равно выбери наиболее близкую и поставь "
        "низкую confidence.\n\n"
        f"Резюме кандидата {candidate_id}:\n{raw_text}\n\n"
        f"Вакансии:\n{role_lines}\n\n"
        'Ответь ТОЛЬКО JSON вида: {"role": "<id вакансии>", "confidence": <0..1>, '
        '"reason": "<кратко, почему именно эта вакансия>"}\n'
        "Поле reason пиши строго на русском языке, даже если резюме или названия "
        "вакансий смешаны с английскими терминами. Без пояснений вне JSON, без "
        "markdown-обрамления."
    )


def classify_role(candidate_id: str, raw_text: str, vacancies: dict,
                   provider: str = "ollama", model_override: str = None) -> dict:
    """Дешёвый классификационный проход перед основной экстракцией — закрывает
    пробел, явно зафиксированный в README ("Как это масштабируется"): раньше
    primary_role брался из golden-набора, а не определялся по тексту резюме.
    Использует ту же cheap-модель провайдера, что и Stage 1 — отдельная
    архитектура для этого не нужна, только ещё один вызов call_llm."""
    model = model_override or MODELS[provider]["cheap"]
    result = call_llm(build_role_prompt(candidate_id, raw_text, vacancies), model, provider)
    role = result.get("role")
    if role not in vacancies:
        role = None
    return {"role": role, "confidence": result.get("confidence"), "reason": result.get("reason", "")}


def _mock_call(vacancy_id: str, golden_fields: dict, only_fields, noise: float) -> dict:
    """Эмулирует ответ модели из golden-профиля, с намеренным шумом — для
    тестирования харнесса без сети/ключа. Эскалация (noise=0) чинит шум
    лишь частично (noise*0.25), не полностью — иначе decision-level
    agreement никогда бы не падал ни при каком уровне шума (см. tests)."""
    specs = [s for s in FIELD_SPECS[vacancy_id] if not only_fields or s[0] in only_fields]
    out = {}
    for name, typ, _ in specs:
        val = golden_fields.get(name)
        conf = round(random.uniform(0.85, 0.99), 2)
        if random.random() < noise:
            conf = round(random.uniform(0.2, 0.55), 2)
            if typ == "bool":
                val = not bool(val) if isinstance(val, bool) else True
            elif typ == "int":
                val = int(val) + random.choice([-2, -1, 1, 2]) if isinstance(val, (int, float)) else 0
        out[name] = val
        out[f"{name}_confidence"] = conf
    return out


def _normalize_for_match(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _evidence_is_verbatim(raw_text: str, evidence: str) -> bool:
    """Деталь Stage 1: evidence обязан быть дословным (с точностью до
    пробелов/регистра) фрагментом самого резюме — так ловятся придуманные
    или переформулированные цитаты (например ФИО+город, выданные за
    подтверждение уровня языка). НЕ ловит случай, когда цитата дословна, но
    не подтверждает поле по смыслу (типа «постановка для бэкенда» ≠
    «требования и сценарии») — это лечится формулировкой полей в
    domain/candidate.py FIELD_SPECS, не проверкой здесь."""
    if not evidence:
        return True
    return _normalize_for_match(evidence) in _normalize_for_match(raw_text)


# Поля, для которых evidence обязан содержать хотя бы одно слово-маркер —
# иначе он, скорее всего, "притянут" из не относящегося к полю текста, даже
# если дословно взят из резюме (реальный случай: модель процитировала целый
# абзац про опыт работы как "доказательство" уровня русского языка — цитата
# была дословной, поэтому verbatim-проверка её пропускала, но по смыслу она
# не о языке вообще). Список намеренно узкий — только там, где баг реально
# наблюдался, а не превентивно для всех полей.
_EVIDENCE_KEYWORD_REQUIREMENTS = {
    "russian_native": ("русск", "язык", "родн", "рабоч", "грамот", "калек", "техническ"),
}


def _evidence_has_required_keyword(field_name: str, evidence: str) -> bool:
    keywords = _EVIDENCE_KEYWORD_REQUIREMENTS.get(field_name)
    if not keywords:
        return True
    low = _normalize_for_match(evidence)
    return any(k in low for k in keywords)


def _scrub_unverified_evidence(fields: dict, specs: list, raw_text: str) -> list:
    """Провайдер-агностичный gate: для каждого поля со своим *_evidence
    проверяет (а) дословность против исходного текста резюме и (б), для
    полей из _EVIDENCE_KEYWORD_REQUIREMENTS, наличие тематического
    слова-маркера в самой цитате. Если любая проверка не прошла — И значение,
    И evidence сбрасываются в None, чтобы domain/criteria.status_of()
    трактовал поле как GAP (нет данных), а не как ложно подтверждённый факт.
    Работает одинаково для любого провайдера, потому что оперирует только уже
    полученным JSON + сырым текстом резюме."""
    rejected = []
    for name, _typ, _desc in specs:
        ev_key = f"{name}_evidence"
        evidence = fields.get(ev_key)
        if not evidence:
            continue
        valid = _evidence_is_verbatim(raw_text, evidence) and _evidence_has_required_keyword(name, evidence)
        if not valid:
            fields[name] = None
            fields[ev_key] = None
            rejected.append(name)
    return rejected


class ExtractionCache:
    """Кеш по хэшу (вакансия + текст резюме + модель) — повторный прогон по
    тем же резюме не платит за LLM повторно. Интерфейс — `dict`-подобный, при
    реальном масштабе меняется на SQLite/Redis без изменений вызывающего кода."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @staticmethod
    def key(vacancy_id, candidate_id, raw_text, model):
        h = hashlib.sha256(f"{vacancy_id}|{raw_text}|{model}".encode()).hexdigest()[:16]
        return f"{candidate_id}:{h}"

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_candidate(vacancy_id: str, candidate_id: str, name: str, raw_text: str,
                       provider: str = "ollama", mock: bool = False, mock_noise: float = 0.0,
                       golden_fields: dict = None, cache: ExtractionCache = None,
                       model_override: str = None) -> CandidateProfile:
    cheap_model = model_override or MODELS[provider]["cheap"]
    strong_model = model_override or MODELS[provider]["strong"]
    # Task 5A: "эскалация" на ту же самую модель — это повторный запрос, а не
    # эскалация (переспрашивать модель у самой себя не даёт независимого
    # сигнала). Если для провайдера не настроена ДЕЙСТВИТЕЛЬНО другая, более
    # сильная модель — эскалация отключается целиком и это явно фиксируется,
    # а не тихо превращается в повторный вызов с тем же результатом.
    escalation_available = strong_model != cheap_model

    ckey = ExtractionCache.key(vacancy_id, candidate_id, raw_text, cheap_model) if cache else None
    if cache and not mock:
        cached = cache.get(ckey)
        if cached is not None:
            return CandidateProfile.from_raw(candidate_id, name, vacancy_id, cached)

    if mock:
        result = _mock_call(vacancy_id, golden_fields or {}, None, mock_noise)
    else:
        result = call_llm(build_prompt(vacancy_id, candidate_id, raw_text), cheap_model, provider)

    critical = DECISION_CRITICAL[vacancy_id]
    low_conf_critical = [
        f for f, _, _ in FIELD_SPECS[vacancy_id]
        if f in critical and result.get(f"{f}_confidence", 1.0) < CONFIDENCE_THRESHOLD
    ]
    escalated = []
    if low_conf_critical and escalation_available:
        if mock:
            refined = _mock_call(vacancy_id, golden_fields or {}, low_conf_critical, noise=mock_noise * 0.25)
        else:
            refined = call_llm(build_prompt(vacancy_id, candidate_id, raw_text, only_fields=low_conf_critical),
                                strong_model, provider)
        result.update(refined)
        escalated = low_conf_critical

    # *_confidence больше НЕ вырезаются: нужны в evidence-JSON и в отчёте для
    # честной "уверенность по полю" (см. правки screen.py).
    fields = dict(result)

    # Minor fix: confidence на null-значении бессмысленна ("1.0 уверен, что
    # ничего не знаю" — противоречие) — не полагаемся на то, что модель сама
    # это соблюдёт (просили в промпте, но промпт-договорённость не гарантия),
    # обнуляем детерминированно здесь.
    for name, _typ, _desc in FIELD_SPECS[vacancy_id]:
        if fields.get(name) is None:
            fields[f"{name}_confidence"] = None

    rejected = _scrub_unverified_evidence(fields, FIELD_SPECS[vacancy_id], raw_text) if not mock else []

    # Task 5B: confidence не может САМА "вылечить" пустой evidence. Раньше
    # эскалация могла вернуть высокую confidence при evidence=null (реальный
    # случай: integrations_experience ушло с низкой confidence на эскалацию
    # и вернулось с confidence=0.9, но evidence так и остался null) — тогда
    # _needs_human_review молча становился False, хотя поле по-прежнему
    # ничем не подтверждено. Здесь это заблокировано структурно: любое
    # decision-critical поле без evidence (и не отклонённое отдельно через
    # rejected, чтобы не задваивать причину) требует ревью НЕЗАВИСИМО от
    # заявленной моделью confidence.
    empty_evidence_critical = [
        f for f, _, _ in FIELD_SPECS[vacancy_id]
        if f in critical and f not in rejected
        and fields.get(f) not in (None, "not_stated")
        and not fields.get(f"{f}_evidence")
    ]

    still_low_conf = [f for f in escalated if result.get(f"{f}_confidence", 1.0) < CONFIDENCE_THRESHOLD]
    needs_review_fields = sorted(set(still_low_conf) | set(empty_evidence_critical))

    fields["_escalated_fields"] = escalated
    fields["_model_primary"] = cheap_model
    fields["_provider"] = provider
    if low_conf_critical and not escalation_available:
        fields["_escalation_disabled_reason"] = (
            f"поля {low_conf_critical} требовали эскалации (низкая уверенность), но для провайдера "
            f"'{provider}' не настроена отдельная более сильная модель (strong == cheap == {cheap_model}) — "
            "эскалация пропущена, а не выполнена повторным запросом к той же модели"
        )
    if escalated:
        fields["_model_escalation"] = strong_model
        fields["_escalation_reason"] = (
            f"поля {escalated} переэкстрагированы моделью {strong_model}: "
            f"уверенность после первого прохода была ниже порога {CONFIDENCE_THRESHOLD}"
        )
    if rejected:
        fields["_evidence_rejected_fields"] = rejected
        fields["_evidence_rejected_reason"] = (
            f"для полей {rejected} цитата-evidence не найдена дословно в тексте резюме — "
            "значение сброшено в 'нет данных', а не принято на веру"
        )
    if empty_evidence_critical:
        fields["_empty_evidence_critical_fields"] = empty_evidence_critical
        fields["_empty_evidence_critical_reason"] = (
            f"поля {empty_evidence_critical} влияют на решение, но пришли без evidence-цитаты — "
            "confidence модели для них не учитывается, требуется проверка"
        )
    fields["_needs_human_review"] = bool(needs_review_fields)
    if needs_review_fields:
        fields["_human_review_reason"] = f"остаются непроверенными: {needs_review_fields}"

    if cache and not mock:
        cache.set(ckey, fields)

    return CandidateProfile.from_raw(candidate_id, name, vacancy_id, fields)
