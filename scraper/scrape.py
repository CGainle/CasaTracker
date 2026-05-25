#!/usr/bin/env python3
"""
Casatracker — orquestador principal.

Corre todos los scrapers, aplica filtros y geofence, y produce listings.json
para que la PWA lo consuma.

Uso:
    python scrape.py             # corre todo
    python scrape.py --no-zonaprop  # saltea ZonaProp (Playwright)
"""
import sys
import os
import json
import logging
import argparse
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Path setup
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import geocode
from filters import matches_filters, annotate_state
from geofence import in_zone, address_in_zone

from portales import argenprop, properati, mercadolibre, zonaprop
from portales import inmobiliarias, szpira_clarin


# ─── Config logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("casatracker")


SCRAPERS = [
    ("Argenprop",         argenprop.scrape),
    ("Properati",         properati.scrape),
    ("MercadoLibre",      mercadolibre.scrape),
    ("ZonaProp",          zonaprop.scrape),
    ("Corigliano",        inmobiliarias.scrape_corigliano),
    ("Pappacena Carbone", inmobiliarias.scrape_pcarbone),
    ("Julio Carfi",       inmobiliarias.scrape_juliocarfi),
    ("Eduardo Carfi",     inmobiliarias.scrape_eduardocarfi),
    ("Ferrero",           inmobiliarias.scrape_ferrero),
    ("Taburet",           inmobiliarias.scrape_taburet),
    ("Matias Szpira",     szpira_clarin.scrape_szpira),
    ("Clarín",            szpira_clarin.scrape_clarin),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-zonaprop", action="store_true", help="Saltear ZonaProp")
    ap.add_argument("--only", help="Solo correr este scraper (nombre)")
    ap.add_argument("--out", default="../docs/listings.json", help="Path del JSON salida")
    args = ap.parse_args()

    log.info("=" * 70)
    log.info("CASATRACKER — empezando scraping diario")
    log.info("=" * 70)

    all_listings = []
    portal_stats = {}

    for name, fn in SCRAPERS:
        if args.only and args.only.lower() not in name.lower():
            continue
        if args.no_zonaprop and name == "ZonaProp":
            log.info(f"⏭  Saltando ZonaProp (--no-zonaprop)")
            continue

        log.info(f"\n┃ {name}")
        try:
            items = fn() or []
            portal_stats[name] = len(items)
            all_listings.extend(items)
        except Exception as e:
            log.error(f"  ❌ {name} crasheó: {e}")
            log.error(traceback.format_exc())
            portal_stats[name] = f"ERROR: {e}"

    log.info(f"\n┃ Total bruto: {len(all_listings)} avisos")

    # ─── Dedupe por URL ────────────────────────────────────────────────────
    seen_urls = set()
    deduped = []
    for l in all_listings:
        if l.url and l.url not in seen_urls:
            seen_urls.add(l.url)
            deduped.append(l)
    log.info(f"┃ Después de dedupe: {len(deduped)}")

    # ─── Aplicar filtros ───────────────────────────────────────────────────
    filtered = []
    for l in deduped:
        d = l.to_dict() if hasattr(l, 'to_dict') else l
        if matches_filters(d):
            annotate_state(d)
            filtered.append(d)
    log.info(f"┃ Después de filtros: {len(filtered)}")

    # ─── Geocodificar los que no tienen lat/lng (con address) ──────────────
    log.info(f"┃ Geocodificando…")
    for l in filtered:
        if l.get("lat") and l.get("lng"):
            continue
        if l.get("address"):
            coords = geocode(l["address"])
            if coords:
                l["lat"], l["lng"] = coords

    # ─── Geofence ──────────────────────────────────────────────────────────
    in_geofence = []
    for l in filtered:
        if l.get("lng") and l.get("lat"):
            if in_zone(l["lng"], l["lat"]):
                in_geofence.append(l)
                continue
        # Fallback por barrio/address
        if address_in_zone(l.get("zona"), l.get("address")):
            in_geofence.append(l)
    log.info(f"┃ Dentro del geofence: {len(in_geofence)}")

    # ─── Fecha ─────────────────────────────────────────────────────────────
    today = datetime.now(timezone.utc).date().isoformat()
    for l in in_geofence:
        l.setdefault("added", today)

    # ─── Mergear con histórico para marcar novedades ──────────────────────
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    previous = []
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8")).get("listings", [])
        except Exception:
            previous = []

    prev_ids = {l["id"] for l in previous}
    for l in in_geofence:
        l["is_new"] = l["id"] not in prev_ids

    # ─── Escribir resultado final ──────────────────────────────────────────
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "stats": {
            "raw": len(all_listings),
            "deduped": len(deduped),
            "filtered": len(filtered),
            "in_geofence": len(in_geofence),
            "new_today": sum(1 for l in in_geofence if l.get("is_new")),
            "by_portal": portal_stats,
        },
        "listings": in_geofence,
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("=" * 70)
    log.info(f"✅ {output_path}")
    log.info(f"   Total: {len(in_geofence)} · Nuevos hoy: {output['stats']['new_today']}")
    log.info(f"   Por portal: {portal_stats}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
