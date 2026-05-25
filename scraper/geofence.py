"""
Geofence — Polígono que delimita la zona de búsqueda.

Define el área entre Castelar Norte e Ituzaingó Norte, delimitada por:
- Vía del FFCC Sarmiento (sur)
- Calle Ranchos (este, Castelar)
- Calle Gral. Machado
- Calle Pontevedra
- Calle Paysandú
- C. José María Paz (centro)
- Bacacay
- Manuel Rodríguez Fragio (oeste, Ituzaingó)

Si un aviso tiene lat/lng se chequea contra el polígono.
Si no, se intenta geocodificar la dirección.
Si tampoco se puede, se chequea por barrio (zona) + heurística de calle.
"""

# Polígono en formato (lon, lat) — coordenadas aproximadas siguiendo las calles límite
# Se rodea la zona en sentido horario empezando por el extremo sudeste (Vía FFCC + Ranchos)
POLYGON = [
    (-58.6438, -34.6510),  # Vía FFCC y Ranchos (Castelar)
    (-58.6438, -34.6420),  # Ranchos subiendo
    (-58.6470, -34.6395),  # Gral. Machado
    (-58.6520, -34.6385),  # Pontevedra
    (-58.6580, -34.6380),  # Paysandú
    (-58.6650, -34.6388),  # José María Paz
    (-58.6720, -34.6395),  # cruzando hacia Ituzaingó
    (-58.6780, -34.6405),  # Bacacay
    (-58.6810, -34.6440),  # Manuel Rodríguez Fragio
    (-58.6820, -34.6510),  # de vuelta a la Vía
    (-58.6700, -34.6515),  # Vía del FFCC (lado Ituzaingó)
    (-58.6550, -34.6515),  # Vía cruzando el centro
    (-58.6438, -34.6510),  # cierre
]


def point_in_polygon(lon: float, lat: float, poly=POLYGON) -> bool:
    """Algoritmo ray casting clásico. Devuelve True si (lon,lat) cae dentro."""
    if lon is None or lat is None:
        return False
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


# Bounding box rápido para descartar antes de hacer el cálculo polígono completo
BBOX = {
    "minLon": min(p[0] for p in POLYGON),
    "maxLon": max(p[0] for p in POLYGON),
    "minLat": min(p[1] for p in POLYGON),
    "maxLat": max(p[1] for p in POLYGON),
}


def in_bbox(lon, lat) -> bool:
    if lon is None or lat is None:
        return False
    return (BBOX["minLon"] <= lon <= BBOX["maxLon"]
            and BBOX["minLat"] <= lat <= BBOX["maxLat"])


def in_zone(lon, lat) -> bool:
    """Chequeo definitivo: dentro del bbox y dentro del polígono."""
    return in_bbox(lon, lat) and point_in_polygon(lon, lat)


# Lista de barrios aceptados (fallback cuando no hay coordenadas)
ACCEPTED_ZONES = {
    "castelar norte", "castelar", "ituzaingó norte", "ituzaingo norte",
    "ituzaingó", "ituzaingo",
}

# Calles que están claramente fuera (zona sur) para descartar rápido
EXCLUDE_HINTS = [
    "castelar sur", "ituzaingó sur", "ituzaingo sur",
    "san antonio de padua", "morón sur", "moron sur",
    "haedo", "ramos mejía", "ramos mejia",
    "villa udaondo", "parque leloir", "el palomar",
]


def address_in_zone(zona: str, address: str) -> bool:
    """Fallback cuando no hay lat/lng: usa barrio y descarta zonas conocidas afuera."""
    if not zona and not address:
        return False
    text = f"{zona or ''} {address or ''}".lower()
    for ex in EXCLUDE_HINTS:
        if ex in text:
            return False
    for ac in ACCEPTED_ZONES:
        if ac in text:
            return True
    return False
