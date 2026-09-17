"""
Сравнивает LLM-экстракцию (llm_extracted.json, из extract.py) с golden set —
два уровня метрик, см. TECH_SPEC.md §5:

1. field agreement — совпало ли каждое поле с golden (отладочный сигнал).
2. decision agreement — прогоняет ОБА профиля через тот же engine.decide() и
   сравнивает вердикт (это метрика продукта: ошибка в поле, не влияющая на
   решение, не является проблемой).

Запуск: python3 eval_extraction.py [--extracted llm_extracted.json]
"""
import argparse
import json
from pathlib import Path

from domain.candidate import FIELD_SPECS, CandidateProfile, load_golden_candidates, load_resumes
from domain.vacancy import load_vacancies
from engine.evaluator import decide_candidate

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"

INTERNAL_PREFIX = "_"


def field_agreement(vacancy_id: str, golden_fields: dict, extracted_fields: dict) -> tuple:
    specs = FIELD_SPECS[vacancy_id]
    matched, total, mismatches = 0, 0, []
    for name, _typ, _desc in specs:
        total += 1
        g, e = golden_fields.get(name), extracted_fields.get(name)
        if g == e:
            matched += 1
        else:
            mismatches.append((name, g, e))
    return matched, total, mismatches


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extracted", default=str(ROOT / "llm_extracted.json"))
    args = ap.parse_args()

    vacancies = load_vacancies(FIXTURES / "vacancies" / "roles.json")
    golden = load_golden_candidates(FIXTURES / "candidates_golden.json")
    resumes = load_resumes(FIXTURES / "resumes")
    extracted_raw = json.loads(Path(args.extracted).read_text(encoding="utf-8"))

    total_matched = total_fields = 0
    decision_agree = 0
    decision_total = 0
    field_report_lines = []
    decision_report_lines = []

    for cid, c in sorted(golden.items()):
        if cid not in extracted_raw:
            print(f"[{cid}] нет в {args.extracted} — пропущен")
            continue

        e_raw = {k: v for k, v in extracted_raw[cid].items()
                  if not k.startswith(INTERNAL_PREFIX) and k not in ("name", "primary_role")}
        e_candidate = CandidateProfile.from_raw(cid, c.name, c.vacancy_id, e_raw)

        matched, total, mismatches = field_agreement(c.vacancy_id, c.fields, e_candidate.fields)
        total_matched += matched
        total_fields += total
        if mismatches:
            field_report_lines.append(f"  {cid}: {matched}/{total} совпало; расхождения: " +
                                       "; ".join(f"{n} golden={g!r} extracted={e!r}" for n, g, e in mismatches))
        else:
            field_report_lines.append(f"  {cid}: {matched}/{total} совпало")

        raw_text = resumes.get(cid, "")
        golden_trace = decide_candidate(vacancies[c.vacancy_id], c, raw_text)
        extracted_trace = decide_candidate(vacancies[c.vacancy_id], e_candidate, raw_text)
        decision_total += 1
        if golden_trace.decision == extracted_trace.decision:
            decision_agree += 1
        else:
            decision_report_lines.append(
                f"  {cid}: golden={golden_trace.decision.value} -> extracted={extracted_trace.decision.value} "
                f"(extracted reason: {extracted_trace.reason})"
            )

    print("=== Field-level agreement ===")
    for line in field_report_lines:
        print(line)
    print(f"\nИТОГО полей: {total_matched}/{total_fields} "
          f"({100 * total_matched / total_fields:.1f}%)" if total_fields else "нет данных")

    print("\n=== Decision-level agreement ===")
    if decision_report_lines:
        print("Расхождения:")
        for line in decision_report_lines:
            print(line)
    else:
        print("Расхождений нет.")
    print(f"\nИТОГО решений: {decision_agree}/{decision_total} "
          f"({100 * decision_agree / decision_total:.1f}%)" if decision_total else "нет данных")


if __name__ == "__main__":
    main()
