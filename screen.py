"""
Полный цикл с нуля: сырой текст резюме -> определение подходящей вакансии
(LLM-классификация) -> извлечение полей под эту вакансию (LLM, Stage 1) ->
решение движком (Stage 2, без LLM, детерминированно) -> объяснение.

Закрывает пробел, явно зафиксированный в README ("Как это масштабируется"):
раньше primary_role брался из golden-набора, а не определялся по тексту.
Здесь это отдельный дешёвый классификационный проход перед основной
экстракцией — ровно так, как README и предлагал, не новая архитектура.

Phase 2: сборка артефакта (extraction -> criteria -> decision -> validation)
и рендеринг .md — ОБЩИЕ функции с report.py (build_artifact/write_artifact/
render_markdown_from_artifact), не дублируются здесь — иначе .md, который
видит golden-прогон, и .md, который видит live-экстракцию, могли бы тихо
разойтись в формате.

Запуск:
  python3 screen.py fixtures/resumes/R05.txt
  python3 screen.py fixtures/resumes/*.txt
  python3 screen.py my_resume.txt --provider anthropic
"""
import argparse
import re
from pathlib import Path

from domain.vacancy import load_vacancies
from engine.evaluator import decide_candidate_with_validation
from extractors.llm_extractor import classify_role, extract_candidate
import json

from report import OUTPUT_DIR, build_artifact, write_artifact

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"

_HEADER_RE = re.compile(r"^R\d+\.\s*(.+)$")


def _guess_name(raw_text: str, candidate_id: str) -> str:
    """Резюме в fixtures/resumes/*.txt начинаются с заголовка вида
    'R01. Мария Левина, 31 год, Москва' — берём имя до первой запятой,
    а не всю строку целиком (возраст/город не нужны как 'имя')."""
    first_line = next((ln.strip() for ln in raw_text.splitlines() if ln.strip()), candidate_id)
    m = _HEADER_RE.match(first_line)
    body = m.group(1) if m else first_line
    return body.split(",")[0].strip() or candidate_id


def screen_one(path: Path, vacancies: dict, provider: str, model: str = None,
               out_dir: Path = None, judge_relevance_flag: bool = False,
               judge_model_override: str = None) -> Path:
    candidate_id = path.stem
    raw_text = path.read_text(encoding="utf-8")
    name_guess = _guess_name(raw_text, candidate_id)
    out_dir = out_dir or OUTPUT_DIR

    print(f"\n=== {candidate_id} ({path.name}) — {name_guess} ===")

    cls = classify_role(candidate_id, raw_text, vacancies, provider=provider, model_override=model)
    role = cls["role"]

    if role is None:
        print(f"  Не удалось определить вакансию. Сырой ответ классификатора: {cls}")
        # Без role — оценивать нечего (нет вакансии, под которую строить
        # критерии); сохраняем только то, что реально есть, не притворяясь,
        # что decision/criteria были вычислены.
        artifact = {
            "candidate_id": candidate_id, "source_file": str(path), "role_classification": cls,
            "extraction": {}, "criteria": {"must_have": [], "nice_to_have": []}, "stop_factors": [],
            "compensation_status": "unknown",
            "decision": {"decision": None, "decision_ru": None, "reason": "роль не определена",
                         "concerns": [], "confidence": None},
            "validation": {"issues": []},
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{candidate_id}.evidence.json"
        md_path = out_dir / f"{candidate_id}.explain.md"
        json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(f"# Скрининг: {candidate_id}\n\nРоль не определена.\n", encoding="utf-8")
        print(f"  Результат записан: {md_path}")
        return md_path

    print(f"  Роль: {role} ({vacancies[role].title}) — уверенность {cls.get('confidence')}")
    print(f"  Почему эта роль: {cls.get('reason')}")

    extracted = extract_candidate(role, candidate_id, name_guess, raw_text,
                                   provider=provider, model_override=model)
    trace, vr = decide_candidate_with_validation(vacancies[role], extracted, raw_text)

    if judge_relevance_flag:
        import dataclasses
        from domain.decision import decide
        from validation.relevance import apply_relevance_judge
        judge_model = judge_model_override or model
        new_must = apply_relevance_judge(trace.evaluation.must_have, provider, judge_model, vr)
        new_nice = apply_relevance_judge(trace.evaluation.nice_to_have, provider, judge_model, vr)
        new_evaluation = dataclasses.replace(trace.evaluation, must_have=new_must, nice_to_have=new_nice)
        trace = decide(vacancies[role], extracted, new_evaluation)

    print(f"  Решение: {trace.decision_ru.upper()} (уверенность: {trace.confidence}) — {trace.reason}")
    for m in trace.evaluation.must_have:
        ev = " / ".join(f"«{e.text}»" for e in m.evidence) or "нет цитаты из резюме"
        print(f"    [{m.status.value}] {m.text}: {ev}")
    if trace.evaluation.stop_factors_triggered:
        print("  Стоп-факторы: " + "; ".join(s.text for s in trace.evaluation.stop_factors_triggered))
    if extracted.get("_escalated_fields"):
        print(f"  ↑ эскалация: {extracted.get('_escalation_reason')}")
    if extracted.get("_escalation_disabled_reason"):
        print(f"  ↑ эскалация не выполнена: {extracted.get('_escalation_disabled_reason')}")
    if extracted.get("_evidence_rejected_fields"):
        print(f"  ✗ отклонённый evidence: {extracted.get('_evidence_rejected_reason')}")
    if extracted.get("_empty_evidence_critical_fields"):
        print(f"  ⚠ поля без evidence, влияющие на решение: {extracted.get('_empty_evidence_critical_reason')}")
    if extracted.get("_type_coerced_fields"):
        print(f"  ⚙ тип поправлен движком: {extracted.get('_type_coerced_fields')}")
    if extracted.get("_needs_human_review"):
        print(f"  ⚠ needs_human_review: {extracted.get('_human_review_reason')}")
    if vr.issues:
        for issue in vr.as_dicts():
            print(f"  ⚠ validation[{issue['kind']}] {issue['criterion_id']}: {issue['detail']}")

    artifact = build_artifact(candidate_id, str(path), cls, extracted.fields, trace, vr)
    json_path, md_path = write_artifact(candidate_id, artifact, vacancies[role].title, out_dir)

    print(f"  Результат записан: {md_path}")
    print(f"  Артефакт (extraction+criteria+decision+validation): {json_path}")
    return md_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("resumes", nargs="+", help="путь(и) к .txt резюме")
    ap.add_argument("--provider", default="ollama", choices=["ollama", "anthropic", "groq", "gemini"])
    ap.add_argument("--model", default=None, help="переопределить модель провайдера")
    ap.add_argument("--out-dir", default=None, help="куда писать результат (по умолчанию screening_results/)")
    ap.add_argument("--judge-relevance", action="store_true",
                     help="Task 6: дополнительный LLM-вызов на каждый непустой evidence "
                          "(проверяет, доказывает ли цитата ИМЕННО этот критерий, не только что она "
                          "реальная) — не включён по умолчанию, стоит отдельных вызовов на кандидата")
    ap.add_argument("--judge-model", default=None, help="модель для судьи релевантности (по умолчанию — та же, что --model)")
    args = ap.parse_args()

    vacancies = load_vacancies(FIXTURES / "vacancies" / "roles.json")
    out_dir = Path(args.out_dir) if args.out_dir else None
    for p in args.resumes:
        screen_one(Path(p), vacancies, args.provider, args.model, out_dir,
                   args.judge_relevance, args.judge_model)


if __name__ == "__main__":
    main()
