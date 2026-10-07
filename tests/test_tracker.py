"""Проверка разбора и логики обновления на тестовом HTML.

HTML собран по структуре, увиденной на krisha.kz (названия классов .a-card* — предположение,
запасной разбор по ссылкам /a/show/ID проверяется отдельно). Запуск: python -m unittest discover tests
"""
import dataclasses
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tracker  # noqa: E402
from config import Config  # noqa: E402
from parsers import detect_lift, parse_detail, parse_listing, split_address  # noqa: E402
from storage import CsvStore  # noqa: E402

NB = " "


def fmt(price):
    return f"{price:,}".replace(",", NB) + f"{NB}₸"


def card(ad_id, rooms, area, floor, floors, price, sub, preview, complex_link=None, price_prefix=""):
    floor_txt = f"{floor}/{floors} этаж" if floors else f"{floor} этаж"
    link = f'<a href="/complex/show/astana/x/">ЖК «{complex_link}»</a> от застройщика «Test»' if complex_link else ""
    return f"""
    <div class="a-card" data-id="{ad_id}">
      <a href="/a/show/{ad_id}"><img alt="фото"></a>
      <a class="a-card__title" href="/a/show/{ad_id}">{rooms}-комнатная квартира · {area} м² · {floor_txt}</a>
      <div class="a-card__price">{price_prefix}{fmt(price)}</div>
      <div class="a-card__subtitle">{sub}</div>
      <div class="a-card__text-preview">{preview}</div>
      {link}
    </div>"""


def page(cards, total):
    return f"<html><body><h1>Продажа</h1><div>Найдено {total} объявлений</div>{''.join(cards)}</body></html>"


def detail(h1, params, description):
    dl = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in params.items())
    return (f"<html><body><h1>{h1}</h1><dl>{dl}</dl>"
            f"<div class='offer__description'>{description}</div></body></html>")


A = card(1001, 2, 59.1, 4, 9, 38_500_000, "Есильский р-н, Аль-Фараби 46/21 — Улы Дала Тельмана",
         "жил. комплекс Jetisu.Aspan, монолитный дом, 2026 г.п., состояние: свежий ремонт, потолки 2.65м.")
B = card(1002, 2, 63.3, 11, 17, 41_200_000, "Есильский р-н, Жошы хана 12/2,",
         "жил. комплекс Capital Park. Emotions, монолитный дом, 2026 г.п., потолки 3м.")
C = card(1003, 3, 74.92, 3, None, 27_000_000, "Сарайшык р-н, А102",
         "жил. комплекс Амирель, 9 этажей, 2023 г.п., потолки 2.7м.", complex_link="Амирель", price_prefix="от ")
D = card(1004, 2, 55.6, 3, 9, 33_000_000, "Ахмет Байтурсынулы 10/3",
         "кирпичный дом, 2021 г.п., потолки 3м., Лифт работает")
E_TOO_OLD = card(1005, 2, 50.0, 2, 9, 30_000_000, "Алматы р-н, Тест 1", "кирпичный дом, 2012 г.п.")
F_TOO_PRICEY = card(1006, 3, 90.0, 2, 9, 60_000_000, "Алматы р-н, Тест 2", "кирпичный дом, 2022 г.п.")


