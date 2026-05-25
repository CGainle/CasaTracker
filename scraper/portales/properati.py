"""
Properati scraper (v3).

Las URLs anteriores devolvían 404. Properati cambió a estructura:
  /casas/venta-castelar.html
  /casas/venta-ituzaingo.html
"""
import logging
import json
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from common import (
    make_session, fetch, Listing, make_id,
    extract_beds, extract_baths, extract_garages, extract_surface, parse_price,
)

log = logging.getLogger("casatracker.properati")

PORTAL = "Properati"
BASE = "https://www.properati.com.ar"

SEARCH_URLS = [
    f"{BASE}/s/castelar-norte/casa/venta",
    f"{BASE}/s/ituzaingo-norte/casa/venta",
    f"{BASE}/s/castelar/casa/venta",
    f"{BASE}/s/ituzaingo/casa/venta",
    f"{BASE}/casas/venta-castelar.html",
    f"{BASE}/casas/venta-ituzaingo.html",
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

        # JSON-LD primero
        for s in soup.select("script[type='application/ld+json']"):
            try:
                data = json.loads(s.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict): continue
                    url = item.get("url") or item.get("@id")
                    if url and url not in seen_urls and "/detalle" in url.lower():
                        seen_urls.add(url)
                        _process(item, url, search_url, results)
            except Exception:
                continue

        # Cards HTML
        for sel in ["a[href*='/detalle/']", "a[href*='/p/']", "article a[href]"]:
            cards = soup.select(sel)
            if cards:
                log.info(f"    selector '{sel}' → {len(cards)} matches")
                break

        for card in cards[:30] if cards else []:
            try:
                href = card.get("href")
                if not href: continue
                url = urljoin(BASE, href)
                if url in seen_urls: continue
                seen_urls.add(url)
                # Si no tenemos info del JSON-LD, vamos al detalle
                d = fetch(session, url)
                if not d: continue
                ds = BeautifulSoup(d.text, "html.parser")
                full = ds.get_text(" ", strip=True)
                zone_text = full.lower()
                if "castelar norte" in zone_text:
                    zona = "Castelar Norte"
                elif "ituzaingo norte" in zone_text or "ituzaingó norte" in zone_text:
                    zona = "Ituzaingó Norte"
                else:
                    zona = "Castelar Norte" if "castelar" in search_url else "Ituzaingó Norte"

                title_el = ds.select_one("h1") or ds.select_one("h2")
                title = title_el.get_text(" ", strip=True) if title_el else "Casa en venta"

                price = None
                m = re.search(r"(?:u\$s|usd|us\$)\s*([\d.]+)", full, re.IGNORECASE)
                if m:
                    try: price = int(m.group(1).replace(".",""))
                    except: pass

                og = ds.select_one("meta[property='og:image']")
                image = og.get("content") if og else None

                beds = extract_beds(full[:2000])
                baths = extract_baths(full[:2000])
                garage = extract_garages(full[:2000])
                sup_total, sup_cub = extract_surface(full[:2000])

                results.append(Listing(
                    id=make_id(PORTAL, url),
                    title=title[:120], address="", zona=zona,
                    portal=PORTAL, url=url, price=price,
                    beds=beds, baths=baths, garage=garage,
                    sup_total=sup_total, sup_cub=sup_cub,
                    desc=full[:500], image=image,
                ))
            except Exception as e:
                log.warning(f"    {e}")

    log.info(f"  TOTAL Properati: {len(results)}")
    return results


def _process(item, url, search_url, results):
    title = item.get("name", "Casa en venta")
    desc = item.get("description", "")
    offers = item.get("offers", {}) or {}
    price = None
    if isinstance(offers, dict):
        p = offers.get("price")
        if offers.get("priceCurrency") in ("USD", None) and p:
            try: price = int(float(p))
            except: pass
    addr = item.get("address", {})
    if isinstance(addr, dict):
        address = addr.get("streetAddress") or addr.get("name") or ""
    else:
        address = ""
    geo = item.get("geo", {})
    lat = lng = None
    if isinstance(geo, dict):
        try:
            lat = float(geo.get("latitude")); lng = float(geo.get("longitude"))
        except: pass
    image = item.get("image")
    if isinstance(image, list) and image: image = image[0]

    text = (title + " " + desc).lower()
    if "castelar norte" in text or "castelar" in text:
        zona = "Castelar Norte"
    elif "ituzaingo" in text or "ituzaingó" in text:
        zona = "Ituzaingó Norte"
    else:
        zona = "Castelar Norte" if "castelar" in search_url else "Ituzaingó Norte"

    results.append(Listing(
        id=make_id(PORTAL, url),
        title=title[:120], address=address[:160], zona=zona,
        portal=PORTAL, url=url, price=price,
        beds=extract_beds(desc), baths=extract_baths(desc), garage=extract_garages(desc),
        sup_total=None, sup_cub=None,
        desc=desc[:500], image=image,
        lat=lat, lng=lng,
    ))
