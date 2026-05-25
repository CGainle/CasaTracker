# Casa Tracker · Castelar Norte / Ituzaingó Norte

Sistema automático de búsqueda de casas en venta. Corre todos los días a las 0 hs de Argentina, scrapea 12 fuentes distintas, filtra por tus criterios, y publica los resultados en una PWA instalable.

## 🏗️ Cómo funciona

```
┌──────────────────────┐
│ GitHub Actions       │
│ Cron diario 0:00 AR  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────────────────────┐
│ scraper/scrape.py recorre:           │
│  • ZonaProp · Argenprop              │
│  • MercadoLibre · Properati          │
│  • Corigliano · Pappacena Carbone    │
│  • Julio Carfi · Eduardo Carfi       │
│  • Ferrero · Taburet                 │
│  • Matias Szpira · Clarín            │
└──────────┬───────────────────────────┘
           │
           ▼
   Filtra por criterios + geofence
           │
           ▼
   Escribe docs/listings.json
           │
           ▼
┌──────────────────────────────────────┐
│ GitHub Pages sirve la PWA            │
│ El celu lee listings.json al abrir   │
└──────────────────────────────────────┘
```

## 🚀 Instalación (paso a paso)

### 1. Crear repo en GitHub

1. Andá a [github.com/new](https://github.com/new)
2. Nombre: `casatracker` (o el que quieras)
3. **Public** (necesario para GitHub Pages gratis)
4. **NO** marques "Add a README" — vamos a subir el nuestro
5. Create repository

### 2. Subir los archivos

**Opción A — desde la web (fácil):**

1. Descomprimí el zip que te dio Claude
2. En el repo recién creado, hacé clic en "uploading an existing file"
3. Arrastrá **todo el contenido** de la carpeta `casatracker/` (no la carpeta, su contenido)
4. Hacé clic en "Commit changes"

**Opción B — con git (si lo tenés):**

```bash
cd casatracker
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/casatracker.git
git push -u origin main
```

### 3. Activar GitHub Pages

1. En tu repo, andá a **Settings** (arriba a la derecha)
2. En el menú izquierdo, **Pages**
3. Source: **Deploy from a branch**
4. Branch: **main**
5. Folder: **/docs**
6. **Save**

En 1-2 minutos la URL `https://TU_USUARIO.github.io/casatracker/` va a funcionar.

### 4. Activar GitHub Actions

1. Andá a la pestaña **Actions** del repo
2. Si te muestra un cartel, hacé clic en "I understand my workflows, enable them"
3. Vas a ver el workflow "Daily Scrape" listado
4. Hacé clic en él, después **"Run workflow"** → **Run workflow** para correrlo manualmente esta primera vez
5. Esperá ~5 minutos. Cuando termine, va a haber commiteado un `docs/listings.json` con avisos reales

### 5. Instalar en el celu

1. Abrí `https://TU_USUARIO.github.io/casatracker/` en el celu
2. **Android (Chrome):** menú ⋮ → "Instalar app"
3. **iPhone (Safari):** botón compartir → "Agregar a pantalla de inicio"

Listo. Aparece en la pantalla principal con tu logo. Cada vez que abras la app, se descarga el `listings.json` más reciente.

## ⚙️ Personalización

### Cambiar filtros default

Editá `scraper/filters.py`:

```python
PRICE_MIN_USD = 175_000
PRICE_MAX_USD = 250_000
MIN_BEDROOMS = 3
MIN_BATHROOMS = 2
MIN_GARAGES = 1
```

### Cambiar el polígono de búsqueda

Editá `scraper/geofence.py` → `POLYGON`. Cada par es `(longitud, latitud)`.

### Agregar otra inmobiliaria

1. En `scraper/portales/inmobiliarias.py`, agregá una función nueva tipo:

```python
def scrape_nueva():
    return _scrape_generic(
        "Nueva Inmobiliaria",
        "https://nueva-inmob.com.ar",
        "https://nueva-inmob.com.ar/casas/venta",
        "a[href*='/propiedad/']",
    )
```

2. Agregala a la lista `SCRAPERS` en `scraper/scrape.py`

### Disparar una búsqueda manual

En la pestaña **Actions** del repo → "Daily Scrape" → "Run workflow".

## 🐛 Troubleshooting

**El workflow falla / aparece en rojo en Actions**

Abrí el run que falló y mirá los logs. Lo más común es que ZonaProp bloquea Playwright. Eso está esperado — los otros 11 scrapers siguen corriendo y los avisos de Argenprop/ML/Properati ya son la mayoría.

**El sitio web no muestra nada**

Verificá que `docs/listings.json` se haya commiteado (Actions tab → último run → debería haber un commit "🏠 Daily scrape …"). Si no, corré el workflow manualmente.

**Los íconos no aparecen al instalar la PWA**

Asegurate que `manifest.json`, `icon-192.png`, `icon-512.png` etc. están todos en `docs/`.

## 🔧 Correr localmente (opcional, para debug)

```bash
cd scraper
pip install -r requirements.txt
python -m playwright install chromium
python scrape.py --no-zonaprop      # más rápido sin Playwright
```

Para ver el sitio:

```bash
cd docs
python -m http.server 8000
# abrir http://localhost:8000
```

## 📂 Estructura

```
casatracker/
├── scraper/
│   ├── scrape.py             # orquestador principal
│   ├── common.py             # HTTP, geocoder, schema
│   ├── filters.py            # criterios + heurísticas
│   ├── geofence.py           # polígono Castelar/Ituzaingó
│   ├── portales/
│   │   ├── argenprop.py
│   │   ├── zonaprop.py       # con Playwright
│   │   ├── properati.py
│   │   ├── mercadolibre.py   # API JSON
│   │   ├── inmobiliarias.py  # Corigliano, Carfi, etc
│   │   └── szpira_clarin.py  # vía Argenprop
│   └── requirements.txt
├── docs/                      # la PWA
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── manifest.json
│   ├── listings.json         # generado por el scraper
│   └── icon-*.png
└── .github/workflows/
    └── daily.yml             # cron diario
```

## ⚠️ Notas técnicas

- **ZonaProp** tiene anti-bot (DataDome). Funciona la mayoría de los días pero a veces puede fallar. Si te falla mucho, comentá la línea en `SCRAPERS` y queda el resto.
- **MercadoLibre** usa su API pública JSON, mucho más confiable que scraping.
- **Las inmobiliarias** funcionan con requests + BeautifulSoup, sin problemas.
- **El geocoder** usa Nominatim de OpenStreetMap (1 req/segundo, gratis).
- **Los datos guardados localmente** (visto/no visto, filtros, conocidos) viven en `localStorage` del navegador. Se pierden si limpiás el storage o reinstalás la PWA.

## 💰 Costo

Todo gratis:

- GitHub: gratis (repo public)
- GitHub Actions: 2000 minutos/mes gratis. Esto usa ~5 min/día = 150 min/mes
- GitHub Pages: gratis
- Nominatim (geocoding): gratis
- OpenStreetMap tiles: gratis
- Sin servidor propio, sin base de datos, sin scraping de pago

---

Si necesitás ayuda, abrí un issue o pegale los logs de un run fallido a Claude.
