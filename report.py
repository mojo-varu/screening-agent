"""
CLI поверх domain/ + engine/ — сам ничего не решает, только оркестрирует
загрузку fixtures, прогон через движок и запись результатов на диск.
Требует только стандартную библиотеку Python 3.

Phase 2 (evidence-grounded evaluation, Task 0/1): каждый кандидат — это ДВА
файла в screening_results/: <id>.evidence.json (три слоя: extraction ->
criteria -> decision, плюс validation) и <id>.explain.md (рендерится ИЗ
этого JSON, а не из живых Python-объектов параллельно — иначе .md и .json
могут разойтись). Эти же функции сборки/рендеринга используются screen.py —
одна точка правды на оба входа (golden-набор здесь, live-экстракция там).

Запуск: python3 report.py
Пишет: screening_results/<id>.evidence.json, screening_results/<id>.explain.md
       для каждого golden-кандидата, report.md (сводная таблица),
       evidence_full_matrix.json (кросс-прогон)
"""
import json
from pathlib import Path

from domain.candidate import load_golden_candidates, load_resumes
from domain.decision import Decision
from domain.vacancy import load_vacancies
from engine.evaluator import decide_candidate_with_validation, run_full_matrix

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
OUTPUT_DIR = ROOT / "screening_results"

DECISION_EMOJI = {Decision.TAKE: "✅", Decision.RESERVE: "⏳", Decision.REJECT: "❌"}


# ---------------------------------------------------------------------------
# Сериализация: dataclass-объекты движка -> обычные dict/list для JSON.
# ---------------------------------------------------------------------------

def serialize_evidence_span(span) -> dict:
    return {"text": span.text, "start": span.start, "end": span.end}


def serialize_criterion(m) -> dict:
    return {
        "criterion_id": m.criterion_id,
        "text": m.text,
        "status": m.status.value,
        "evidence": [serialize_evidence_span(e) for e in m.evidence],
        "reason": m.reason,
        "provenance": m.provenance,
    }


def serialize_stop_factor(sf) -> dict:
    return {
        "stop_factor_id": sf.stop_factor_id,
        "text": sf.text,
        "triggered": sf.triggered,
        "evidence": [serialize_evidence_span(e) for e in sf.evidence],
        "confidence": sf.confidence,
        "reason": sf.reason,
    }


def serialize_decision(trace) -> dict:
    return {
        "decision": trace.decision.value,
        "decision_ru": trace.decision_ru,
        "reason": trace.reason,
        "concerns": list(trace.concerns),
        "confidence": trace.confidence,
    }


def serialize_validation(vr) -> dict:
    return {"issues": vr.as_dicts()}


def build_artifact(candidate_id: str, source_file: str, role_classification: dict,
                    extraction_fields: dict, trace, vr) -> dict:
    """Единственная сборка трёхслойного артефакта (Task 0/1): extraction ->
    criteria -> decision, плюс validation. decision считается ТОЛЬКО из
    criteria (уже вычислено в trace до вызова этой функции — она не решает
    ничего сама, только собирает в одну структуру для сохранения/рендеринга)."""
    ev = trace.evaluation
    return {
        "candidate_id": candidate_id,
        "source_file": source_file,
        "role_classification": role_classification,
        "extraction": extraction_fields,
        "criteria": {
            "must_have": [serialize_criterion(m) for m in ev.must_have],
            "nice_to_have": [serialize_criterion(m) for m in ev.nice_to_have],
        },
        "stop_factors": [serialize_stop_factor(sf) for sf in ev.stop_factors_triggered],
        "compensation_status": ev.compensation_status,
        "decision": serialize_decision(trace),
        "validation": serialize_validation(vr),
    }


# ---------------------------------------------------------------------------
# Рендеринг .md — ТОЛЬКО из уже собранного artifact dict, никаких live-объектов.
# ---------------------------------------------------------------------------

_STATUS_LABEL_RU = {
    "met": "выполнено",
    "not_met": "не выполнено",
    "unclear": "не подтверждено — резюме не даёт однозначного ответа",
    "not_applicable": "неприменимо",
}


def _evidence_text(evidence_list: list) -> str:
    if not evidence_list:
        return "нет цитаты из резюме"
    return " / ".join(f"«{e['text']}»" for e in evidence_list)


