"""Разбор HTML krisha.kz: страница выдачи и страница объявления."""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

BASE_URL = "https://krisha.kz"
ID_RE = re.compile(r"/a/show/(\d+)")
PRICE_RE = re.compile(r"(от\s*)?(\d[\d\s ]*)\s*₸")
BUILDINGS = "кирпичный|панельный|монолитный|иной"


# ---------------------------------------------------------------- утилиты

def clean(text) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(" ", " ")).strip()


def to_int(text) -> Optional[int]:
    digits = re.sub(r"\D", "", str(text) if text is not None else "")
    return int(digits) if digits else None


def to_float(text) -> Optional[float]:
    compact = str(text if text is not None else "").replace(" ", "").replace(" ", "")
    m = re.search(r"\d+(?:[.,]\d+)?", compact)
    return float(m.group(0).replace(",", ".")) if m else None


def parse_price(text: str):
    """'от 32 230 000 ₸' -> (32230000, True); '38 500 000 ₸' -> (38500000, False)."""
    m = PRICE_RE.search(text or "")
    if not m:
        return None, False
    return to_int(m.group(2)), bool(m.group(1))


def parse_title(title: str) -> dict:
    """'2-комнатная квартира · 59.1 м² · 4/9 этаж' -> rooms, area, floor, floors."""
    rooms = re.search(r"(\d+)\s*-\s*комнат", title)
    area = re.search(r"(\d+(?:[.,]\d+)?)\s*м²", title)
    both = re.search(r"(\d+)\s*/\s*(\d+)\s*этаж", title)
    single = re.search(r"(\d+)\s*этаж", title)
    out = {
        "rooms": int(rooms.group(1)) if rooms else None,
        "area": to_float(area.group(1)) if area else None,
        "floor": None,
        "floors": None,
    }
    if both:
        out["floor"], out["floors"] = int(both.group(1)), int(both.group(2))
    elif single:
        out["floor"] = int(single.group(1))
    return out


