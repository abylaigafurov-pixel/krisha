"""Хранилища: Google Sheets (основное) и CSV (для локальной проверки)."""
from __future__ import annotations

import csv
import json
import logging
import re

from parsers import to_float, to_int

log = logging.getLogger("tracker")

# (ключ, заголовок колонки в таблице). Порядок = порядок колонок A, B, C...
COLUMNS = [
    ("id", "ID"),
    ("url", "Ссылка"),
    ("status", "Статус"),
    ("first_seen", "Впервые найдено"),
    ("last_seen", "Последний раз в выдаче"),
    ("misses", "Пропусков подряд"),
    ("price", "Цена, ₸"),
    ("prev_price", "Прежняя цена, ₸"),
    ("price_changed", "Дата смены цены"),
    ("price_m2", "Цена за м², ₸"),
    ("rooms", "Комнат"),
    ("area", "Площадь, м²"),
    ("floor", "Этаж"),
    ("floors", "Этажей в доме"),
    ("complex", "ЖК"),
    ("address", "Адрес"),
    ("district", "Район"),
    ("year", "Год постройки"),
    ("building", "Тип дома"),
    ("lift", "Лифт"),
    ("is_new", "Новостройка"),
]
HEADERS = [h for _, h in COLUMNS]
INT_KEYS = {"misses", "price", "prev_price", "price_m2", "rooms", "floor", "floors", "year"}
FLOAT_KEYS = {"area"}


def _coerce(key: str, value):
    if value is None or value == "":
        return None
    if key == "id":
        return re.sub(r"\D", "", str(value)) or None
    if key in INT_KEYS:
        return to_int(value)
    if key in FLOAT_KEYS:
        return to_float(value)
    return str(value)


def _row_from_values(index: dict, values: list) -> dict | None:
    row = {}
    for key, header in COLUMNS:
        i = index.get(header)
        raw = values[i] if i is not None and i < len(values) else None
        row[key] = _coerce(key, raw)
    return row if row["id"] else None


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value  # чтобы Google Sheets не принял текст за формулу
    return value


class CsvStore:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> list[dict]:
        try:
            with open(self.path, encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return []
                index = {h: i for i, h in enumerate(header)}
                rows = (_row_from_values(index, v) for v in reader)
                return [r for r in rows if r]
        except FileNotFoundError:
            return []

    def save(self, rows: list[dict]) -> None:
        with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(HEADERS)
            for r in rows:
                writer.writerow(["" if r.get(k) is None else r.get(k) for k, _ in COLUMNS])


class SheetsStore:
    CHUNK = 2000

    def __init__(self, spreadsheet_id: str, credentials_json: str, worksheet: str = "Объявления"):
        import gspread

        client = gspread.service_account_from_dict(json.loads(credentials_json))
        sheet = client.open_by_key(spreadsheet_id)
        self._fresh = False
        try:
            self.ws = sheet.worksheet(worksheet)
        except gspread.WorksheetNotFound:
            self.ws = sheet.add_worksheet(title=worksheet, rows=2000, cols=len(COLUMNS) + 5)
            self._fresh = True

    def load(self) -> list[dict]:
        values = self.ws.get_all_values()
        if not values or not any(values[0]):
            self._fresh = True
            return []
        index = {h: i for i, h in enumerate(values[0])}
        rows = (_row_from_values(index, v) for v in values[1:])
        return [r for r in rows if r]

    def save(self, rows: list[dict]) -> None:
        data = [HEADERS] + [[_cell(r.get(k)) for k, _ in COLUMNS] for r in rows]
        if self.ws.row_count < len(data) + 50:
            self.ws.resize(rows=len(data) + 500)
        if self.ws.col_count < len(COLUMNS):
            self.ws.resize(cols=len(COLUMNS))
        for start in range(0, len(data), self.CHUNK):
            self.ws.update(
                values=data[start:start + self.CHUNK],
                range_name=f"A{start + 1}",
                value_input_option="USER_ENTERED",
            )
        if self._fresh:
            try:
                self.ws.freeze(rows=1)
                self.ws.set_basic_filter()
            except Exception as exc:  # оформление не критично
                log.warning("Не удалось оформить заголовок: %s", exc)
            self._fresh = False
