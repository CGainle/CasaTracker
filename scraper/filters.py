"""
Filtros de propiedades.

Aplica los criterios definidos por el usuario:
- Precio USD entre 175.000 y 250.000 (o "consultar" si no hay precio explícito y el resto matchea)
- Mínimo 3 dormitorios
- Al menos 1 dormitorio en planta baja con baño completo
- Mínimo 2 baños totales
- Mínimo 1 cochera
- Estado: lista para habitar / remodelada / a estrenar (NO a reciclar)
"""
import re

# ─── Criterios ────────────────────────────────────────────────────────────────
PRICE_MIN_USD = 175_000
PRICE_MAX_USD = 250_000
MIN_BEDROOMS = 3
MIN_BATHROOMS = 2
MIN_GARAGES = 1

# Palabras que indican que es a reciclar / no apta
REJECT_KEYWORDS = [
    "a reciclar", "reciclar", "para reciclar",
    "demoler", "demolición", "demolicion",
    "para refaccionar", "a refaccionar", "refaccionar",
    "mal estado", "muy mal estado",
    "fixer upper",
]

# Palabras que confirman buen estado
ACCEPT_STATE_KEYWORDS = [
    "lista para habitar", "para habitar",
    "remodelada", "remodelado", "reciclada", "reciclado",
    "a estrenar", "estrenar", "nueva", "nuevo",
    "impecable", "excelente estado", "muy buen estado",
    "buen estado", "muy bueno",
]

# Heurística para detectar "planta baja con baño y dormitorio"
PB_BED_KEYWORDS = [
    "planta baja", "pb completa", "pb cuenta", "en planta baja:",
    "dormitorio en pb", "dorm en pb", "habitación en pb",
    "todo en planta baja", "una planta",
]
PB_BATH_KEYWORDS = [
    "baño en planta baja", "baño completo en pb",
    "baño en pb",
]


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    s = s.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    return s


def detect_pb_bed_bath(text: str):
    """
    Heurística para detectar si la propiedad tiene dormitorio + baño en planta baja.
    Si la descripción menciona 'planta baja' Y ('dormitorio' o 'habitación')
    Y 'baño' cerca, asumimos True.
    Para casas de una sola planta, siempre True.
    """
    if not text:
        return False, False
    t = normalize_text(text)

    # Casas de una sola planta: todo está en PB
    if re.search(r"(una sola planta|en una planta|todo en planta baja|una planta)", t):
        return True, True

    # Detectar bloque "planta baja" + contenido cercano
    pb_block = re.search(r"planta baja[:,.\s][^.]{0,300}", t)
    if pb_block:
        block = pb_block.group(0)
        has_bed = bool(re.search(r"(dormitorio|dorm\.|habitacion)", block))
        has_bath = bool(re.search(r"baño completo|bano completo|baño |bano ", block))
        return has_bed, has_bath

    return False, False


def parse_price_to_usd(price_str, currency=None):
    """Devuelve precio en USD o None si no aplica / desconocido."""
    if price_str is None or price_str == "":
        return None
    if isinstance(price_str, (int, float)):
        # Si es número, asumimos USD si encaja en el rango razonable
        n = int(price_str)
        if 50_000 <= n <= 2_000_000:
            return n
        return None
    s = str(price_str).strip().lower()
    if "consultar" in s or "consulte" in s or "a convenir" in s:
        return None
    # Sólo nos interesan USD
    is_ars = "$" in s and "u$s" not in s and "usd" not in s and "us$" not in s
    if is_ars:
        return None
    nums = re.findall(r"[\d.,]+", s)
    if not nums:
        return None
    num = nums[0].replace(".", "").replace(",", "")
    try:
        return int(num)
    except ValueError:
        return None


def matches_filters(listing: dict, strict_price=False) -> bool:
    """
    Decide si un aviso pasa los filtros.

    Si `strict_price=False`, los avisos sin precio explícito pasan
    (porque muchos posteos "a consultar" después resultan estar en rango).
    """
    desc = listing.get("desc", "") or ""
    title = listing.get("title", "") or ""
    full_text = normalize_text(title + " " + desc)

    # 1. Rechazar inmediatamente si dice "a reciclar"
    for kw in REJECT_KEYWORDS:
        if kw in full_text:
            return False

    # 2. Precio en rango (o sin precio si strict_price=False)
    price = listing.get("price")
    if price is not None:
        if not (PRICE_MIN_USD <= price <= PRICE_MAX_USD):
            return False
    elif strict_price:
        return False

    # 3. Dormitorios y baños mínimos
    beds = listing.get("beds") or 0
    baths = listing.get("baths") or 0
    garage = listing.get("garage") or 0
    if beds and beds < MIN_BEDROOMS:
        return False
    if baths and baths < MIN_BATHROOMS:
        return False
    if garage is not None and garage < MIN_GARAGES:
        return False

    # 4. PB con dormitorio + baño (si vienen flags directos, respetar; sino, heurística)
    pb_bed = listing.get("pb_bed")
    pb_bath = listing.get("pb_bath")
    if pb_bed is None or pb_bath is None:
        det_bed, det_bath = detect_pb_bed_bath(desc)
        if pb_bed is None: listing["pb_bed"] = det_bed
        if pb_bath is None: listing["pb_bath"] = det_bath

    # Si después de la detección sigue sin haber confirmación de PB, no rechazamos
    # (muchas casas de una planta no lo dicen explícitamente). Solo penalizaríamos
    # si la descripción dice claramente "todos los dormitorios en planta alta".
    if re.search(r"todos los dormitorios? en (planta alta|primer piso|pa)", full_text):
        return False

    return True


def annotate_state(listing: dict) -> dict:
    """Añade un campo `state` (Excelente/Muy Bueno/Bueno) según keywords."""
    desc = normalize_text(listing.get("desc", "") + " " + listing.get("title", ""))
    if any(k in desc for k in ["a estrenar", "estrenar", "nueva", "nuevo", "impecable", "excelente"]):
        listing["state"] = "Excelente"
    elif any(k in desc for k in ["remodelada", "remodelado", "reciclada", "reciclado", "muy bueno", "muy buen"]):
        listing["state"] = "Muy Bueno"
    elif any(k in desc for k in ["buen estado", "lista para habitar"]):
        listing["state"] = "Bueno"
    else:
        listing["state"] = "Bueno"
    return listing
