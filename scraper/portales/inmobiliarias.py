"""
Inmobiliarias locales (v3 — más permisivo).

Lección del log: 42 listings de Ferrero pasaron pero todos los descartó el filter
porque metíamos `full[:600]` (texto completo de la página, incluso nav/footer)
en el campo `desc` y ahí aparecían palabras como "refaccionar".

Esta versión:
- NO mete el full page text en `desc`. Solo extrae el bloque de descripción real.
- Filtros mínimos para validar que sea una propiedad de venta en zona.
"""
import logging
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

from common import (
    make_session, fetch, Listing, make_id,
    extract_beds, extract_baths, extract_garages, extract_surface,
)

log = logging.getLogger("casatracker.inmob")


def _is_property_link(href: str) -> bool:
    if not href:
        return False
    h = href.lower()
    if any(p in h for p in [
        "/propiedad/", "/propiedades/", "/inmueble/", "/inmuebles/",
        "/ficha", "/detalle", "ficha.php", "propiedad.php", "id_inmueble", "?id=",
    ]):
        if any(x in h for x in ["page=", "?p=", "/categor", "/buscar", "/alquiler"]):
            return False
        return True
    return False


def _extract_description(ds: BeautifulSoup) -> str:
    """Intenta obtener SOLO la descripción real de la propiedad, no nav/footer."""
    for sel in [
        ".description", ".property-description", "[class*='descripcion']",
        "[class*='Description']", ".detalle-descripcion", ".text-description",
        "#description", "#descripcion", ".tab-description",
        "[itemprop='description']",
    ]:
        el = ds.select_one(sel)
        if el:
            t = el.get_text(" ", strip=True)
            if len(t) > 50:
                return t[:800]
    # Si no encuentro, busco un <p> largo que tenga keywords típicas de descripción
    for p in ds.select("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 80 and any(k in t.lower() for k in [
            "living", "comedor", "cocina", "dormitorio", "jardin", "jardín",
            "cochera", "patio", "fondo", "quincho", "lote"
        ]):
            return t[:800]
    return ""


