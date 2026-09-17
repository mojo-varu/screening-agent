"""
Единственное место, которое реально ходит в сеть за LLM. Все провайдеры —
за одним интерфейсом (call_llm(prompt, model, provider) -> dict), чтобы
extractors/llm_extractor.py не знал, с каким провайдером работает.

Живьём проверены все три: Ollama (локально), Anthropic (urllib) и Groq.

Groq — особый случай: Cloudflare перед их API отдаёт 403 (error code 1010,
"Access denied. Please check your network settings.") на запросы от
urllib.request — даже с честным User-Agent на GET /models. На POST
/chat/completions подмена только User-Agent не помогла вообще: под тем же
ключом и телом запроса curl получает 200, urllib с идентичным UA — стабильно
403. Это фингерпринтинг на уровне TLS/HTTP2-хендшейка (ClientHello/ALPN),
который urllib подделать не может, а строкой заголовка не лечится. Поэтому
call_groq() ниже не использует urllib — шлёт запрос через системный curl
subprocess'ом. Ключ передаётся curl через `-H @tempfile` (заголовок из
файла с правами 600), а не литералом в argv — чтобы он не светился в `ps`.
"""
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

USER_AGENT = "curl/8.5.0"

MODELS = {
    # phi4-mini (квантованная, 3.8B) выбрана вместо qwen2.5:3b по факту
    # прогона обеих через eval_extraction.py на живом golden-наборе:
    # decision agreement 70% vs 60%, и, что важнее, phi4-mini не
    # галлюцинирует стоп-факторов (у qwen2.5:3b 4/10 кандидатов получили
    # стоп-фактор, которого нет в тексте резюме вообще). "strong" == "cheap"
    # deliberately: более крупного локального варианта phi4 не установлено —
    # эскалация в llm_extractor.py срабатывает, но бьёт в ту же модель.
    "ollama": {"cheap": "phi4-mini:3.8b-q4_K_M", "strong": "phi4-mini:3.8b-q4_K_M"},
    "anthropic": {"cheap": "claude-haiku-4-5-20251001", "strong": "claude-sonnet-5"},
    # qwen/qwen3.8-27b — единственная Qwen-модель, реально числящаяся в
    # аккаунте на момент проверки (GET /openai/v1/models); "32B"/"3.6-27B"
    # там не значились — взято по факту, не по памяти. "strong" == "cheap":
    # openai/gpt-oss-120b тоже доступен и был бы реальным по размеру
    # эскалационным вариантом, но не Qwen — не включаю его сам, пока явно
    # не попросят смешивать семейства моделей внутри одной эскалации.
    "groq": {"cheap": "qwen/qwen3.8-27b", "strong": "qwen/qwen3.8-27b"},
    # gemini-2.5-flash-lite числился в /v1beta/models, но на живом вызове
    # вернул 404 "no longer available to new users" — сам API-ответ
    # рекомендует gemini-3.5-flash-lite, что и проверено отдельным вызовом.
    # Сознательно не "-latest" алиас, чтобы модель не подменилась молча.
    "gemini": {"cheap": "gemini-3.5-flash-lite", "strong": "gemini-3.5-flash-lite"},
}

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _load_dotenv():
    """Минимальный .env-загрузчик (без python-dotenv — pip недоступен в
    этой песочнице). Не перезаписывает уже установленные переменные
    окружения — реальный env всегда имеет приоритет над .env."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


OLLAMA_MAX_RETRIES = 2  # format:"json" не гарантирует валидный JSON на каждый вызов,
                        # особенно на крупной схеме (все *_evidence поля) с квантованной моделью


def call_ollama(prompt: str, model: str) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "format": "json",
        # num_predict бounds generation length — без него квантованная модель
        # иногда уходит в повтор/не останавливается (сервер запущен с
        # --context-shift, поэтому даже заполнение контекста не остановит
        # генерацию само по себе). 1200 оказалось мало и на живом V1-запросе
        # (R02) резало JSON посреди строки ("Unterminated string") — 12 полей
        # x value+confidence+evidence легко перебирают этот бюджет. 2500 с
        # запасом покрывает самую большую схему (V2, 17 строк), но всё ещё
        # даёт жёсткую верхнюю границу, а не бесконечную генерацию.
        "options": {"temperature": 0, "num_predict": 2500},
        "stream": False,
    }
    req_data = json.dumps(payload).encode("utf-8")

    last_error = None
    for attempt in range(OLLAMA_MAX_RETRIES + 1):
        req = urllib.request.Request(
            OLLAMA_URL, data=req_data,
            headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            last_error = e
            continue
    raise RuntimeError(
        f"Ollama вернул невалидный JSON {OLLAMA_MAX_RETRIES + 1} раза подряд "
        f"(модель {model}): {last_error}"
    )


def _parse_json_loose(text: str) -> dict:
    """Claude иногда оборачивает ответ в ```json ... ``` несмотря на явную
    инструкцию "без markdown-обрамления" — снимаем обёртку перед парсингом."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def call_anthropic(prompt: str, model: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY не задан (ни в окружении, ни в .env)")

    payload = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    text = body["content"][0]["text"]
    return _parse_json_loose(text)


GROQ_MAX_RETRIES = 4
GROQ_RATE_LIMIT_BACKOFF = 20  # сек — free-tier OTPM лимит маленький, ждём с запасом


def call_groq(prompt: str, model: str) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY не задан (ни в окружении, ни в .env)")

    payload = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    })

    header_fd, header_path = tempfile.mkstemp(prefix="groq_hdr_")
    try:
        os.chmod(header_path, 0o600)
        with os.fdopen(header_fd, "w") as hf:
            hf.write(f"Authorization: Bearer {api_key}\n")

        for attempt in range(GROQ_MAX_RETRIES + 1):
            proc = subprocess.run(
                ["curl", "-s", "-X", "POST", GROQ_API_URL,
                 "-H", "Content-Type: application/json",
                 "-H", f"@{header_path}",
                 "--data-binary", "@-"],
                input=payload.encode("utf-8"),
                capture_output=True, timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"curl завершился с ошибкой ({proc.returncode}): "
                                    f"{proc.stderr.decode(errors='replace')}")

            body = json.loads(proc.stdout.decode("utf-8"))
            if "error" not in body:
                break
            err = body["error"]
            # free-tier OTPM/RPM лимит маленький (1000 output tokens/min) — при
            # конкурентных запросах это ожидаемо, не повод падать всей пачкой.
            if err.get("code") == "rate_limit_exceeded" and attempt < GROQ_MAX_RETRIES:
                time.sleep(GROQ_RATE_LIMIT_BACKOFF)
                continue
            raise RuntimeError(f"Groq API вернул ошибку: {err}")
    finally:
        os.unlink(header_path)

    text = body["choices"][0]["message"]["content"]
    return _parse_json_loose(text)


def call_gemini(prompt: str, model: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не задан (ни в окружении, ни в .env)")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    url = GEMINI_API_URL_TMPL.format(model=model)
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json_loose(text)


def call_llm(prompt: str, model: str, provider: str) -> dict:
    if provider == "ollama":
        return call_ollama(prompt, model)
    if provider == "anthropic":
        return call_anthropic(prompt, model)
    if provider == "groq":
        return call_groq(prompt, model)
    if provider == "gemini":
        return call_gemini(prompt, model)
    raise ValueError(f"unknown provider: {provider}")
