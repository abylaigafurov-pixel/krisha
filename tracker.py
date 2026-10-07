"""Отслеживание объявлений krisha.kz: обход выдачи -> таблица Google Sheets.

Режимы:
  quick - первые страницы выдачи (самые свежие объявления). Запускать часто.
  full  - вся выдача: новые, изменения цен, пометка «Нет в выдаче». Запускать раз в сутки.
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from config import Config, load_config
from parsers import parse_detail, parse_listing
from storage import COLUMNS, CsvStore, SheetsStore

log = logging.getLogger("tracker")
TZ = ZoneInfo("Asia/Almaty")

STATUS_ACTIVE = "Активно"
STATUS_GONE = "Нет в выдаче"
STATUS_DELETED = "Удалено (404)"
LIFT_UNCHECKED = "не проверено"

CARD_FIELDS = ("rooms", "area", "floor", "floors", "complex", "address", "district", "year", "building")


class FetchError(Exception):
    pass


class NotFound(Exception):
    pass


class Fetcher:
    def __init__(self, cfg: Config):
        self.delay = (cfg.delay_min, cfg.delay_max)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        })

    def get(self, url: str, params: dict | None = None) -> str:
        last = None
        for attempt in range(1, 5):
            time.sleep(random.uniform(*self.delay))
            try:
                resp = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as exc:
                last = exc
                time.sleep(5 * attempt)
                continue
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                raise NotFound(url)
            last = f"HTTP {resp.status_code}"
            time.sleep(15 * attempt)  # 403 / 429 / 5xx: ждём дольше и пробуем снова
        raise FetchError(f"{url}: {last}")


def search_params(cfg: Config, rooms: int, page: int) -> dict:
    params = {
        "das[live.rooms][0]": rooms,
        "das[price][from]": cfg.price_from,
        "das[price][to]": cfg.price_to,
        "das[house.year][from]": cfg.year_from,
    }
    if page > 1:
        params["page"] = page
    return params


def matches_filters(card: dict, cfg: Config) -> bool:
    if card["rooms"] is not None and card["rooms"] not in cfg.rooms:
        return False
    price = card["price"]
    if price is None or not (cfg.price_from <= price <= cfg.price_to):
        return False
    if card["year"] is not None and card["year"] < cfg.year_from:
        return False
    return True


def scan(fetcher, cfg: Config, mode: str, debug_dir: str | None = None):
    """Обходит выдачу. Возвращает (карточки по ID, полный ли обход)."""
    found: dict[str, dict] = {}
    complete = mode == "full"
    max_pages = cfg.max_pages if mode == "full" else cfg.quick_pages
    url = cfg.base_url + cfg.search_path

    for rooms in cfg.rooms:
        total, reached_end, prev_ids, seen_here = None, False, set(), set()
        for page in range(1, max_pages + 1):
            try:
                html = fetcher.get(url, search_params(cfg, rooms, page))
            except FetchError as exc:
                log.error("Не удалось загрузить выдачу (%s-комн., стр. %s): %s", rooms, page, exc)
                complete = False
                break
            cards, page_total = parse_listing(html)
            if total is None:
                total = page_total
            ids = {c["id"] for c in cards}
            if page == 1 and not ids and total != 0:
                log.error("На первой странице (%s-комн.) не найдено ни одной карточки: "
                          "сайт мог изменить вёрстку или заблокировать запрос.", rooms)
                complete = False
                if debug_dir:
                    os.makedirs(debug_dir, exist_ok=True)
                    with open(os.path.join(debug_dir, f"search_{rooms}.html"), "w", encoding="utf-8") as f:
                        f.write(html)
            if not ids or ids <= prev_ids:
                reached_end = True
                break
            prev_ids = ids
            seen_here |= ids
            for card in cards:
                found.setdefault(card["id"], card)
            if page % 20 == 0:
                log.info("%s-комн.: страница %s, найдено %s", rooms, page, len(seen_here))

        log.info("%s-комн.: просмотрено объявлений %s (сайт сообщает: %s)", rooms, len(seen_here), total)
        if mode == "full":
            complete = complete and reached_end
            if total and len(seen_here) < 0.8 * total:
                log.warning("Собрано %s из %s — обход считаем неполным, «снятые» не отмечаем.",
                            len(seen_here), total)
                complete = False
    return found, complete


def merge_card(row: dict, card: dict) -> None:
    for key in CARD_FIELDS:
        if card.get(key) not in (None, "") and row.get(key) in (None, ""):
            row[key] = card[key]
    if card.get("is_new"):
        row["is_new"] = "да"
    elif not row.get("is_new"):
        row["is_new"] = "нет"


def update_price(row: dict, price: int | None, now: str) -> bool:
    """Обновляет цену. Возвращает True, если цена изменилась."""
    changed = False
    if price:
        old = row.get("price")
        if old and old != price:
            row["prev_price"] = old
            row["price_changed"] = now
            changed = True
        row["price"] = price
    if row.get("price") and row.get("area"):
        row["price_m2"] = round(row["price"] / row["area"])
    return changed


def new_row(card: dict, now: str) -> dict:
    row = {key: None for key, _ in COLUMNS}
    row.update(id=card["id"], url=card["url"], status=STATUS_ACTIVE,
               first_seen=now, last_seen=now, misses=0, lift=LIFT_UNCHECKED)
    merge_card(row, card)
    update_price(row, card["price"], now)
    return row


def enrich(row: dict, detail: dict) -> None:
    for key in CARD_FIELDS:
        if detail.get(key) not in (None, "") and row.get(key) in (None, ""):
            row[key] = detail[key]
    row["lift"] = detail["lift"]
    update_price(row, None, "")  # пересчитать цену за м², если появилась площадь


def run(cfg: Config, store, fetcher, mode: str, max_detail: int, debug_dir: str | None = None) -> int:
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    rows = store.load()
    by_id = {r["id"]: r for r in rows}
    log.info("Режим: %s. В таблице уже %s объявлений.", mode, len(rows))

    found, complete = scan(fetcher, cfg, mode, debug_dir)
    stats: Counter = Counter()
    matched: set[str] = set()

    for ad_id, card in found.items():
        if not matches_filters(card, cfg):
            stats["не подходят под фильтры"] += 1
            continue
        matched.add(ad_id)
        row = by_id.get(ad_id)
        if row is None:
            row = new_row(card, now)
            rows.append(row)
            by_id[ad_id] = row
            stats["новых"] += 1
            continue
        if row["status"] != STATUS_ACTIVE:
            stats["вернулись в выдачу"] += 1
        merge_card(row, card)
        if update_price(row, card["price"], now):
            stats["изменилась цена"] += 1
        row.update(status=STATUS_ACTIVE, last_seen=now, misses=0)

    if complete and mode == "full":
        for row in rows:
            if row["id"] in matched or row["status"] != STATUS_ACTIVE:
                continue
            row["misses"] = (row.get("misses") or 0) + 1
            if row["misses"] >= cfg.miss_threshold:
                row["status"] = STATUS_GONE
                stats["пропали из выдачи"] += 1

    # Страницы объявлений: нужны для проверки лифта (и дозаполнения полей)
    todo = [r for r in rows if r["status"] == STATUS_ACTIVE and r["lift"] in (None, LIFT_UNCHECKED)]
    todo.sort(key=lambda r: r["first_seen"] or "", reverse=True)
    for row in todo[:max_detail]:
        try:
            detail = parse_detail(fetcher.get(row["url"]))
        except NotFound:
            row["status"] = STATUS_DELETED
            stats["удалены (404)"] += 1
            continue
        except FetchError as exc:
            log.error("Остановил проверку лифта: %s", exc)
            break
        enrich(row, detail)
        stats["проверено на лифт"] += 1
    remaining = sum(1 for r in rows if r["status"] == STATUS_ACTIVE and r["lift"] in (None, LIFT_UNCHECKED))

    store.save(rows)

    log.info("Готово: %s", dict(stats) or "изменений нет")
    log.info("Всего в таблице: %s. Лифт ещё не проверен у: %s.", len(rows), remaining)
    if not found and not complete:
        log.error("Ни одного объявления не получено — запуск считаем неудачным.")
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["quick", "full"], default=os.environ.get("MODE") or "quick")
    parser.add_argument("--store", choices=["sheets", "csv"], default=os.environ.get("STORE") or "sheets")
    parser.add_argument("--csv-path", default="listings.csv")
    parser.add_argument("--max-detail", type=int, default=None,
                        help="сколько страниц объявлений открыть для проверки лифта")
    parser.add_argument("--debug-dir", default=os.environ.get("DEBUG_DIR") or None,
                        help="куда сохранить HTML, если не удалось разобрать выдачу")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    max_detail = args.max_detail if args.max_detail is not None else (
        cfg.detail_full if args.mode == "full" else cfg.detail_quick)

    if args.store == "csv":
        store = CsvStore(args.csv_path)
    else:
        creds, sheet_id = os.environ.get("GOOGLE_CREDENTIALS"), os.environ.get("SPREADSHEET_ID")
        if not creds or not sheet_id:
            log.error("Задайте переменные GOOGLE_CREDENTIALS и SPREADSHEET_ID (см. README).")
            return 2
        store = SheetsStore(sheet_id, creds, os.environ.get("WORKSHEET") or "Объявления")

    return run(cfg, store, Fetcher(cfg), args.mode, max_detail, args.debug_dir)


if __name__ == "__main__":
    sys.exit(main())
