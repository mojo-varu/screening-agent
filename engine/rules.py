"""
Ролеспецифичные критерии: КАКИЕ поля резюме проверяются для каждой из трёх
вакансий. domain/evaluation.py и domain/decision.py этого не знают и знать
не должны — они работают с CriterionResult, а не с полями конкретной роли.

Phase 2 (evidence-grounded evaluation): единственная точка, где сырое
значение поля + его evidence-цитата превращаются в CriterionResult —
build_criterion(). Здесь же применяется ключевое правило Task 2:

    критерий может получить NOT_MET, только если есть evidence span,
    который его прямо опровергает; пустой/незаземлённый evidence -> UNCLEAR.

Заземление цитаты в исходном тексте резюме (Task 1: EvidenceSpan с
start/end) — через validation/grounding.py; неудачное заземление
регистрируется как ValidationIssue (Task 4), а не молча проглатывается.
"""
from domain.candidate import CandidateProfile
from domain.criteria import CriterionResult, CriterionStatus, EvidenceSpan, PARTIAL_PROVENANCE, worst
from domain.vacancy import Vacancy
from validation.grounding import locate
from validation.report import ValidationIssue, ValidationReport


def _years_word(n) -> str:
    """Русское согласование числительного с 'год': 1 год, 2-4 года, 5-20 лет,
    дальше по последней цифре (11-14 — всегда 'лет', это не считается)."""
    n = abs(int(n)) if n is not None else 0
    if 11 <= n % 100 <= 14:
        return "лет"
    last = n % 10
    if last == 1:
        return "год"
    if 2 <= last <= 4:
        return "года"
    return "лет"


def _text(vacancy: Vacancy, pool: str, crit_id: str) -> str:
    items = vacancy.must_have if pool == "must" else vacancy.nice_to_have
    return next(c.text for c in items if c.id == crit_id)


def build_criterion(criterion_id: str, text: str, raw_value, quote,
                     raw_text: str, validation_report: ValidationReport,
                     *, reason_override: str = None) -> CriterionResult:
    """Единственный путь построения CriterionResult из сырого значения поля.

    raw_value: True / False / "partial" / None / "not_stated" (или "gap"-
    эквиваленты) — семантика та же, что была у status_of() до Phase 2.
    quote: *_evidence строка (может быть None/пустой).
    raw_text: сырой текст резюме, нужен для заземления цитаты (Task 1/4).
    validation_report: сюда пишутся ValidationIssue при проваленном
    заземлении — вызывающий код (report.py/screen.py) может показать их
    отдельно, не только через provenance на самом критерии.
    """
    if raw_value in (None, "not_stated"):
        return CriterionResult(
            criterion_id, text, CriterionStatus.UNCLEAR, (),
            reason="в резюме нет явного сигнала по этому критерию",
            provenance="rule:no_evidence",
        )

    span = ()
    if quote:
        gr = locate(raw_text or "", quote)
        if not gr.grounded:
            validation_report.add(ValidationIssue(
                criterion_id, "ungrounded",
                f"цитата не найдена дословно в резюме: {quote!r}"))
            return CriterionResult(
                criterion_id, text, CriterionStatus.UNCLEAR, (),
                reason="цитата-обоснование не найдена дословно в резюме — сброшено, не принято на веру",
                provenance="validation:ungrounded_downgrade",
            )
        if gr.start >= 0:
            span = (EvidenceSpan(gr.text, gr.start, gr.end),)

    if not span:
        # Значение заявлено (True/False/partial), но evidence пуст или не
        # заземлён содержательно — симметрично применяем то же правило, что
        # Task 2 явно требует для NOT_MET, и к MET тоже: непроверяемое
        # утверждение честнее показать как UNCLEAR, чем поверить на слово.
        return CriterionResult(
            criterion_id, text, CriterionStatus.UNCLEAR, (),
            reason="значение указано, но без проверяемой цитаты-основания — недостаточно для решения",
            provenance="rule:no_evidence",
        )

    if raw_value is True:
        status = CriterionStatus.MET
        reason = reason_override or "резюме явно подтверждает критерий"
        provenance = "rule:explicit_true"
    elif raw_value is False:
        status = CriterionStatus.NOT_MET
        reason = reason_override or "резюме содержит прямое опровержение критерия"
        provenance = "rule:explicit_false"
    elif raw_value == "partial":
        status = CriterionStatus.NOT_MET
        reason = reason_override or "резюме показывает частичное/неполное соответствие — не провал, но не подтверждено полностью"
        provenance = PARTIAL_PROVENANCE
    else:
        status = CriterionStatus.UNCLEAR
        reason = "нераспознанное значение поля"
        provenance = "rule:unrecognized_value"

    return CriterionResult(criterion_id, text, status, span, reason=reason, provenance=provenance)