class ParserTests(unittest.TestCase):
    def test_listing_fields(self):
        cards, total = parse_listing(page([A, B, C, D], 4))
        self.assertEqual(total, 4)
        by_id = {c["id"]: c for c in cards}
        a = by_id["1001"]
        self.assertEqual((a["rooms"], a["area"], a["floor"], a["floors"]), (2, 59.1, 4, 9))
        self.assertEqual(a["price"], 38_500_000)
        self.assertEqual(a["complex"], "Jetisu.Aspan")
        self.assertEqual(a["district"], "Есильский р-н")
        self.assertEqual(a["address"], "Аль-Фараби 46/21 — Улы Дала Тельмана")
        self.assertEqual((a["year"], a["building"]), (2026, "монолитный"))
        self.assertEqual(by_id["1002"]["complex"], "Capital Park. Emotions")
        self.assertEqual(by_id["1002"]["address"], "Жошы хана 12/2")
        c = by_id["1003"]
        self.assertTrue(c["is_new"] and c["price_from"])
        self.assertEqual((c["complex"], c["floors"], c["floor"]), ("Амирель", 9, 3))
        d = by_id["1004"]
        self.assertEqual((d["complex"], d["district"], d["address"]), (None, None, "Ахмет Байтурсынулы 10/3"))

    def test_fallback_without_classes(self):
        html = ("<html><body>"
                "<section><a href='/a/show/7'>2-комнатная квартира · 50 м² · 3/9 этаж</a>"
                "<span>35 000 000 ₸</span><p>Есильский р-н, Тест 5</p>"
                "<p>жил. комплекс Лайм, монолитный дом, 2024 г.п.</p></section>"
                "<section><a href='/a/show/8'>3-комнатная квартира · 70 м² · 5/9 этаж</a>"
                "<span>45 000 000 ₸</span></section></body></html>")
        cards, _ = parse_listing(html)
        self.assertEqual([c["id"] for c in cards], ["7", "8"])
        self.assertEqual(cards[0]["price"], 35_000_000)
        self.assertEqual(cards[0]["rooms"], 2)
        self.assertEqual(cards[0]["complex"], "Лайм")

    def test_split_address(self):
        self.assertEqual(split_address("р-н Байконур, Тест 1"), ("р-н Байконур", "Тест 1"))
        self.assertEqual(split_address("Нура р-н, Е-430 2а"), ("Нура р-н", "Е-430 2а"))

    def test_lift(self):
        self.assertEqual(detect_lift("Лифт работает, паркинг"), "да")
        self.assertEqual(detect_lift("Дом без лифта"), "нет")
        self.assertEqual(detect_lift("лифт пока не запущен"), "есть, не работает")
        self.assertEqual(detect_lift("Тихий двор, паркинг"), "не указан")

    def test_detail(self):
        html = detail("2-комнатная квартира · 49 м² · 7/9 этаж, Улы Дала 4/1",
                      {"Город": "Астана, Есильский р-н", "Тип дома": "монолитный", "Жилой комплекс": "Jetisu.Lepsi",
                       "Год постройки": "2023", "Этаж": "7 из 9", "Площадь": "49 м²"},
                      "Удобный этаж. Лифт работает.")
        d = parse_detail(html)
        self.assertEqual((d["complex"], d["year"], d["building"]), ("Jetisu.Lepsi", 2023, "монолитный"))
        self.assertEqual((d["floor"], d["floors"], d["district"], d["address"]), (7, 9, "Есильский р-н", "Улы Дала 4/1"))
        self.assertEqual(d["lift"], "да")


