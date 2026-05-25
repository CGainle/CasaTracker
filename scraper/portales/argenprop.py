"""
Argenprop scraper (v3).

Lección aprendida del log anterior:
- Los selectores `div.listing__item` SÍ funcionan (vimos 20 cards por página)
- Pero el filtro `"/propiedades/" in url` rechazaba TODO porque Argenprop
  usa URLs como `/casa-en-venta-en-castelar-norte-..-12345`

Esta versión:
- Extrae todo del CARD directamente (sin necesidad de pegarle al detalle)
- Solo va al detalle si hace falta más info
- Acepta cualquier URL absoluta de argenprop.com
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

SEARCH_URLS = [
    (f"{BASE}/casas/venta/castelar-norte/dolares-175000-250000", "Castelar Norte"),
    (f"{BASE}/casas/venta/ituzaingo-norte/dolares-175000-250000", "Ituzaingó Norte"),
    (f"{BASE}/casas/venta/castelar-norte/3-ambientes/dolares-175000-250000", "Castelar Norte"),
    (f"{BASE}/casas/venta/ituzaingo-norte/3-ambientes/dolares-175000-250000", "Ituzaingó Norte"),
    # Range más amplio por si hay precios cerca del límite
    (f"{BASE}/casas/venta/castelar-norte/dolares-150000-275000", "Castelar Norte"),
    (f"{BASE}/casas/venta/ituzaingo-norte/dolares-150000-275000", "Ituzaingó Norte"),
]


def _looks_like_detail_url(href: str) -> bool:
    """Argenprop detail URLs: termina en `--<id>` o tiene `/propiedad`."""
    if not href: return False
    h = href.lower()
    if "argenprop.com" not in h and not h.startswith("/"):
        return False
    # Excluir listados
    if any(x in h for x in ["?page=", "/buscar", "/casas/venta/", "/casas/alquiler/"]):
        # /casas/venta/ es para LISTADOS; los detalles son /casa-en-venta-...
        if "/casa-en-venta" not in h and "/propiedad" not in h:
            return False
    # Aceptar patrones de detalle
    if "/casa-en-venta" in h or "/propiedad" in h or re.search(r"--\d+(/|$|\?)", h):
        return True
    return False


def scrape():
    session = make_session()
    results = []
    seen_urls = set()

    for search_url, default_zona in SEARCH_URLS:
        log.info(f"  → {search_url}")
        r = fetch(session, search_url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        # Cards
        cards = soup.select("div.listing__item")
        if not cards:
            cards = soup.select("[class*='listing-item'], [class*='listing-card'], article[class*='card']")
        log.info(f"    {len(cards)} cards")

        for card in cards:
            try:
                # Link al detalle — el card es un <div>, busca el <a> adentro
                a = card.select_one("a[href]")
                if not a:
                    continue
                href = a.get("href")
                if not href or not _looks_like_detail_url(href):
                    continue
                url = urljoin(BASE, href)
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Datos directo del card preview — Argenprop los pone visibles
                card_text = card.get_text(" ", strip=True)

                # Precio (con clase específica o cualquier elemento que tenga "USD")
                price_text = ""
                for sel in [".card__price", "[class*='price']", "[class*='Price']"]:
                    el = card.select_one(sel)
                    if el and ("USD" in el.get_text() or "U$S" in el.get_text() or "u$s" in el.get_text().lower()):
                        price_text = el.get_text(" ", strip=True)
                        break
                if not price_text:
                    # Buscar en cualquier texto del card
                    m = re.search(r"(?:USD|U\$S|u\$s)\s*([\d.,]+)", card_text, re.IGNORECASE)
                    if m:
                        price_text = m.group(0)
                price = parse_price(price_text)

                # Dirección
                addr = ""
                for sel in [".card__address", "[class*='address']", "[class*='location']"]:
                    el = card.select_one(sel)
                    if el:
                        addr = el.get_text(" ", strip=True)
                        break

                # Título
                title_el = card.select_one("h2, h3, [class*='title']")
                title = title_el.get_text(" ", strip=True) if title_el else "Casa en venta"

                # Imagen
                image = None
                img = card.select_one("img")
                if img:
                    image = img.get("data-src") or img.get("src") or img.get("data-image")
                    if image and image.startswith("//"):
                        image = "https:" + image
                    if image and image.startswith("data:"):
                        image = None

                # Specs del card (ambientes, dormitorios, baños, etc.)
                features_text = ""
                for f in card.select("[class*='feature'], li, .features li"):
                    features_text += " " + f.get_text(" ", strip=True)

                combined = title + " " + features_text + " " + card_text

                beds = extract_beds(combined)
                baths = extract_baths(combined)
                garage = extract_garages(combined)
                sup_total, sup_cub = extract_surface(combined)

                # Descripción (cortita, del preview)
                desc_el = card.select_one(".card__description, [class*='description']")
                desc = desc_el.get_text(" ", strip=True) if desc_el else card_text[:400]

                results.append(Listing(
                    id=make_id(PORTAL, url),
                    title=title[:120],
                    address=addr[:160],
                    zona=default_zona,
                    portal=PORTAL,
                    url=url,
                    price=price,
                    beds=beds, baths=baths, garage=garage,
                    sup_total=sup_total, sup_cub=sup_cub,
                    desc=desc[:500],
                    image=image,
                ))
            except Exception as e:
                log.warning(f"    Error parseando card: {e}")
                continue

    log.info(f"  TOTAL Argenprop: {len(results)}")
    return results