def combine_worst(criterion_id: str, text: str, *subs: CriterionResult) -> CriterionResult:
    """Сводит несколько под-критериев (например ssr+meta_forms_responsive)
    в один: статус — наихудший из под-статусов (используется и для "все
    обязательны" семантики — tools в V3, git_deploy в V2 — потому что если
    хотя бы один компонент UNCLEAR/NOT_MET, весь составной критерий не может
    быть уверенно MET). Evidence и provenance собираются от ВСЕХ
    под-критериев, чей статус совпал с итоговым — не теряем, откуда взялся
    вердикт."""
    status = worst(*(s.status for s in subs))
    contributing = [s for s in subs if s.status == status] or list(subs)
    spans = tuple(e for s in contributing for e in s.evidence)
    reason = "; ".join(f"{s.criterion_id}: {s.reason}" for s in contributing)

    # decision.py различает "мягкий" NOT_MET (partial -> RESERVE) от
    # "жёсткого" (explicit false -> REJECT) по ТОЧНОЙ строке provenance.
    # Если ВСЕ вклады в худший статус мягкие — составной критерий тоже
    # мягкий (иначе комбинирование трёх partial-сигналов внезапно давало бы
    # REJECT там, где каждый из них по отдельности давал бы только RESERVE).
    # Если хотя бы один вклад жёсткий — весь составной критерий жёсткий.
    if status == CriterionStatus.NOT_MET and all(s.provenance == PARTIAL_PROVENANCE for s in contributing):
        provenance = PARTIAL_PROVENANCE
    else:
        provenance = "combine:worst(" + ",".join(s.provenance for s in subs) + ")"

    return CriterionResult(criterion_id, text, status, spans, reason=reason, provenance=provenance)


def combine_any_met(criterion_id: str, text: str, *subs: CriterionResult) -> CriterionResult:
    """OR-семантика (стек: TypeScript ИЛИ Python — достаточно одного): MET,
    если хотя бы один под-критерий MET, иначе — обычная worst()-свёртка
    оставшихся. Раньше это было захардкожено инлайн в eval_must_have_v2;
    вынесено, потому что семантика "любой из" отличается от "все
    обязательны" (combine_worst) и должна быть явной, а не неявной веткой."""
    met = [s for s in subs if s.status == CriterionStatus.MET]
    if met:
        spans = tuple(e for s in met for e in s.evidence)
        reason = "; ".join(f"{s.criterion_id}: {s.reason}" for s in met)
        provenance = "combine:any_met(" + ",".join(s.provenance for s in subs) + ")"
        return CriterionResult(criterion_id, text, CriterionStatus.MET, spans, reason=reason, provenance=provenance)
    return combine_worst(criterion_id, text, *subs)


# ---------------------------------------------------------------------------
# MUST-HAVE — провал любого здесь -> REJECT (см. domain/decision.py)
# ---------------------------------------------------------------------------

def eval_must_have_v1(vacancy: Vacancy, c: CandidateProfile, raw_text: str, vr: ValidationReport) -> tuple:
    years_total = c.get("years_total")
    years_ok = (years_total or 0) >= 3
    experience = build_criterion("experience", _text(vacancy, "must", "experience"), years_ok,
                                  c.get("years_total_evidence"), raw_text, vr,
                                  reason_override=f"{years_total} {_years_word(years_total)} опыта в роли BA/системного аналитика")

    requirements_authorship = build_criterion(
        "requirements_authorship", _text(vacancy, "must", "requirements_authorship"),
        c.get("requirements_authorship", "not_stated"),
        c.get("requirements_authorship_evidence") or c.get("requirements_note"), raw_text, vr)

    integrations = build_criterion(
        "integrations", _text(vacancy, "must", "integrations"),
        c.get("integrations_experience", "not_stated"),
        c.get("integrations_experience_evidence") or c.get("integrations_note"), raw_text, vr)

    russian_quality = build_criterion(
        "russian_quality", _text(vacancy, "must", "russian_quality"),
        c.get("russian_native", "not_stated"),
        c.get("russian_native_evidence"), raw_text, vr)

    return (experience, requirements_authorship, integrations, russian_quality)


def eval_must_have_v2(vacancy: Vacancy, c: CandidateProfile, raw_text: str, vr: ValidationReport) -> tuple:
    def sub(field, value, quote):
        """Под-критерий для комбинирования (stack_ts/stack_python и т.п.) —
        текст берётся как имя поля, потому что у под-критерия нет
        собственного текста в fixtures/vacancies — он существует только
        внутри combine_*, наружу идёт текст СОСТАВНОГО критерия."""
        return build_criterion(field, field, value, quote, raw_text, vr)

    years_total = c.get("years_total")
    years_ok = (years_total or 0) >= 3
    experience = build_criterion("experience", _text(vacancy, "must", "experience"), years_ok,
                                  c.get("years_total_evidence"), raw_text, vr,
                                  reason_override=f"{years_total} {_years_word(years_total)} коммерческой разработки")

    ts = sub("stack_ts", c.get("stack_ts", "not_stated"), c.get("stack_ts_evidence"))
    py = sub("stack_python", c.get("stack_python", "not_stated"), c.get("stack_python_evidence"))
    stack = combine_any_met("stack", _text(vacancy, "must", "stack"), ts, py)

    ssr = sub("ssr", c.get("ssr", "not_stated"), c.get("ssr_evidence"))
    meta = sub("meta_forms_responsive", c.get("meta_forms_responsive", "not_stated"),
                c.get("meta_forms_responsive_evidence"))
    frontend_quality = combine_worst("frontend_quality", _text(vacancy, "must", "frontend_quality"), ssr, meta)

    git = sub("git", c.get("git", "not_stated"), c.get("git_evidence"))
    review = sub("review", c.get("review", "not_stated"), c.get("review_evidence"))
    deploy = sub("deploy", c.get("deploy", "not_stated"), c.get("deploy_evidence"))
    git_deploy = combine_worst("git_deploy", _text(vacancy, "must", "git_deploy"), git, review, deploy)

    return (experience, stack, frontend_quality, git_deploy)


