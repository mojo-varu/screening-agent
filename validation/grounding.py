"""
Task 4: деминистическая проверка "существует ли эта цитата в тексте
резюме" — то, что ЛОВИТ фабрикацию (цитаты, которых в резюме нет вообще или
которые модель переформулировала до неузнаваемости). НЕ ловит и не пытается
ловить релевантность (настоящая цитата не по теме) — это отдельная,
судейская проверка (validation/relevance.py, Task 6), с другим механизмом
(LLM-судья, а не сопоставление строк) и другим классом ошибок.

Работает одинаково для golden-набора и для любого LLM-провайдера: вход —
только сырой текст резюме + предложенная цитата, никакого сетевого вызова.
"""
import re
from dataclasses import dataclass


def normalize(s: str) -> str:
    """лишние пробелы схлопнуты, регистр снят, ё/е не различаются — так
    сравнение не спотыкается на форматировании, которое не меняет смысл."""
    s = (s or "").lower().replace("ё", "е")
    return re.sub(r"\s+", " ", s).strip()


@dataclass(frozen=True)
class GroundingResult:
    grounded: bool
    start: int = -1
    end: int = -1
    text: str = ""  # ФАКТИЧЕСКИЙ фрагмент raw_text[start:end], если grounded


def _fuzzy_pattern(quote: str) -> "re.Pattern":
    """Запасной путь для случая 'дословно почти, но пробел/регистр/ё
    отличаются' — экранирует токены цитаты и склеивает их через \\s+,
    с учётом взаимозаменяемости е/ё."""
    tokens = quote.split()
    parts = [re.sub(r"[еЕёЁ]", "[еЕёЁ]", re.escape(tok)) for tok in tokens]
    return re.compile(r"\s+".join(parts), re.IGNORECASE)


def locate(raw_text: str, quote: str) -> GroundingResult:
    """Пытается найти quote в raw_text. Порядок попыток:
    1) точное точное python-совпадение (даёт точные offsets бесплатно);
    2) fuzzy-regex с допуском на пробелы/регистр/ё (тоже даёт точные offsets
       в исходном тексте, потому что регекс матчится по нему напрямую, а не
       по нормализованной копии).
    Если оба провалились — цитата не заземлена (validation failure), это
    решает вызывающий код (engine/rules.py / validation/report.py), не эта
    функция: locate() только сообщает факт, не понижает статус сама."""
    if not quote:
        return GroundingResult(grounded=True)  # пустая цитата - не "не найденная цитата", а её отсутствие

    idx = raw_text.find(quote)
    if idx != -1:
        return GroundingResult(True, idx, idx + len(quote), raw_text[idx:idx + len(quote)])

    try:
        m = _fuzzy_pattern(quote).search(raw_text)
    except re.error:
        m = None
    if m:
        return GroundingResult(True, m.start(), m.end(), raw_text[m.start():m.end()])

    return GroundingResult(False)
