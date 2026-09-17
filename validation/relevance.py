"""
Task 6 — единственная проверка, которая реально ловит "цитата дословна и из
этого резюме, но не о том": grounding (validation/grounding.py) этого не
может поймать в принципе, потому что цитата настоящая — только явное
судейское решение.

Судья видит ТОЛЬКО определение критерия и цитату — НЕ предложенный моделью
статус и НЕ остальной контекст резюме — иначе он может просто подтвердить
чужой вывод не глядя, а не оценить independently, доказывает ли именно эта
цитата именно этот критерий.

Опционально вызывается (не автоматически на каждый критерий каждого
кандидата — это отдельный LLM-вызов на каждую непустую evidence, и должно
включаться явно, а не тратить бюджет по умолчанию)."""
from extractors.providers import call_llm

VERDICTS = ("supports", "does_not_support", "insufficient")


def build_relevance_prompt(criterion_text: str, quote: str) -> str:
    return (
        "Является ли эта цитата подтверждением конкретно этого критерия? "
        "Не оценивай кандидата в целом, не угадывай его пользу для вакансии — "
        "ответь только про то, доказывает ли ИМЕННО ЭТА цитата ИМЕННО ЭТОТ "
        "критерий, ничего больше. Если цитата про смежную, но другую вещь "
        "(например упоминает участие в задаче, но не то же самое действие, "
        "которое требует критерий) — это does_not_support или insufficient, "
        "не supports.\n\n"
        f"Критерий: {criterion_text}\n"
        f"Цитата из резюме: «{quote}»\n\n"
        'Ответь ТОЛЬКО JSON вида: {"verdict": "supports" | "does_not_support" | "insufficient", '
        '"reason": "<одна короткая фраза по-русски>"}\n'
        "Без пояснений вне JSON, без markdown-обрамления."
    )


def judge_relevance(criterion_text: str, quote: str, provider: str, model: str) -> dict:
    """Один узкий вопрос судье на одну (критерий, цитата) пару. Возвращает
    {"verdict": ..., "reason": ...}; нераспознанный ответ трактуется как
    'insufficient' (Task 4's downgrade-only принцип: неуверенность судьи не
    может повысить статус, только понизить или оставить как есть)."""
    result = call_llm(build_relevance_prompt(criterion_text, quote), model, provider)
    verdict = result.get("verdict")
    if verdict not in VERDICTS:
        verdict = "insufficient"
    return {"verdict": verdict, "reason": result.get("reason", "")}


def apply_relevance_judge(must_have: tuple, provider: str, model: str, validation_report) -> tuple:
    """Прогоняет судью по каждому must-have критерию с непустым evidence;
    'does_not_support'/'insufficient' -> критерий понижается до UNCLEAR,
    provenance='judge:relevance' (Task 4's правило: только понижение, никогда
    не повышение статуса или confidence). Возвращает НОВЫЙ tuple — исходный
    must_have не мутируется."""
    import dataclasses
    from domain.criteria import CriterionStatus
    from validation.report import ValidationIssue

    out = []
    for m in must_have:
        if not m.evidence:
            out.append(m)
            continue
        quote = " / ".join(e.text for e in m.evidence)
        verdict = judge_relevance(m.text, quote, provider, model)
        if verdict["verdict"] in ("does_not_support", "insufficient"):
            validation_report.add(ValidationIssue(
                m.criterion_id,
                "not_relevant" if verdict["verdict"] == "does_not_support" else "relevance_insufficient",
                f"судья: {verdict['reason']} (цитата: {quote!r})",
            ))
            out.append(dataclasses.replace(
                m, status=CriterionStatus.UNCLEAR,
                reason=f"судья по релевантности: {verdict['reason']}",
                provenance="judge:relevance",
            ))
        else:
            out.append(m)
    return tuple(out)
