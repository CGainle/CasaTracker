"""
MercadoLibre Inmuebles (v2).

La API pública dio 403 desde GitHub Actions. Cambiamos a scraping HTML directo.
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

log = logging.getLogger("casatracker.mercadolibre")

PORTAL = "MercadoLibre"

SEARCH_URLS = [
    # Castelar (parte de Morón)
    ("https://inmuebles.mercadolibre.com.ar/casas/venta/buenos-aires/moron/castelar/_BEDROOMS_3-*_PriceRange_175000USD-250000USD",
     "Castelar Norte"),
    ("https://inmuebles.mercadolibre.com.ar/casas/venta/buenos-aires/ituzaingo/_BEDROOMS_3-*_PriceRange_175000USD-250000USD",
     "Ituzaingó Norte"),
    # Sin filtro de precio por si los avisos tienen otros valores
    ("https://inmuebles.mercadolibre.com.ar/casas/venta/buenos-aires/moron/castelar/",
     "Castelar Norte"),
    ("https://inmuebles.mercadolibre.com.ar/casas/venta/buenos-aires/ituzaingo/",
     "Ituzaingó Norte"),
]


def scrape():
    session = make_session()
    results = []
    seen = set()

    for search_url, default_zona in SEARCH_URLS:
        log.info(f"  → {search_url[:90]}…")
        r = fetch(session, search_url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        # ML envuelve cada listing en una clase tipo `ui-search-result__wrapper`
        # o `andes-card`. Buscamos cualquier link a /MLA-...
        cards = soup.select("a[href*='/MLA-'], a.ui-search-link")
        log.info(f"    {len(cards)} links detectados")

        for c in cards[:40]:
            try:
                href = c.get("href")
                if not href: continue
                # Limpiar tracking
                url = href.split("#")[0].split("?")[0]
                if url in seen: continue
                seen.add(url)
                # Filtrar solo URLs que parecen detalle de inmueble
                if "/MLA-" not in url and "/casas/" not in url:
                    continue

                # Buscar el contenedor padre del card para extraer datos visibles
                parent = c
                for _ in range(5):
                    parent = parent.parent
                    if not parent: break
                    if parent.name in ("article", "li") or (parent.get("class") and any(
                            "result" in cls or "card" in cls.lower() for cls in parent.get("class"))):
                        break

                container_text = parent.get_text(" ", strip=True) if parent else c.get_text(" ", strip=True)

                # Precio en USD
                price = None
                m = re.search(r"US\$\s*([\d.]+)", container_text)
                if m:
                    try: price = int(m.group(1).replace(".", ""))
                    except: pass

                # Specs del card
                beds = extract_beds(container_text)
                baths = extract_baths(container_text)
                garage = extract_garages(container_text)
                sup_total, sup_cub = extract_surface(container_text)

                # Título y dirección
                title_el = c.select_one("h2, h3, [class*='title']") or c
                title = title_el.get_text(" ", strip=True)[:120]

                # Imagen
                image = None
                img = parent.select_one("img") if parent else None
                if img:
                    image = img.get("data-src") or img.get("src")
                    if image and "data:image" in image:
                        image = img.get("data-src")

                # Address tentativa
                addr = ""
                addr_el = parent.select_one("[class*='location'], [class*='address']") if parent else None
                if addr_el:
                    addr = addr_el.get_text(" ", strip=True)[:160]

                results.append(Listing(
                    id=make_id(PORTAL, url),
                    title=title, address=addr, zona=default_zona,
                    portal=PORTAL, url=url, price=price,
                    beds=beds, baths=baths, garage=garage,
                    sup_total=sup_total, sup_cub=sup_cub,
                    desc=container_text[:500], image=image,
                ))
            except Exception as e:
                log.warning(f"    {e}")
                continue

    log.info(f"  TOTAL MercadoLibre: {len(results)}")
    return results
