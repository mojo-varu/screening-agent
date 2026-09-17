"""
Минимальная последовательная проверка Stage 1 (извлечение) на живой модели —
до того, как доверять полному extract.py (конкурентность + кеш + эскалация).
Без аргументов бьёт по первым 2 кандидатам через --provider ollama, печатает
сырой ответ модели как есть — чтобы руками увидеть, действительно ли JSON-контракт
держится на конкретной локальной модели, а не полагаться на предположение.

Запуск: python3 poc.py [--n N] [--provider ollama|anthropic]
"""
import argparse
import json
import sys
from pathlib import Path

from domain.candidate import load_golden_candidates, load_resumes
from extractors.llm_extractor import extract_candidate

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2, help="сколько кандидатов проверить")
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    golden = load_golden_candidates(FIXTURES / "candidates_golden.json")
    resumes = load_resumes(FIXTURES / "resumes")

    if not resumes:
        print(f"Нет резюме в {FIXTURES / 'resumes'}", file=sys.stderr)
        sys.exit(1)

    ids = list(golden.keys())[: args.n]
    for cid in ids:
        c = golden[cid]
        raw_text = resumes.get(cid)
        if raw_text is None:
            print(f"[{cid}] пропущен: нет fixtures/resumes/{cid}.txt")
            continue

        print(f"\n=== {cid} ({c.vacancy_id}) — {c.name} — provider={args.provider} ===")
        try:
            extracted = extract_candidate(
                c.vacancy_id, cid, c.name, raw_text, provider=args.provider,
                model_override=args.model,
            )
        except Exception as e:
            print(f"  ОШИБКА: {type(e).__name__}: {e}")
            continue

        print(json.dumps(extracted.fields, ensure_ascii=False, indent=2))
        if extracted.get("_needs_human_review"):
            print(f"  -> _needs_human_review: {extracted.get('_human_review_reason')}")


if __name__ == "__main__":
    main()
