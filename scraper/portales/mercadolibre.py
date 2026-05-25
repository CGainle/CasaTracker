"""
MercadoLibre Inmuebles scraper.

MercadoLibre tiene una API pública (sites/MLA/search) que devuelve JSON.
Usamos eso en vez de scrapear HTML.
"""
import logging
import requests
from common import Listing, make_id

log = logging.getLogger("casatracker.mercadolibre")

PORTAL = "MercadoLibre"
API = "https://api.mercadolibre.com/sites/MLA/search"


# IDs de localidades en MLA
LOCATIONS = [
    # (zone_label, location_id, city_search)
    ("Castelar Norte", "TUxBQ0NBUzc3MzU",  "castelar"),    # Castelar dentro de Morón
    ("Ituzaingó Norte", "TUxBQ0lUVTYxOTM", "ituzaingo"),
]


def scrape():
    results = []
    for zona, city_id, city_name in LOCATIONS:
        log.info(f"  → MLA {zona}")
        params = {
            "category": "MLA1466",        # Casas
            "OPERATION": "242075",         # Venta
            "PROPERTY_TYPE": "242060",     # Casa
            "price": "175000USD-250000USD",
            "BEDROOMS": "3-*",
            "FULL_BATHROOMS": "2-*",
            "PARKING_LOTS": "1-*",
            "limit": 50,
            "state": "TUxBUENBUGw3M2E1",   # Buenos Aires
            "city": city_id,
        }
        try:
            r = requests.get(API, params=params, timeout=20)
            if r.status_code != 200:
                log.warning(f"    HTTP {r.status_code}")
                continue
            data = r.json()
        except Exception as e:
            log.warning(f"    Error API: {e}")
            continue

        items = data.get("results", [])
        log.info(f"    {len(items)} resultados")

        for it in items:
            try:
                url = it.get("permalink")
                if not url:
                    continue
                price = it.get("price") if it.get("currency_id") == "USD" else None
                if price is None:
                    continue

                # Atributos
                attrs = {a["id"]: a for a in it.get("attributes", [])}
                def get_num(aid):
                    a = attrs.get(aid)
                    if a:
                        v = a.get("value_struct") or {}
                        try:
                            return int(v.get("number", 0)) or None
                        except Exception:
                            pass
                        try:
                            return int(a.get("value_name", "").split()[0])
                        except Exception:
                            return None
                    return None

                beds = get_num("BEDROOMS")
                baths = get_num("FULL_BATHROOMS")
                garage = get_num("PARKING_LOTS")
                sup_cub = get_num("COVERED_AREA")
                sup_total = get_num("TOTAL_AREA")

                addr_info = it.get("location", {})
                address = ", ".join(filter(None, [
                    addr_info.get("address_line"),
                    addr_info.get("neighborhood", {}).get("name") if isinstance(addr_info.get("neighborhood"), dict) else None,
                ]))

                lat = it.get("location", {}).get("latitude")
                lng = it.get("location", {}).get("longitude")

                results.append(Listing(
                    id=make_id(PORTAL, url),
                    title=it.get("title", "")[:100],
                    address=address[:160] or city_name.title(),
                    zona=zona,
                    portal=PORTAL,
                    url=url,
                    price=price,
                    beds=beds,
                    baths=baths,
                    garage=garage,
                    sup_total=sup_total,
                    sup_cub=sup_cub,
                    desc="",  # ML no devuelve descripción en search; tendríamos que pegarle a /items/{id}
                    image=it.get("thumbnail", "").replace("-I.jpg", "-O.jpg"),
                    lat=lat,
                    lng=lng,
                ))
            except Exception as e:
                log.warning(f"  Error parseando item: {e}")
                continue

    log.info(f"  TOTAL MercadoLibre: {len(results)} avisos")
    return results
