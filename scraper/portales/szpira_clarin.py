"""
Matias Szpira y Clarín Clasificados.

Estos dos no tienen catálogo propio scrapeable; publican vía Argenprop.
Reusamos la lógica de Argenprop apuntando a sus perfiles.
"""
import logging
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from common import (
    make_session, fetch, Listing, make_id,
    extract_beds, extract_baths, extract_garages, extract_surface, parse_price,
)

log = logging.getLogger("casatracker.szpira_clarin")


def _scrape_argenprop_anunciante(portal_name, listing_url):
    session = make_session()
    BASE = "https://www.argenprop.com"
    results = []
    seen = set()

    log.info(f"  → {portal_name}: {listing_url}")
    r = fetch(session, listing_url)
    if not r:
        return results
    soup = BeautifulSoup(r.text, "html.parser")

    items = soup.select("a[href*='/propiedades/']")
    for it in items[:40]:
        try:
            url = urljoin(BASE, it.get("href"))
            if url in seen: continue
            seen.add(url)

            d = fetch(session, url)
            if not d: continue
            ds = BeautifulSoup(d.text, "html.parser")
            full = ds.get_text(" ", strip=True)
            tlow = full.lower()

            # Solo Castelar Norte / Ituzaingó Norte
            if not any(z in tlow for z in ["castelar norte", "ituzaingo norte", "ituzaingó norte"]):
                continue
            if "alquiler" in tlow[:300] and "venta" not in tlow[:300]:
                continue
            if any(ex in tlow for ex in ["castelar sur", "ituzaingó sur", "ituzaingo sur"]):
                continue

            title_el = ds.select_one("h1, h2")
            title = title_el.get_text(" ", strip=True) if title_el else "Casa en venta"

            price_el = ds.select_one(".price, .property-price, [class*='price']")
            price = parse_price(price_el.get_text(" ", strip=True) if price_el else "")
            if price is None:
                # Buscar USD en todo el texto
                import re
                m = re.search(r"u\$s\s*([\d.,]+)|USD\s*([\d.,]+)", full, re.IGNORECASE)
                if m:
                    n = (m.group(1) or m.group(2)).replace(".", "").replace(",", "")
                    try: price = int(n)
                    except: price = None

            img_el = ds.select_one("meta[property='og:image']")
            image = img_el.get("content") if img_el else None

            beds = extract_beds(full)
            baths = extract_baths(full)
            garage = extract_garages(full)
            sup_total, sup_cub = extract_surface(full)

            zona = "Castelar Norte" if "castelar norte" in tlow else "Ituzaingó Norte"

            results.append(Listing(
                id=make_id(portal_name, url),
                title=title[:100],
                address="",
                zona=zona,
                portal=portal_name,
                url=url,
                price=price,
                beds=beds, baths=baths, garage=garage,
                sup_total=sup_total, sup_cub=sup_cub,
                desc=full[:600],
                image=image,
            ))
        except Exception as e:
            log.warning(f"  Error: {e}")

    log.info(f"    TOTAL {portal_name}: {len(results)}")
    return results


def scrape_szpira():
    return _scrape_argenprop_anunciante(
        "Matias Szpira",
        "https://www.argenprop.com/matias-szpira/casas/venta",
    )


def scrape_clarin():
    return _scrape_argenprop_anunciante(
        "Clarín",
        "https://www.argenprop.com/clarin-clasificados/casas/venta",
    )