def split_address(text: str):
    """'Есильский р-н, Аль-Фараби 46/21 — Улы Дала' -> ('Есильский р-н', 'Аль-Фараби 46/21 — Улы Дала')."""
    text = clean(text).strip(" ,")
    m = re.match(r"^((?:р-н\s+\S+)|(?:[^,]*?\sр-н)),\s*(.+)$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip(" ,")
    return "", text


def parse_preview(text: str) -> dict:
    """Строка вида 'жил. комплекс Jetisu.Aspan, монолитный дом, 2026 г.п., ...'."""
    text = clean(text)
    complex_name = None
    m = re.search(
        r"жил\.\s*комплекс\s+(.+?)(?=,\s*(?:(?:%s)\s+дом|\d+\s+этаж\w*|\d{4}\s*г\.п\.|состояние:|потолки))" % BUILDINGS,
        text,
    )
    if m:
        complex_name = m.group(1).strip()
    year = re.search(r"(\d{4})\s*г\.п\.", text)
    building = re.search(r"(%s)\s+дом" % BUILDINGS, text)
    floors = re.search(r",\s*(\d+)\s+этаж(?:ей|а)?\s*,\s*\d{4}\s*г\.п\.", text)
    return {
        "complex": complex_name,
        "year": int(year.group(1)) if year else None,
        "building": building.group(1) if building else None,
        "floors": int(floors.group(1)) if floors else None,
    }


def detect_lift(text: str) -> str:
    """Определяет лифт по тексту объявления (отдельного поля на сайте нет)."""
    t = (text or "").lower().replace("ё", "е")
    if "лифт" not in t:
        return "не указан"
    if re.search(r"без\s+лифт|нет\s+лифт|лифт\w*\s+(?:в\s+доме\s+)?(?:нет|отсутству)|отсутству\w+\s+лифт", t):
        return "нет"
    if re.search(r"лифт\w*\s+(?:пока\s+)?не\s+(?:работает|запущен|функционирует)", t):
        return "есть, не работает"
    return "да"


# ---------------------------------------------------------------- выдача

def parse_card(el) -> Optional[dict]:
    link = None
    for a in el.find_all("a", href=ID_RE):
        if "комнат" in a.get_text().lower():
            link = a
            break
    if link is None:
        link = el.find("a", href=ID_RE)
    if link is None:
        return None

    ad_id = ID_RE.search(link["href"]).group(1)
    text = clean(el.get_text(" "))
    title = clean(link.get_text())
    if "комнат" not in title:
        title = text
    info = parse_title(title)

    price_el = el.select_one(".a-card__price")
    price, price_from = parse_price(price_el.get_text() if price_el else text)

    sub_el = el.select_one(".a-card__subtitle")
    district, address = split_address(sub_el.get_text() if sub_el else "")

    preview_el = el.select_one(".a-card__text-preview")
    pv = parse_preview(preview_el.get_text() if preview_el else text)

    complex_name = None
    cl = el.select_one('a[href*="/complex/show/"]')
    if cl:
        complex_name = re.sub(r"^ЖК\s*", "", clean(cl.get_text())).strip("«»\" ") or None
    complex_name = complex_name or pv["complex"]

    return {
        "id": ad_id,
        "url": f"{BASE_URL}/a/show/{ad_id}",
        "price": price,
        "price_from": price_from,
        "rooms": info["rooms"],
        "area": info["area"],
        "floor": info["floor"],
        "floors": info["floors"] or pv["floors"],
        "complex": complex_name,
        "address": address or None,
        "district": district or None,
        "year": pv["year"],
        "building": pv["building"],
        "is_new": bool(cl) or bool(re.search(r"\bНовостройка\b", text)),
    }


def parse_listing(html: str):
    """Возвращает (список карточек, 'Найдено N объявлений' или None)."""
    soup = BeautifulSoup(html, "html.parser")
    cards, seen = [], set()

    elements = soup.select(".a-card[data-id]") or soup.select(".a-card")
    if elements:
        nodes = elements
    else:
        # Запасной путь, если классы на сайте поменялись: ищем ссылки на объявления
        # и берём наибольший контейнер, где есть ссылки только на одно объявление.
        nodes = []
        done = set()
        for a in soup.find_all("a", href=ID_RE):
            ad_id = ID_RE.search(a["href"]).group(1)
            if ad_id in done:
                continue
            done.add(ad_id)
            node = a
            while node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
                ids = {ID_RE.search(x["href"]).group(1) for x in node.parent.find_all("a", href=ID_RE)}
                if len(ids) > 1:
                    break
                node = node.parent
            nodes.append(node)

    for node in nodes:
        card = parse_card(node)
        if card and card["id"] not in seen:
            seen.add(card["id"])
            cards.append(card)

    m = re.search(r"Найдено\s+([\d\s ]+?)\s+объявл", soup.get_text(" "))
    return cards, (to_int(m.group(1)) if m else None)


# ---------------------------------------------------------------- объявление

def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    params = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd is not None:
            params[clean(dt.get_text())] = clean(dd.get_text(" "))

    text = soup.get_text("\n")
    desc_el = soup.select_one(".offer__description, .js-description")
    if desc_el:
        description = clean(desc_el.get_text(" "))
    else:
        m = re.search(
            r"Описание\s*\n(.*?)\n\s*(?:Перевести|Показать оригинал|Пожаловаться на объявление)",
            text,
            re.S,
        )
        description = clean(m.group(1)) if m else ""

    h1 = clean(soup.h1.get_text(" ")) if soup.h1 else ""
    info = parse_title(h1)
    addr = re.search(r"(?:этаж|м²),\s*(.+)$", h1)

    district = None
    city = params.get("Город", "")
    if "," in city:
        district = clean(city.split(",", 1)[1]) or None

    floor = floors = None
    fl = re.search(r"(\d+)\s*из\s*(\d+)", params.get("Этаж", ""))
    if fl:
        floor, floors = int(fl.group(1)), int(fl.group(2))

    lift_source = description + " " + " ".join(f"{k} {v}" for k, v in params.items())
    return {
        "complex": params.get("Жилой комплекс") or None,
        "address": clean(addr.group(1)).strip(" ,") if addr else None,
        "district": district,
        "year": to_int(params.get("Год постройки")),
        "building": params.get("Тип дома") or None,
        "rooms": info["rooms"],
        "area": info["area"],
        "floor": floor or info["floor"],
        "floors": floors or info["floors"],
        "lift": detect_lift(lift_source),
    }
