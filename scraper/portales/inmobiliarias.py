"""
Scrapers de inmobiliarias locales (v2).

Las webs de inmobiliarias varían mucho. Estrategia genérica:
1. Pedir la URL de listado
2. Encontrar todos los links que parezcan ser de una propiedad
3. Visitar cada link y extraer lo que se pueda
4. Aplicar filtros mínimos (zona + venta)
"""
import logging
import re
import json
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from common import (
    make_session, fetch, Listing, make_id,
    extract_beds, extract_baths, extract_garages, extract_surface, parse_price,
)

log = logging.getLogger("casatracker.inmob")


def _is_property_link(href: str, base_domain: str) -> bool:
    """Heurística: parece link a una página de propiedad individual."""
    if not href: return False
    h = href.lower()
    # Patrones comunes
    if any(p in h for p in [
        "/propiedad/", "/propiedades/", "/inmueble/", "/inmuebles/",
        "/ficha", "/detalle", "/casa/", "/casa-",
        "id_inmueble", "id=", "ficha.php", "propiedad.php"
    ]):
        # Excluir navegación y filtros
        if any(x in h for x in ["page=", "?p=", "/categor", "/buscar", "/alquiler/", "alquiler.php"]):
            return False
        return True
    return False


def _scrape_inmob(portal_name, base_url, listing_urls, zona_default="Castelar Norte"):
    """Scraper genérico para inmobiliarias.

    listing_urls: lista de URLs de listado (uno por barrio).
    """
    session = make_session()
    base_domain = urlparse(base_url).netloc
    results = []
    seen = set()

    # listing_urls puede ser str o lista
    if isinstance(listing_urls, str):
        listing_urls = [listing_urls]

    all_property_urls = set()

    for listing_url in listing_urls:
        log.info(f"  → {portal_name}: {listing_url}")
        r = fetch(session, listing_url)
        if not r:
            log.warning(f"    Sin respuesta")
            continue
        soup = BeautifulSoup(r.text, "html.parser")

        # Recolectar todos los links de propiedades
        for a in soup.select("a[href]"):
            href = a.get("href")
            if _is_property_link(href, base_domain):
                full_url = urljoin(base_url, href)
                all_property_urls.add(full_url)

        log.info(f"    {len(all_property_urls)} URLs de propiedad recolectadas hasta ahora")

    # Visitar cada propiedad
    for url in list(all_property_urls)[:60]:
        if url in seen: continue
        seen.add(url)

        try:
            detail = fetch(session, url)
            if not detail:
                continue
            ds = BeautifulSoup(detail.text, "html.parser")
            full = ds.get_text(" ", strip=True)
            tlow = full.lower()

            # Filtrar: tiene que ser venta y de Castelar/Ituzaingó
            if "alquiler" in tlow[:300] and "venta" not in tlow[:600]:
                continue
            in_zone_text = any(z in tlow for z in [
                "castelar norte", "castelar", "ituzaingo norte", "ituzaingó norte", "ituzaingo", "ituzaingó"
            ])
            if not in_zone_text:
                continue

            # Excluir zonas claramente afuera
            if any(ex in tlow for ex in [
                "castelar sur", "ituzaingó sur", "ituzaingo sur",
                "haedo", "el palomar", "parque leloir"
            ]):
                continue

            # Título
            title_el = ds.select_one("h1") or ds.select_one("h2") or ds.select_one(".title")
            title = title_el.get_text(" ", strip=True) if title_el else "Casa en venta"

            # Precio en USD
            price = None
            m = re.search(r"u\$s\s*([\d.]+)|usd\s*([\d.]+)|us\$\s*([\d.]+)", full, re.IGNORECASE)
            if m:
                num = (m.group(1) or m.group(2) or m.group(3)).replace(".", "").replace(",", "")
                try: price = int(num)
                except: price = None

            # Imagen principal
            image = None
            og = ds.select_one("meta[property='og:image']")
            if og: image = og.get("content")
            if not image:
                img = ds.select_one(".main-image img, .property-image img, .slide img, .gallery img, img.main")
                if img: image = img.get("src") or img.get("data-src")
            if image and image.startswith("/"):
                image = urljoin(base_url, image)
            if image and image.startswith("//"):
                image = "https:" + image

            beds = extract_beds(full)
            baths = extract_baths(full)
            garage = extract_garages(full)
            sup_total, sup_cub = extract_surface(full)

            # Zona
            if "castelar norte" in tlow:
                zona = "Castelar Norte"
            elif "ituzaingo norte" in tlow or "ituzaingó norte" in tlow:
                zona = "Ituzaingó Norte"
            elif "castelar" in tlow:
                zona = "Castelar Norte"  # asumimos norte si no especifica
            elif "ituzaingo" in tlow or "ituzaingó" in tlow:
                zona = "Ituzaingó Norte"
            else:
                zona = zona_default

            # Dirección: extraer del título o buscar patrones
            address = ""
            m_addr = re.search(r"([A-ZÁÉÍÓÚ][a-záéíóú]+(?:\s[A-ZÁÉÍÓÚ][a-záéíóú]+)*\s+\d{1,5})", title)
            if m_addr:
                address = m_addr.group(1)

            # Descripción
            desc_el = ds.select_one(".description, .property-description, [class*='description']")
            desc = desc_el.get_text(" ", strip=True)[:800] if desc_el else full[:600]

            results.append(Listing(
                id=make_id(portal_name, url),
                title=title[:120],
                address=address[:160],
                zona=zona,
                portal=portal_name,
                url=url,
                price=price,
                beds=beds, baths=baths, garage=garage,
                sup_total=sup_total, sup_cub=sup_cub,
                desc=desc,
                image=image,
            ))
        except Exception as e:
            log.warning(f"    Error en {url[:60]}: {e}")
            continue

    log.info(f"  TOTAL {portal_name}: {len(results)}")
    return results


