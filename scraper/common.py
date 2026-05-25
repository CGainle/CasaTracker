"""
Utilidades compartidas.

- Sesión HTTP con headers de browser real
- Reintentos exponenciales, manejo especial de HTTP 202 (Argenprop bot challenge)
- Geocoder Nominatim
- Schema de Listing
"""
import time
import json
import hashlib
import logging
import re
import random
from dataclasses import dataclass, asdict, field
from typing import Optional
import requests

log = logging.getLogger("casatracker")

# User-Agents rotativos (algunos sitios bloquean si siempre el mismo)
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    })
    return s


def fetch(session, url, *, timeout=20, retries=4, backoff=1.5):
    """GET con reintentos. HTTP 202 (Argenprop anti-bot) recibe trato especial."""
    last_err = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 202:
                # Argenprop devuelve 202 cuando piensa que sos bot.
                # Esperar más tiempo y reintentar
                wait = 3 + attempt * 2
                log.info(f"  HTTP 202 (anti-bot) en {url[:70]}, esperando {wait}s")
                time.sleep(wait)
                continue
            if r.status_code in (429, 503):
                wait = (backoff ** attempt) * 3
                log.warning(f"  HTTP {r.status_code} en {url[:80]}, esperando {wait:.1f}s")
                time.sleep(wait)
                continue
            if 400 <= r.status_code < 500:
                # Cliente error, no tiene sentido reintentar
                log.warning(f"  HTTP {r.status_code} en {url[:80]}")
                return None
            log.warning(f"  HTTP {r.status_code} en {url[:80]}")
        except requests.RequestException as e:
            last_err = e
            log.warning(f"  Error de red en {url[:80]}: {e}")
            time.sleep(backoff ** attempt)
    log.warning(f"  Falló definitivamente: {url[:80]}")
    return None


# ─── Geocoder ─────────────────────────────────────────────────────────────────
_geocache = {}
_last_geo_call = [0.0]


def geocode(address: str) -> Optional[tuple]:
    if not address:
        return None
    key = address.lower().strip()
    if key in _geocache:
        return _geocache[key]
    # 1 req/seg max para Nominatim
    elapsed = time.time() - _last_geo_call[0]
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
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
    zona: str
    portal: str
    url: str
    price: Optional[int] = None
    beds: Optional[int] = None
    baths: Optional[int] = None
    garage: Optional[int] = None
    sup_total: Optional[int] = None
    sup_cub: Optional[int] = None
    pb_bed: Optional[bool] = None
    pb_bath: Optional[bool] = None
    state: Optional[str] = None
    desc: str = ""
    image: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    added: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d.pop("raw", None)
        return d


def make_id(portal: str, url: str) -> str:
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    return f"{portal.lower().replace(' ', '_')}_{h}"


# ─── Helpers de parseo ────────────────────────────────────────────────────────
def extract_int(text: str, patterns) -> Optional[int]:
    if not text:
        return None
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                v = int(m.group(1).replace(".", "").replace(",", ""))
                if 0 < v < 100:
                    return v
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
        r"(\d+)\s*garages?",
        r"cochera (?:para |de )?(\d+)\s*autos?",
        r"garage (?:para |de )?(\d+)\s*autos?",
    ])


def extract_surface(text: str) -> tuple:
    def get(patterns):
        if not text: return None
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    v = int(m.group(1).replace(".", "").replace(",", ""))
                    if 20 < v < 5000:
                        return v
                except (ValueError, IndexError):
                    continue
        return None
    total = get([
        r"superficie total[:\s]*([\d.,]+)",
        r"sup\.?\s*total[:\s]*([\d.,]+)",
        r"lote[:\s]*([\d.,]+)",
        r"terreno[:\s]*([\d.,]+)",
    ])
    cubierta = get([
        r"superficie cubierta[:\s]*([\d.,]+)",
        r"sup\.?\s*cubierta[:\s]*([\d.,]+)",
        r"([\d.,]+)\s*m2?\s*cubiertos?",
    ])
    return total, cubierta


def parse_price(text):
    """Extrae precio USD. Si está en pesos o no se entiende, devuelve None."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        n = int(text)
        if 30_000 <= n <= 5_000_000:
            return n
        return None
    s = str(text)
    if "consultar" in s.lower() or "consulte" in s.lower() or "a convenir" in s.lower():
        return None
    # Detectar USD
    is_usd = bool(re.search(r"u\$s|usd|us\$|d[oó]lar", s, re.IGNORECASE))
    # Si dice "$" sin USD, son pesos → ignoramos
    has_peso = "$" in s and not is_usd
    nums = re.findall(r"[\d.]{4,}", s.replace(",", "."))
    if not nums:
        return None
    cleaned = max(nums, key=len).replace(".", "")
    try:
        n = int(cleaned)
    except ValueError:
        return None
    if has_peso and not is_usd:
        return None
    if 30_000 <= n <= 5_000_000:
        return n
    return None