def eval_must_have_v3(vacancy: Vacancy, c: CandidateProfile, raw_text: str, vr: ValidationReport) -> tuple:
    def sub(field, value, quote):
        return build_criterion(field, field, value, quote, raw_text, vr)

    years_total = c.get("years_total")
    years_ok = (years_total or 0) >= 3
    experience = build_criterion("experience", _text(vacancy, "must", "experience"), years_ok,
                                  c.get("years_total_evidence"), raw_text, vr,
                                  reason_override=f"{years_total} {_years_word(years_total)} именно в UX/UI")

    relevant_cases = build_criterion("relevant_cases", _text(vacancy, "must", "relevant_cases"),
                                      c.get("relevant_cases", "not_stated"),
                                      c.get("relevant_cases_evidence") or c.get("cases_note"),
                                      raw_text, vr)

    figma = sub("figma", c.get("figma", "not_stated"), c.get("figma_evidence"))
    design_system = sub("design_system", c.get("design_system", "not_stated"), c.get("design_system_evidence"))
    responsive = sub("responsive", c.get("responsive", "not_stated"), c.get("responsive_evidence"))
    tools = combine_worst("tools", _text(vacancy, "must", "tools"), figma, design_system, responsive)

    explainability = build_criterion("explainability", _text(vacancy, "must", "explainability"),
                                      c.get("explainability", "not_stated"),
                                      c.get("explainability_evidence") or c.get("explainability_note"),
                                      raw_text, vr)

    return (experience, relevant_cases, tools, explainability)


MUST_HAVE_EVALUATORS = {"V1": eval_must_have_v1, "V2": eval_must_have_v2, "V3": eval_must_have_v3}


# ---------------------------------------------------------------------------
# NICE-TO-HAVE — не влияет на решение (см. TECH_SPEC.md, "веса"), только
# информация для человека в отчёте. Тоже проходит через build_criterion, для
# единообразия рендеринга, но игнорируется decision.py целиком.
# ---------------------------------------------------------------------------

def _nice(vacancy: Vacancy, c: CandidateProfile, crit_id: str, field: str, raw_text: str, vr: ValidationReport) -> CriterionResult:
    return build_criterion(crit_id, _text(vacancy, "nice", crit_id), c.get(field, "not_stated"),
                            c.get(f"{field}_evidence"), raw_text, vr)


def eval_nice_to_have_v1(vacancy: Vacancy, c: CandidateProfile, raw_text: str, vr: ValidationReport) -> tuple:
    english = c.get("english")
    english_val = english in ("B2", "B2+", "C1", "C2") if english else "not_stated"
    return (
        _nice(vacancy, c, "domain", "domain_match", raw_text, vr),
        _nice(vacancy, c, "bpmn", "bpmn", raw_text, vr),
        _nice(vacancy, c, "usm", "usm", raw_text, vr),
        build_criterion("english_b2", _text(vacancy, "nice", "english_b2"), english_val,
                         c.get("english_evidence"), raw_text, vr,
                         reason_override=f"английский: {english}" if english else None),
    )


def eval_nice_to_have_v2(vacancy: Vacancy, c: CandidateProfile, raw_text: str, vr: ValidationReport) -> tuple:
    return (
        _nice(vacancy, c, "framework", "framework_next", raw_text, vr),
        _nice(vacancy, c, "external_api", "external_api", raw_text, vr),
        _nice(vacancy, c, "ux_taste", "ux_taste", raw_text, vr),
        _nice(vacancy, c, "llm_agents", "llm_agents", raw_text, vr),
    )


def eval_nice_to_have_v3(vacancy: Vacancy, c: CandidateProfile, raw_text: str, vr: ValidationReport) -> tuple:
    return (
        _nice(vacancy, c, "animation", "animation", raw_text, vr),
        _nice(vacancy, c, "3d_webgl", "3d_webgl", raw_text, vr),
        _nice(vacancy, c, "research", "research", raw_text, vr),
    )


NICE_TO_HAVE_EVALUATORS = {"V1": eval_nice_to_have_v1, "V2": eval_nice_to_have_v2, "V3": eval_nice_to_have_v3}
