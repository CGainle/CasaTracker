"""
Utilidades compartidas entre todos los scrapers.

- Sesión HTTP con headers de browser real
- Reintentos exponenciales
- Geocoder usando Nominatim (gratis, respetando rate limit)
- Schema de Listing
"""
import time
import json
import hashlib
import logging
import re
from dataclasses import dataclass, asdict, field
from typing import Optional
import requests

log = logging.getLogger("casatracker")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def fetch(session, url, *, timeout=20, retries=3, backoff=1.5):
    """GET con reintentos y backoff."""
    last_err = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 503):
                wait = (backoff ** attempt) * 2
                log.warning(f"  HTTP {r.status_code} en {url[:80]}, esperando {wait:.1f}s")
                time.sleep(wait)
                continue
            log.warning(f"  HTTP {r.status_code} en {url[:80]}")
            return None
        except requests.RequestException as e:
            last_err = e
            log.warning(f"  Error de red en {url[:80]}: {e}")
            time.sleep(backoff ** attempt)
    log.error(f"  Falló definitivamente: {url[:80]} ({last_err})")
    return None


# ─── Geocoder ─────────────────────────────────────────────────────────────────
_geocache = {}
_last_geo_call = [0.0]


def geocode(address: str) -> Optional[tuple]:
    """
    Devuelve (lat, lng) o None. Usa Nominatim (1 req/seg max).
    Cachea en memoria durante la corrida.
    """
    if not address:
        return None
    key = address.lower().strip()
    if key in _geocache:
        return _geocache[key]

    # Respetar 1 req/seg
    elapsed = time.time() - _last_geo_call[0]
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    # Sesgar la query con "Buenos Aires, Argentina"
    full = f"{address}, Buenos Aires, Argentina"
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": full, "format": "json", "limit": 1, "countrycodes": "ar"},
            headers={"User-Agent": "casatracker/1.0 (personal use)"},
            timeout=15,
        )
        _last_geo_call[0] = time.time()
        if r.status_code == 200:
            data = r.json()
            if data:
                lat = float(data[0]["lat"])
                lng = float(data[0]["lon"])
                _geocache[key] = (lat, lng)
                return (lat, lng)
    except Exception as e:
        log.warning(f"  Geocoding falló para {address}: {e}")
    _geocache[key] = None
    return None


# ─── Listing schema ───────────────────────────────────────────────────────────
@dataclass
class Listing:
    id: str
    title: str
    address: str
    zona: str           # "Castelar Norte" o "Ituzaingó Norte"
    portal: str         # "ZonaProp", "Argenprop", etc.
    url: str            # link directo al aviso
    price: Optional[int] = None       # USD
    beds: Optional[int] = None
    baths: Optional[int] = None
    garage: Optional[int] = None
    sup_total: Optional[int] = None
    sup_cub: Optional[int] = None
    pb_bed: Optional[bool] = None
    pb_bath: Optional[bool] = None
    state: Optional[str] = None
    desc: str = ""
    image: Optional[str] = None       # URL de imagen
    lat: Optional[float] = None
    lng: Optional[float] = None
    added: str = ""                   # ISO date
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d.pop("raw", None)
        return d


def make_id(portal: str, url: str) -> str:
    """ID determinístico estable basado en portal + URL."""
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    return f"{portal.lower()}_{h}"


# ─── Helpers de parseo de texto ───────────────────────────────────────────────
def extract_int(text: str, patterns) -> Optional[int]:
    """Busca el primer match numérico de cualquiera de los patterns regex."""
    if not text:
        return None
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1).replace(".", "").replace(",", ""))
            except (ValueError, IndexError):
                continue
    return None


def extract_beds(text: str) -> Optional[int]:
    return extract_int(text, [
        r"(\d+)\s*dormitorios?",
        r"(\d+)\s*dorm\b",
        r"(\d+)\s*habitaciones",
    ])


def extract_baths(text: str) -> Optional[int]:
    return extract_int(text, [
        r"(\d+)\s*baños? completos?",
        r"(\d+)\s*baños?",
    ])


def extract_garages(text: str) -> Optional[int]:
    return extract_int(text, [
        r"(\d+)\s*cocheras?",
        r"(\d+)\s*garage",
        r"cochera (?:para |de )?(\d+)\s*autos?",
        r"garage (?:para |de )?(\d+)\s*autos?",
    ])


def extract_surface(text: str) -> tuple:
    """Devuelve (sup_total, sup_cub) en m²."""
    total = extract_int(text, [
        r"superficie total[:\s]*([\d.,]+)\s*m",
        r"sup\.?\s*total[:\s]*([\d.,]+)",
        r"lote[:\s]*([\d.,]+)\s*m",
        r"terreno[:\s]*([\d.,]+)\s*m",
    ])
    cubierta = extract_int(text, [
        r"superficie cubierta[:\s]*([\d.,]+)\s*m",
        r"sup\.?\s*cubierta[:\s]*([\d.,]+)",
        r"([\d.,]+)\s*m2?\s*cubierto",
    ])
    return total, cubierta


def parse_price(text: str) -> Optional[int]:
    """Extrae precio en USD del texto. Devuelve None si está en pesos o no hay precio."""
    if not text:
        return None
    t = text.lower().replace(",", "").replace(".", "")
    if "consultar" in t or "a convenir" in t:
        return None
    # Detectar USD
    is_usd = bool(re.search(r"u\$s|usd|us\$|d[oó]lares?", text, re.IGNORECASE))
    if not is_usd:
        # Si no dice nada y es número alto, asumimos pesos → descartamos
        m = re.search(r"\$\s*([\d.,]+)", text)
        if m:
            return None
        # Si es solo número grande sin moneda, podría ser USD
        nums = re.findall(r"(\d{5,7})", t)
        if nums:
            return int(nums[0])
        return None
    nums = re.findall(r"(\d{4,7})", t)
    if not nums:
        return None
    return int(nums[0])