def render_markdown_from_artifact(artifact: dict, vacancy_title: str = "") -> str:
    lines = [f"# Скрининг: {artifact['candidate_id']}", "", f"Источник: `{artifact['source_file']}`", ""]

    rc = artifact["role_classification"]
    role = rc.get("role")
    if role:
        lines.append(f"Рассмотрена на: {role}" + (f" ({vacancy_title})" if vacancy_title else ""))
    else:
        lines.append("Роль не определена")
    lines.append(f"Определение роли — уверенность {rc.get('confidence')}: {rc.get('reason')}")
    lines.append("")

    dec = artifact["decision"]
    lines.append(f"## Решение: {dec['decision_ru'].upper()} (уверенность: {dec['confidence']})")
    lines.append("")
    lines.append(f"**Почему:** {dec['reason']}")
    lines.append("")

    lines.append("**Must-have:**")
    for m in artifact["criteria"]["must_have"]:
        label = _STATUS_LABEL_RU.get(m["status"], m["status"])
        lines.append(f"- {label} — {m['text']}: {_evidence_text(m['evidence'])}")
    lines.append("")

    if artifact["stop_factors"]:
        lines.append("**Стоп-факторы:** " + "; ".join(sf["text"] for sf in artifact["stop_factors"]))
        lines.append("")

    lines.append(f"**Зарплата:** ожидание {artifact['compensation_status']}")
    lines.append("")

    weaknesses = list(artifact["extraction"].get("weaknesses") or [])
    if weaknesses:
        lines.append("**Самостоятельно отмеченные слабости (из резюме):**")
        for w in weaknesses:
            lines.append(f"- {w}")
        lines.append("")

    unclear = [m for m in artifact["criteria"]["must_have"] if m["status"] == "unclear"]
    if unclear:
        lines.append("**Проверить на интервью:**")
        for m in unclear:
            lines.append(f"- Резюме не подтверждает явно: «{m['text']}» — уточнить на интервью.")
        lines.append("")

    if artifact["validation"]["issues"]:
        lines.append("**⚠ Проблемы валидации evidence:**")
        for issue in artifact["validation"]["issues"]:
            lines.append(f"- [{issue['kind']}] {issue['criterion_id']}: {issue['detail']}")
        lines.append("")

    # Диагностика live-экстракции (эскалация, отклонённый evidence, типовые
    # правки) — есть только когда artifact собран из реального вызова LLM
    # (screen.py); у golden-набора этих ключей в extraction нет, секция
    # просто не появится — тот же рендерер обслуживает оба входа.
    extraction = artifact["extraction"]
    if extraction.get("_escalated_fields"):
        lines.append(f"**↑ Эскалация:** {extraction.get('_escalation_reason', '')}")
        lines.append("")
    if extraction.get("_escalation_disabled_reason"):
        lines.append(f"**↑ Эскалация не выполнена:** {extraction['_escalation_disabled_reason']}")
        lines.append("")
    if extraction.get("_evidence_rejected_fields"):
        lines.append(f"**✗ Отклонённый evidence:** {extraction.get('_evidence_rejected_reason', '')}")
        lines.append("")
    if extraction.get("_empty_evidence_critical_fields"):
        lines.append(f"**⚠ Поля без evidence, влияющие на решение:** "
                      f"{extraction.get('_empty_evidence_critical_reason', '')}")
        lines.append("")
    if extraction.get("_type_coerced_fields"):
        lines.append(f"**⚙ Тип поправлен движком:** экстрактор вернул значение не того типа для "
                      f"{extraction['_type_coerced_fields']} — исправлено детерминированным кодом, не моделью.")
        lines.append("")
    if extraction.get("_needs_human_review"):
        lines.append(f"**⚠ Требуется проверка человеком:** {extraction.get('_human_review_reason', '')}")
        lines.append("")

    return "\n".join(lines)


def write_artifact(candidate_id: str, artifact: dict, vacancy_title: str, out_dir: Path = None) -> tuple:
    out_dir = out_dir or OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{candidate_id}.evidence.json"
    md_path = out_dir / f"{candidate_id}.explain.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_from_artifact(artifact, vacancy_title), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# Сводный report.md по всем golden-кандидатам (удобство поверх per-candidate
# файлов — не заменяет их, а суммирует).
# ---------------------------------------------------------------------------

def render_summary_markdown(rows: list) -> str:
    lines = ["# Отчёт по отбору кандидатов", "", "## Сводная таблица", "",
             "| ID | Вакансия | Решение | Причина |", "|---|---|---|---|"]
    for cid, vacancy_title, trace in rows:
        emoji = DECISION_EMOJI[trace.decision]
        lines.append(f"| {cid} | {vacancy_title} | {emoji} {trace.decision_ru} | {trace.reason} |")
    lines.append("")
    lines.append("Полный разбор каждого кандидата (критерии, evidence, provenance) — в `screening_results/<id>.explain.md`.")
    return "\n".join(lines)


def main():
    vacancies = load_vacancies(FIXTURES / "vacancies" / "roles.json")
    golden = load_golden_candidates(FIXTURES / "candidates_golden.json")
    resumes = load_resumes(FIXTURES / "resumes")

    rows = []
    for cid in sorted(golden.keys()):
        c = golden[cid]
        vacancy = vacancies[c.vacancy_id]
        raw_text = resumes.get(cid, "")
        trace, vr = decide_candidate_with_validation(vacancy, c, raw_text)
        artifact = build_artifact(
            cid, f"fixtures/resumes/{cid}.txt",
            {"role": c.vacancy_id, "confidence": 1.0, "reason": "golden-набор: роль размечена вручную"},
            c.fields, trace, vr,
        )
        write_artifact(cid, artifact, vacancy.title)
        rows.append((cid, vacancy.title, trace))

    (ROOT / "report.md").write_text(render_summary_markdown(rows), encoding="utf-8")

    full_matrix_traces = run_full_matrix(vacancies, golden, resumes)
    (ROOT / "evidence_full_matrix.json").write_text(
        json.dumps([serialize_decision(t) | {"candidate_id": t.candidate_id, "vacancy_id": t.vacancy_id}
                    for t in full_matrix_traces], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"{len(rows)} кандидатов обработано -> screening_results/<id>.evidence.json, screening_results/<id>.explain.md")
    print(f"{len(full_matrix_traces)} строк в кросс-прогоне -> evidence_full_matrix.json")
    print("Сводка -> report.md")


if __name__ == "__main__":
    main()
