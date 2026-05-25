#!/usr/bin/env python3
"""
Casatracker — orquestador (v2).

Mejoras:
- Loguea POR QUÉ se rechaza cada listing (con un Counter)
- Resumen final detallado por portal
"""
import sys, os, json, logging, argparse, traceback
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import geocode
from filters import passes_filters, annotate_state
from geofence import in_zone, address_in_zone

from portales import argenprop, properati, mercadolibre, zonaprop
from portales import inmobiliarias, szpira_clarin


logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S")
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
    ap.add_argument("--no-zonaprop", action="store_true")
    ap.add_argument("--only", help="Solo correr scraper que matche este nombre")
    ap.add_argument("--out", default="../docs/listings.json")
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
            log.info(f"⏭  Saltando ZonaProp")
            continue
        log.info(f"\n┃ {name}")
        try:
            items = fn() or []
            portal_stats[name] = {"scraped": len(items)}
            all_listings.extend(items)
        except Exception as e:
            log.error(f"  ❌ {name} crasheó: {e}")
            log.error(traceback.format_exc())
            portal_stats[name] = {"error": str(e)}

    log.info(f"\n┃ Total bruto: {len(all_listings)}")

    # ─── Dedupe ──────────────────────────────────────────────────────
    seen_urls = set()
    deduped = []
    for l in all_listings:
        if l.url and l.url not in seen_urls:
            seen_urls.add(l.url)
            deduped.append(l)
    log.info(f"┃ Tras dedupe: {len(deduped)}")

    # ─── Filtros, con tracking de motivos ────────────────────────────
    reject_reasons = Counter()
    portal_rejects = {}  # portal -> Counter
    filtered = []
    for l in deduped:
        d = l.to_dict()
        portal = d.get("portal", "?")
        portal_rejects.setdefault(portal, Counter())
        reasons = []
        if passes_filters(d, reasons=reasons):
            annotate_state(d)
            filtered.append(d)
            portal_rejects[portal]["✅passed"] += 1
        else:
            for r in reasons:
                reject_reasons[r] += 1
                portal_rejects[portal][r] += 1

    log.info(f"┃ Tras filtros: {len(filtered)}")
    if reject_reasons:
        log.info(f"┃ Motivos de rechazo:")
        for r, n in reject_reasons.most_common(10):
            log.info(f"     {n}x  {r}")
    log.info(f"┃ Por portal:")
    for p, c in portal_rejects.items():
        passed = c.get("✅passed", 0)
        scraped = portal_stats.get(p, {}).get("scraped", 0)
        log.info(f"     {p}: {scraped} scrap → {passed} pasaron")

    # ─── Geocodificar ────────────────────────────────────────────────
    log.info("┃ Geocodificando los que faltan coords…")
    geocoded = 0
    for l in filtered:
        if (not l.get("lat") or not l.get("lng")) and l.get("address"):
            coords = geocode(l["address"])
            if coords:
                l["lat"], l["lng"] = coords
                geocoded += 1
    log.info(f"   {geocoded} geocodificados")

    # ─── Geofence ────────────────────────────────────────────────────
    in_gf = []
    for l in filtered:
        keep = False
        if l.get("lng") and l.get("lat"):
            if in_zone(l["lng"], l["lat"]):
                keep = True
        if not keep and address_in_zone(l.get("zona"), l.get("address")):
            keep = True
        if keep:
            in_gf.append(l)
    log.info(f"┃ Dentro del geofence: {len(in_gf)}")

    # ─── Marcar nuevos ───────────────────────────────────────────────
    today = datetime.now(timezone.utc).date().isoformat()
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    previous = []
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8")).get("listings", [])
        except Exception:
            previous = []
    prev_ids = {l["id"] for l in previous}
    for l in in_gf:
        l.setdefault("added", today)
        l["is_new"] = l["id"] not in prev_ids

    portal_counts = Counter(l["portal"] for l in in_gf)
    log.info(f"┃ Final por portal:")
    for p, n in portal_counts.most_common():
        log.info(f"     {p}: {n}")

    # ─── Escribir ────────────────────────────────────────────────────
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "stats": {
            "raw": len(all_listings),
            "deduped": len(deduped),
            "filtered": len(filtered),
            "in_geofence": len(in_gf),
            "new_today": sum(1 for l in in_gf if l.get("is_new")),
            "by_portal": dict(portal_counts),
            "reject_reasons": dict(reject_reasons.most_common(15)),
        },
        "listings": in_gf,
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info("=" * 70)
    log.info(f"✅ {output_path}")
    log.info(f"   Total: {len(in_gf)} avisos · Nuevos: {output['stats']['new_today']}")
    log.info("=" * 70)


if __name__ == "__main__":
    main()
