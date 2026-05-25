"""
Filtros de propiedades (v3 — conservadores).

Lección aprendida: las palabras sueltas como "refaccionar" o "mal estado" aparecen
en contextos legítimos ("no necesita refaccionar", "no hay nada en mal estado",
"última refacción 2020") y rechazaban TODO.

Solo rechazamos FRASES MUY ESPECÍFICAS que solo aparecen cuando la propiedad
realmente es a reciclar/demoler.
"""
import re

PRICE_MIN_USD = 175_000
PRICE_MAX_USD = 250_000
MIN_BEDROOMS = 3
MIN_BATHROOMS = 2
MIN_GARAGES = 1

# Frases que SOLO aparecen cuando la propiedad realmente es a reciclar/demoler.
# Tienen que ser específicas — no palabras sueltas.
REJECT_PHRASES = [
    "casa a reciclar",
    "propiedad a reciclar",
    "para reciclar",   # "ideal para reciclar"
    "a reciclar a nuevo",
    "lote con casa a reciclar",
    "lote con construcción a reciclar",
    "ideal demoler",
    "para demoler",
    "apta demoler",
    "demolición total",
    "casa para demoler",
    "fixer upper",
    "venta de lote",   # generalmente significa terreno con casa precaria
    "venta de terreno",
]


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = (s.replace("á", "a").replace("é", "e").replace("í", "i")
           .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
    return s


def detect_pb(text: str):
    """Heurística PB. (has_bed_in_pb, has_bath_in_pb)."""
    if not text:
        return False, False
    t = normalize_text(text)
    # Una sola planta = todo en PB
    if re.search(r"\b(una sola planta|en una planta|una planta\b|propiedad de una planta)\b", t):
        return True, True
    # Bloque "planta baja"
    blk = re.search(r"planta baja[:,.\s][^.]{0,400}", t)
    if blk:
        b = blk.group(0)
        has_bed = bool(re.search(r"(dormitorio|dorm\.|habitacion)", b))
        has_bath = bool(re.search(r"\bbano\b|\bbano completo\b", b))
        return has_bed, has_bath
    return False, False


def passes_filters(listing: dict, reasons: list = None) -> bool:
    """
    Devuelve True si pasa. Si `reasons` se pasa como lista, agrega
    el motivo de rechazo (útil para debug).
    """
    def reject(reason):
        if reasons is not None:
            reasons.append(reason)
        return False

    # Usar solo título + descripción (no full page text)
    title = listing.get("title", "") or ""
    desc = listing.get("desc", "") or ""
    # Limit desc to first 800 chars to avoid matching nav/footer
    text_for_filter = normalize_text((title + " " + desc)[:1500])

    # 1) Rechazos por frases específicas
    for phrase in REJECT_PHRASES:
        if phrase in text_for_filter:
            return reject(f"reject_phrase:{phrase}")

    # 2) Precio en USD: si tiene, debe estar en rango. Si no tiene, pasa.
    price = listing.get("price")
    if price is not None:
        try:
            p = int(price)
            if p < PRICE_MIN_USD * 0.85 or p > PRICE_MAX_USD * 1.10:
                # Un poco de tolerancia para no perder borderline
                return reject(f"price_out_of_range:{p}")
        except (ValueError, TypeError):
            pass  # precio raro, lo dejamos pasar

    # 3) Dormitorios mínimos (si vienen extraídos)
    beds = listing.get("beds")
    if beds is not None and beds > 0 and beds < MIN_BEDROOMS:
        return reject(f"beds:{beds}")

    # 4) Baños — más permisivo (no rechazamos si es null)
    baths = listing.get("baths")
    if baths is not None and baths > 0 and baths < MIN_BATHROOMS:
        return reject(f"baths:{baths}")

    # 5) Cocheras
    garage = listing.get("garage")
    if garage is not None and garage > 0 and garage < MIN_GARAGES:
        return reject(f"garage:{garage}")

    # 6) PB: solo info, no rechaza salvo que diga explícitamente lo contrario
    pb_bed = listing.get("pb_bed")
    pb_bath = listing.get("pb_bath")
    if pb_bed is None or pb_bath is None:
        det_bed, det_bath = detect_pb(desc + " " + title)
        if pb_bed is None: listing["pb_bed"] = det_bed
        if pb_bath is None: listing["pb_bath"] = det_bath

    # 7) Si dice claramente que todo está en PA, rechazar
    if re.search(r"todos los dormitorios? en planta alta|todos los dormitorios? en primer piso",
                 text_for_filter):
        return reject("all_bedrooms_upstairs")

    return True


def annotate_state(listing: dict) -> dict:
    desc = normalize_text((listing.get("desc", "") + " " + listing.get("title", ""))[:800])
    if any(k in desc for k in ["a estrenar", "impecable", "excelente estado", "premium"]):
        listing["state"] = "Excelente"
    elif any(k in desc for k in ["remodelada", "remodelado", "reciclada", "reciclado",
                                  "renovada", "renovado", "puesta a nuevo"]):
        listing["state"] = "Muy Bueno"
    elif any(k in desc for k in ["buen estado", "muy bueno", "muy buen"]):
        listing["state"] = "Muy Bueno"
    elif any(k in desc for k in ["lista para habitar", "para habitar"]):
        listing["state"] = "Bueno"
    else:
        listing["state"] = "Bueno"
    return listing


# Alias de compatibilidad
matches_filters = passes_filters