def scrape_corigliano():
    return _scrape_inmob(
        "Corigliano",
        "https://coriglianopropiedades.com.ar",
        [
            "https://coriglianopropiedades.com.ar/ciudad-propiedad/castelar-norte/",
            "https://coriglianopropiedades.com.ar/ciudad-propiedad/ituzaingo-norte/",
            "https://coriglianopropiedades.com.ar/operacion-propiedad/venta/",
        ],
    )


def scrape_pcarbone():
    return _scrape_inmob(
        "Pappacena Carbone",
        "https://pcarbone.com",
        [
            "https://pcarbone.com/inmuebles/venta",
            "https://pcarbone.com/inmuebles",
        ],
    )


def scrape_juliocarfi():
    return _scrape_inmob(
        "Julio Carfi",
        "https://juliocarfi.com.ar",
        [
            "https://juliocarfi.com.ar/listado_propiedades.php",
            "https://juliocarfi.com.ar/",
        ],
    )


def scrape_eduardocarfi():
    return _scrape_inmob(
        "Eduardo Carfi",
        "https://www.carfi.com.ar",
        [
            "https://www.carfi.com.ar/listado.html",
            "https://www.carfi.com.ar/propiedades.html",
            "https://www.carfi.com.ar/",
        ],
    )


def scrape_ferrero():
    return _scrape_inmob(
        "Ferrero",
        "https://inmobiliariaferrero.com",
        [
            "https://inmobiliariaferrero.com/venta/casas/zona-Castelar+Norte",
            "https://inmobiliariaferrero.com/venta/casas/zona-Ituzaingo+Norte",
            "https://inmobiliariaferrero.com/venta/casas",
        ],
    )


def scrape_taburet():
    return _scrape_inmob(
        "Taburet",
        "https://www.taburet.com.ar",
        [
            "https://www.taburet.com.ar/Propiedades",
            "https://www.taburet.com.ar/Propiedades/?operacion=Venta",
        ],
    )
