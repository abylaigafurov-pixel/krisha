"""Настройки поиска. Меняйте значения здесь (или через переменные окружения)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


@dataclass(frozen=True)
class Config:
    base_url: str = "https://krisha.kz"
    search_path: str = "/prodazha/kvartiry/astana/"

    # Фильтры
    rooms: tuple = (2, 3)
    price_from: int = 25_000_000
    price_to: int = 50_000_000
    year_from: int = 2020

    # Сколько страниц выдачи обходить (на странице ~20 объявлений)
    max_pages: int = 500      # режим full: до конца выдачи
    quick_pages: int = 8      # режим quick: только свежие объявления

    # Сколько страниц объявлений открывать за один запуск (для проверки лифта).
    # Остальные будут дозаполняться в следующих запусках.
    detail_quick: int = 100
    detail_full: int = 300

    # После скольких полных обходов подряд без объявления ставить «Нет в выдаче»
    miss_threshold: int = 2

    # Пауза между запросами, секунды (чтобы не нагружать сайт)
    delay_min: float = 1.5
    delay_max: float = 3.0


def load_config() -> Config:
    return Config(
        price_from=_env_int("PRICE_FROM", Config.price_from),
        price_to=_env_int("PRICE_TO", Config.price_to),
        year_from=_env_int("YEAR_FROM", Config.year_from),
        quick_pages=_env_int("QUICK_PAGES", Config.quick_pages),
        detail_quick=_env_int("DETAIL_QUICK", Config.detail_quick),
        detail_full=_env_int("DETAIL_FULL", Config.detail_full),
    )