class FakeFetcher:
    """Подменяет сайт: выдача по (комнаты, страница) и страницы объявлений."""

    def __init__(self, search, details):
        self.search, self.details, self.calls = search, details, 0

    def get(self, url, params=None):
        self.calls += 1
        if params is not None:
            rooms, pg = params["das[live.rooms][0]"], params.get("page", 1)
            return self.search.get((rooms, pg), page([], 0))
        ad_id = url.rsplit("/", 1)[1]
        if ad_id not in self.details:
            raise tracker.NotFound(url)
        return self.details[ad_id]


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = CsvStore(os.path.join(self.tmp, "t.csv"))
        self.cfg = dataclasses.replace(Config(), max_pages=5, quick_pages=2)
        self.details = {
            "1001": detail("x", {"Жилой комплекс": "Jetisu.Aspan"}, "Лифт работает"),
            "1002": detail("x", {}, "Дом без лифта"),
            "1003": detail("x", {}, "Просто описание"),
            "1004": detail("x", {}, "Лифт есть"),
        }

    def search(self, two_room_cards, three_room_cards):
        return {(2, 1): page(two_room_cards, len(two_room_cards)),
                (3, 1): page(three_room_cards, len(three_room_cards))}

    def rows(self):
        return {r["id"]: r for r in self.store.load()}

    def test_full_cycle(self):
        # Запуск 1: 4 подходящих + 2 лишних (старый дом, цена выше диапазона)
        f = FakeFetcher(self.search([A, B, D, E_TOO_OLD], [C, F_TOO_PRICEY]), self.details)
        self.assertEqual(tracker.run(self.cfg, self.store, f, "full", 50), 0)
        rows = self.rows()
        self.assertEqual(set(rows), {"1001", "1002", "1003", "1004"})
        self.assertEqual(rows["1001"]["lift"], "да")
        self.assertEqual(rows["1002"]["lift"], "нет")
        self.assertEqual(rows["1003"]["lift"], "не указан")
        self.assertEqual(rows["1001"]["price_m2"], round(38_500_000 / 59.1))
        self.assertEqual(rows["1003"]["is_new"], "да")

        # Запуск 2: у A новая цена, B исчезла (1-й пропуск — ещё «Активно»)
        a2 = card(1001, 2, 59.1, 4, 9, 36_000_000, "Есильский р-н, Аль-Фараби 46/21",
                  "жил. комплекс Jetisu.Aspan, монолитный дом, 2026 г.п.")
        f = FakeFetcher(self.search([a2, D], [C]), self.details)
        tracker.run(self.cfg, self.store, f, "full", 50)
        rows = self.rows()
        self.assertEqual((rows["1001"]["price"], rows["1001"]["prev_price"]), (36_000_000, 38_500_000))
        self.assertTrue(rows["1001"]["price_changed"])
        self.assertEqual((rows["1002"]["status"], rows["1002"]["misses"]), ("Активно", 1))
        self.assertEqual(rows["1001"]["lift"], "да")  # повторно не перезаписывается и не запрашивается

        # Запуск 3: B снова нет -> «Нет в выдаче»
        tracker.run(self.cfg, self.store, f, "full", 50)
        self.assertEqual(self.rows()["1002"]["status"], "Нет в выдаче")

        # Запуск 4 (quick): ничего не помечается как пропавшее, B не трогаем
        tracker.run(self.cfg, self.store, f, "quick", 50)
        self.assertEqual(self.rows()["1002"]["status"], "Нет в выдаче")

        # B вернулась в выдачу
        f = FakeFetcher(self.search([a2, B, D], [C]), self.details)
        tracker.run(self.cfg, self.store, f, "full", 50)
        self.assertEqual(self.rows()["1002"]["status"], "Активно")

    def test_detail_limit_and_resume(self):
        f = FakeFetcher(self.search([A, B, D], [C]), self.details)
        tracker.run(self.cfg, self.store, f, "full", 2)
        unchecked = [r for r in self.rows().values() if r["lift"] == "не проверено"]
        self.assertEqual(len(unchecked), 2)
        tracker.run(self.cfg, self.store, f, "full", 10)
        self.assertFalse([r for r in self.rows().values() if r["lift"] == "не проверено"])

    def test_incomplete_scan_does_not_mark_gone(self):
        f = FakeFetcher(self.search([A, B], [C]), self.details)
        tracker.run(self.cfg, self.store, f, "full", 50)

        class Failing(FakeFetcher):
            def get(self, url, params=None):
                if params is not None:
                    raise tracker.FetchError("HTTP 403")
                return super().get(url, params)

        for _ in range(3):
            code = tracker.run(self.cfg, self.store, Failing({}, self.details), "full", 0)
            self.assertEqual(code, 1)
        self.assertEqual({r["status"] for r in self.rows().values()}, {"Активно"})


if __name__ == "__main__":
    unittest.main()
