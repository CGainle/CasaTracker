"""
Argenprop scraper (v2 — más robusto).

Estrategia:
1. Probar múltiples URLs de búsqueda (con/sin filtros) y combinaciones de barrios.
2. Probar varios selectores CSS porque el sitio cambia.
3. Si la card preview tiene precio/beds/baths, usarla; si no, ir al detalle.
4. Extraer del JSON-LD si está disponible.
"""
import logging
import re
import json
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from common import (
    make_session, fetch, Listing, make_id,
    extract_beds, extract_baths, extract_garages, extract_surface, parse_price,
)

log = logging.getLogger("casatracker.argenprop")

PORTAL = "Argenprop"
BASE = "https://www.argenprop.com"

# Más URLs para abarcar más posibilidades
SEARCH_URLS = [
    # 3 ambientes + USD 175k-250k
    (f"{BASE}/casas/venta/castelar-norte/3-ambientes/dolares-175000-250000", "Castelar Norte"),
    (f"{BASE}/casas/venta/ituzaingo-norte/3-ambientes/dolares-175000-250000", "Ituzaingó Norte"),
    # Sin filtro de ambientes (a veces los avisos no se etiquetan así)
    (f"{BASE}/casas/venta/castelar-norte/dolares-175000-250000", "Castelar Norte"),
    (f"{BASE}/casas/venta/ituzaingo-norte/dolares-175000-250000", "Ituzaingó Norte"),
    # Rango más amplio (algunos están en USD 150-300k)
    (f"{BASE}/casas/venta/castelar-norte/dolares-150000-300000", "Castelar Norte"),
    (f"{BASE}/casas/venta/ituzaingo-norte/dolares-150000-300000", "Ituzaingó Norte"),
    # Sin filtro de precio (último recurso)
    (f"{BASE}/casas/venta/castelar-norte", "Castelar Norte"),
    (f"{BASE}/casas/venta/ituzaingo-norte", "Ituzaingó Norte"),
]


def scrape():
    session = make_session()
    results = []
    seen_urls = set()

    for search_url, default_zona in SEARCH_URLS:
        log.info(f"  → {search_url}")
        r = fetch(session, search_url)
        if not r:
            log.warning(f"    Sin respuesta")
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        # Probar múltiples selectores conocidos de Argenprop
        cards = []
        for sel in [
            "div.listing__item",
            "div[class*='listing-item']",
            "div[class*='listing-card']",
            "a[class*='card']",
            "article[class*='card']",
        ]:
            cards = soup.select(sel)
            if cards:
                log.info(f"    selector '{sel}' → {len(cards)} cards")
                break

        # Fallback: buscar todos los links a /propiedades/
        if not cards:
            cards = soup.select("a[href*='/propiedades/']")
            log.info(f"    fallback links → {len(cards)} links")

        if not cards:
            log.warning(f"    cero matches en HTML")
            continue

        for card in cards[:50]:
            try:
                # Encontrar el link al detalle
                if card.name == "a":
                    href = card.get("href")
                else:
                    a = card.select_one("a[href*='/propiedades/']")
                    href = a.get("href") if a else None
                if not href:
                    continue
                url = urljoin(BASE, href)
                if "/propiedades/" not in url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Datos rápidos del card (no siempre vienen)
                container = card if card.name != "a" else (card.parent or card)
                container_text = container.get_text(" ", strip=True)

                # Imagen
                img_el = container.select_one("img")
                image = None
                if img_el:
                    image = img_el.get("data-src") or img_el.get("data-image") or img_el.get("src")
                    if image and image.startswith("//"):
                        image = "https:" + image

                # Ir al detalle del aviso para info completa
                detail = fetch(session, url)
                if not detail:
                    continue
                ds = BeautifulSoup(detail.text, "html.parser")

                # JSON-LD si existe (mejor fuente de datos)
                jsonld = {}
                for s in ds.select("script[type='application/ld+json']"):
                    try:
                        d = json.loads(s.string)
                        if isinstance(d, dict):
                            jsonld.update(d)
                        elif isinstance(d, list):
                            for x in d:
                                if isinstance(x, dict): jsonld.update(x)
                    except Exception:
                        continue

                # Título
                title = (
                    jsonld.get("name") or
                    (ds.select_one("h1") and ds.select_one("h1").get_text(" ", strip=True)) or
                    "Casa en venta"
                )

                # Precio
                price = None
                offer = jsonld.get("offers", {})
                if isinstance(offer, dict):
                    cur = offer.get("priceCurrency")
                    p = offer.get("price")
                    if p and (cur == "USD" or not cur):
                        try: price = int(float(p))
                        except: pass

                if price is None:
                    price_el = ds.select_one(".price-tag, [class*='price'], .titlebar__price")
                    if price_el:
                        price = parse_price(price_el.get_text(" ", strip=True))

                # Descripción
                desc_el = ds.select_one(".section-description, [class*='description'], .property-description, #section-description")
                desc = desc_el.get_text(" ", strip=True) if desc_el else ""
                if not desc:
                    desc = jsonld.get("description", "")

                # Address
                address = ""
                addr_obj = jsonld.get("address", {})
                if isinstance(addr_obj, dict):
                    address = addr_obj.get("streetAddress") or addr_obj.get("name") or ""
                if not address:
                    addr_el = ds.select_one(".titlebar__address, [class*='address'], .property-address")
                    if addr_el:
                        address = addr_el.get_text(" ", strip=True)

                # Features
                feats_text = ""
                for f in ds.select(".features li, .property-features li, [class*='features'] li"):
                    feats_text += " " + f.get_text(" ", strip=True)

                combined = (title or "") + " " + (desc or "") + " " + feats_text

                beds = extract_beds(combined)
                baths = extract_baths(combined)
                garage = extract_garages(combined)
                sup_total, sup_cub = extract_surface(combined)

                if not image:
                    main_img = ds.select_one("meta[property='og:image']")
                    if main_img:
                        image = main_img.get("content")

                # Zona
                tlow = (address + " " + title).lower()
                if "castelar norte" in tlow:
                    zona = "Castelar Norte"
                elif "ituzaingó norte" in tlow or "ituzaingo norte" in tlow:
                    zona = "Ituzaingó Norte"
                else:
                    zona = default_zona

                # Coords desde JSON-LD
                lat = lng = None
                geo = jsonld.get("geo")
                if isinstance(geo, dict):
                    try:
                        lat = float(geo.get("latitude"))
                        lng = float(geo.get("longitude"))
                    except (TypeError, ValueError):
                        pass

                results.append(Listing(
                    id=make_id(PORTAL, url),
                    title=title[:120],
                    address=address[:160],
                    zona=zona,
                    portal=PORTAL,
                    url=url,
                    price=price,
                    beds=beds, baths=baths, garage=garage,
                    sup_total=sup_total, sup_cub=sup_cub,
                    desc=desc[:800],
                    image=image,
                    lat=lat, lng=lng,
                ))
            except Exception as e:
                log.warning(f"    Error parseando: {e}")
                continue

    log.info(f"  TOTAL Argenprop: {len(results)}")
    return results
