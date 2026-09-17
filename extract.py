"""
Полный Stage 1 пайплайн: конкурентность + кеш + эскалация + произвольный
провайдер. Маршрутизация резюме по вакансии (какой vacancy_id прогонять для
какого файла) берётся из golden-набора — см. README, "Как это масштабируется",
про то, что это осознанно не решённый вопрос вне рамок этой задачи.

Запуск:
  python3 extract.py --mock --mock-noise 0.1        # без сети, харнесс-демо
  python3 extract.py --provider ollama                # реальный локальный Qwen
  python3 extract.py --provider ollama --concurrency 2
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from domain.candidate import load_golden_candidates, load_resumes
from extractors.llm_extractor import ExtractionCache, extract_candidate

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="ollama", choices=["ollama", "anthropic", "groq", "gemini"])
    ap.add_argument("--model", default=None, help="переопределить модель провайдера (cheap==strong)")
    ap.add_argument("--mock", action="store_true", help="без сети/ключа — эмуляция ответа из golden с шумом")
    ap.add_argument("--mock-noise", type=float, default=0.0)
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--resumes-dir", default=str(FIXTURES / "resumes"))
    ap.add_argument("--golden-path", default=str(FIXTURES / "candidates_golden.json"))
    ap.add_argument("--cache-path", default=str(ROOT / "extract_cache.json"))
    ap.add_argument("--out", default=str(ROOT / "llm_extracted.json"))
    args = ap.parse_args()

    golden = load_golden_candidates(args.golden_path)
    resumes = load_resumes(args.resumes_dir)
    cache = ExtractionCache(Path(args.cache_path))

    missing = [cid for cid in golden if cid not in resumes]
    if missing:
        print(f"Пропускаю (нет .txt резюме): {missing}")

    jobs = [(cid, c) for cid, c in golden.items() if cid in resumes]

    def _run(cid, c):
        extracted = extract_candidate(
            c.vacancy_id, cid, c.name, resumes[cid],
            provider=args.provider, mock=args.mock, mock_noise=args.mock_noise,
            golden_fields=c.fields, cache=cache, model_override=args.model,
        )
        return cid, c, extracted

    results = {}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(_run, cid, c) for cid, c in jobs]
        for fut in as_completed(futures):
            cid, c, extracted = fut.result()
            out = dict(extracted.fields)
            out["name"] = c.name
            out["primary_role"] = c.vacancy_id
            results[cid] = out
            flag = " [needs_human_review]" if extracted.get("_needs_human_review") else ""
            print(f"  {cid} ({c.vacancy_id}) готов{flag}")

    cache.save()
    Path(args.out).write_text(
        json.dumps(dict(sorted(results.items())), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{len(results)}/{len(golden)} кандидатов извлечено -> {args.out}")
    print(f"Кеш: {args.cache_path}")


if __name__ == "__main__":
    main()
