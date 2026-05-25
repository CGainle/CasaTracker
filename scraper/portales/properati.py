"""
Properati scraper.

Properati expone una API JSON pública para resultados de búsqueda.
"""
import logging
import json
import re
from bs4 import BeautifulSoup
from common import (
    make_session, fetch, Listing, make_id,
    extract_beds, extract_baths, extract_garages, extract_surface, parse_price,
)

log = logging.getLogger("casatracker.properati")

PORTAL = "Properati"
BASE = "https://www.properati.com.ar"

SEARCH_URLS = [
    f"{BASE}/s/castelar-norte-moron/casa/venta",
    f"{BASE}/s/ituzaingo-norte/casa/venta",
]


def scrape():
    session = make_session()
    results = []
    seen_urls = set()

    for search_url in SEARCH_URLS:
        log.info(f"  → {search_url}")
        r = fetch(session, search_url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        # Properati embeds JSON-LD with listings
        for script in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        _process_jsonld_item(item, search_url, session, results, seen_urls)
                elif isinstance(data, dict):
                    _process_jsonld_item(data, search_url, session, results, seen_urls)
            except (json.JSONDecodeError, AttributeError):
                continue

        # Fallback: parsear cards HTML
        cards = soup.select("a[href*='/detalle/']")
        log.info(f"    {len(cards)} cards encontradas")
        for card in cards[:30]:
            try:
                url = card.get("href")
                if not url:
                    continue
                if not url.startswith("http"):
                    url = BASE + url
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                zona = "Castelar Norte" if "castelar" in search_url else "Ituzaingó Norte"
                _scrape_detail(session, url, zona, results)
            except Exception as e:
                log.warning(f"  Error: {e}")

    log.info(f"  TOTAL Properati: {len(results)} avisos")
    return results


def _process_jsonld_item(item, search_url, session, results, seen_urls):
    if item.get("@type") not in ("Product", "Residence", "Offer", "Place"):
        return
    url = item.get("url") or item.get("@id")
    if not url or url in seen_urls:
        return
    seen_urls.add(url)
    zona = "Castelar Norte" if "castelar" in search_url else "Ituzaingó Norte"
    _scrape_detail(session, url, zona, results)


def _scrape_detail(session, url, zona, results):
    r = fetch(session, url)
    if not r:
        return
    soup = BeautifulSoup(r.text, "html.parser")

    title_el = soup.select_one("h1")
    title = title_el.get_text(" ", strip=True) if title_el else "Casa en venta"

    price_el = soup.select_one(".price, [class*='price'], [data-qa='POSTING_CARD_PRICE']")
    price_text = price_el.get_text(" ", strip=True) if price_el else ""
    price = parse_price(price_text)

    desc_el = soup.select_one(".description, [class*='description']")
    desc = desc_el.get_text(" ", strip=True) if desc_el else ""

    addr_el = soup.select_one(".address, [class*='address'], h2")
    address = addr_el.get_text(" ", strip=True) if addr_el else ""

    img_el = soup.select_one("meta[property='og:image']")
    image = img_el.get("content") if img_el else None

    full_text = title + " " + desc
    beds = extract_beds(full_text)
    baths = extract_baths(full_text)
    garage = extract_garages(full_text)
    sup_total, sup_cub = extract_surface(full_text)

    # Coords desde JSON-LD si existe
    lat = lng = None
    for s in soup.select("script[type='application/ld+json']"):
        try:
            d = json.loads(s.string)
            if isinstance(d, dict) and "geo" in d:
                lat = float(d["geo"].get("latitude", 0)) or None
                lng = float(d["geo"].get("longitude", 0)) or None
                if lat: break
        except Exception:
            pass

    results.append(Listing(
        id=make_id(PORTAL, url),
        title=title[:100],
        address=address[:160],
        zona=zona,
        portal=PORTAL,
        url=url,
        price=price,
        beds=beds,
        baths=baths,
        garage=garage,
        sup_total=sup_total,
        sup_cub=sup_cub,
        desc=desc[:600],
        image=image,
        lat=lat,
        lng=lng,
    ))