def _scrape_inmob(portal_name, base_url, listing_urls, zona_default="Castelar Norte"):
    session = make_session()
    results = []
    seen = set()

    if isinstance(listing_urls, str):
        listing_urls = [listing_urls]

    property_urls = set()
    for listing_url in listing_urls:
        log.info(f"  → {portal_name}: {listing_url}")
        r = fetch(session, listing_url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            if _is_property_link(a.get("href")):
                property_urls.add(urljoin(base_url, a.get("href")))
        log.info(f"    {len(property_urls)} URLs acumuladas")

    for url in list(property_urls)[:60]:
        if url in seen: continue
        seen.add(url)
        try:
            detail = fetch(session, url)
            if not detail:
                continue
            ds = BeautifulSoup(detail.text, "html.parser")

            # Título — primero h1, después el <title>
            title = ""
            for sel in ["h1", ".title", "[itemprop='name']"]:
                el = ds.select_one(sel)
                if el:
                    title = el.get_text(" ", strip=True)
                    if title: break
            if not title:
                t = ds.find("title")
                if t: title = t.get_text(" ", strip=True)
            if not title:
                title = "Casa en venta"

            # Descripción real (no full page)
            desc = _extract_description(ds)

            # Verificar zona — buscar en title + URL + descripción primero
            zone_text = (title + " " + url + " " + desc).lower()
            zone_text = (zone_text.replace("á", "a").replace("é", "e")
                         .replace("í", "i").replace("ó", "o").replace("ú", "u"))
            in_zone = any(z in zone_text for z in [
                "castelar norte", "castelar", "ituzaingo norte", "ituzaingo"
            ])
            if not in_zone:
                # fallback: el listado nos llevó acá, probablemente está en zona
                # pero si no se menciona en nada, mejor descartar
                continue

            # Excluir zonas claramente otras (solo si menciona exactamente)
            if any(ex in zone_text for ex in [
                "castelar sur", "ituzaingo sur", "el palomar",
                "parque leloir", "haedo centro"
            ]):
                # Pero solo si NO menciona también la zona buena
                if not any(z in title.lower() for z in ["castelar norte", "ituzaingo norte"]):
                    continue

            # Indicador de venta vs alquiler en el contenido principal
            content_check = (title + " " + desc).lower()
            if "venta" not in content_check and "alquiler" in content_check:
                # Solo alquiler, descartamos
                if "venta" not in url.lower():
                    continue

            # Precio USD
            full_page = ds.get_text(" ", strip=True)
            price = None
            m = re.search(r"(?:u\$s|usd|us\$)\s*([\d.]+)", full_page, re.IGNORECASE)
            if m:
                num = m.group(1).replace(".", "")
                try:
                    p = int(num)
                    if 30_000 <= p <= 5_000_000:
                        price = p
                except ValueError:
                    pass

            # Imagen
            image = None
            og = ds.select_one("meta[property='og:image']")
            if og: image = og.get("content")
            if not image:
                for sel in [".main-image img", ".property-image img", ".slide img",
                           ".gallery img", "img.main", ".featured img"]:
                    el = ds.select_one(sel)
                    if el:
                        image = el.get("src") or el.get("data-src")
                        if image: break
            if image:
                if image.startswith("//"): image = "https:" + image
                elif image.startswith("/"): image = urljoin(base_url, image)

            # Datos numéricos del contenido principal (no full page)
            data_text = title + " " + desc
            beds = extract_beds(data_text) or extract_beds(full_page[:2000])
            baths = extract_baths(data_text) or extract_baths(full_page[:2000])
            garage = extract_garages(data_text) or extract_garages(full_page[:2000])
            sup_total, sup_cub = extract_surface(data_text)
            if not sup_total:
                sup_total, sup_cub_b = extract_surface(full_page[:2000])
                if not sup_cub: sup_cub = sup_cub_b

            # Zona
            if "castelar norte" in zone_text:
                zona = "Castelar Norte"
            elif "ituzaingo norte" in zone_text:
                zona = "Ituzaingó Norte"
            elif "castelar" in zone_text:
                zona = "Castelar Norte"
            elif "ituzaingo" in zone_text:
                zona = "Ituzaingó Norte"
            else:
                zona = zona_default

            # Dirección
            address = ""
            m_addr = re.search(
                r"([A-ZÁÉÍÓÚ][a-záéíóú]+(?:\s[A-ZÁÉÍÓÚ][a-záéíóú]+)*\s+\d{2,5})",
                title
            )
            if m_addr:
                address = m_addr.group(1)
            if not address:
                # Buscar en descripción
                m_addr = re.search(
                    r"([A-ZÁÉÍÓÚ][a-záéíóú]+(?:\s[A-ZÁÉÍÓÚ][a-záéíóú]+)*\s+\d{2,5})",
                    desc[:300]
                )
                if m_addr: address = m_addr.group(1)

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
                desc=desc[:700],  # solo descripción real, NO full page text
                image=image,
            ))
        except Exception as e:
            log.warning(f"    Error en {url[:60]}: {e}")
            continue

    log.info(f"  TOTAL {portal_name}: {len(results)}")
    return results


def scrape_corigliano():
    return _scrape_inmob(
        "Corigliano", "https://coriglianopropiedades.com.ar",
        [
            "https://coriglianopropiedades.com.ar/ciudad-propiedad/castelar-norte/",
            "https://coriglianopropiedades.com.ar/ciudad-propiedad/ituzaingo-norte/",
            "https://coriglianopropiedades.com.ar/operacion-propiedad/venta/",
        ],
    )


def scrape_pcarbone():
    return _scrape_inmob(
        "Pappacena Carbone", "https://pcarbone.com",
        ["https://pcarbone.com/inmuebles/venta"],
    )


def scrape_juliocarfi():
    return _scrape_inmob(
        "Julio Carfi", "https://juliocarfi.com.ar",
        [
            "https://juliocarfi.com.ar/listado_propiedades.php",
            "https://juliocarfi.com.ar/listado_propiedades.php?tipo=Venta",
        ],
    )


def scrape_eduardocarfi():
    return _scrape_inmob(
        "Eduardo Carfi", "https://www.carfi.com.ar",
        ["https://www.carfi.com.ar/"],
    )


def scrape_ferrero():
    return _scrape_inmob(
        "Ferrero", "https://inmobiliariaferrero.com",
        [
            "https://inmobiliariaferrero.com/venta/casas/zona-Castelar+Norte",
            "https://inmobiliariaferrero.com/venta/casas/zona-Ituzaingo+Norte",
        ],
    )


def scrape_taburet():
    return _scrape_inmob(
        "Taburet", "https://www.taburet.com.ar",
        ["https://www.taburet.com.ar/Propiedades"],
    )
