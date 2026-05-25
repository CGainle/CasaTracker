"""
ZonaProp scraper.

ZonaProp tiene protección anti-bot fuerte (DataDome/Akamai), por eso usamos
Playwright (navegador headless) en vez de requests.

Si Playwright no está disponible (entorno sin browser), devuelve [].
"""
import logging
import re
import asyncio
from common import Listing, make_id, extract_beds, extract_baths, extract_garages, extract_surface, parse_price

log = logging.getLogger("casatracker.zonaprop")

PORTAL = "ZonaProp"
BASE = "https://www.zonaprop.com.ar"

SEARCH_URLS = [
    f"{BASE}/casas-venta-castelar-norte-3-dormitorios-mas-de-175000-menos-de-250000-dolar.html",
    f"{BASE}/casas-venta-ituzaingo-norte-3-dormitorios-mas-de-175000-menos-de-250000-dolar.html",
]


def scrape():
    """Wrapper sync que invoca el flujo async de Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("  Playwright no instalado, salteando ZonaProp")
        return []

    try:
        return asyncio.run(_scrape_async())
    except Exception as e:
        log.error(f"  ZonaProp falló: {e}")
        return []


async def _scrape_async():
    from playwright.async_api import async_playwright

    results = []
    seen_urls = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="es-AR",
        )
        page = await context.new_page()

        for search_url in SEARCH_URLS:
            log.info(f"  → {search_url}")
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(3000)  # let DataDome challenge resolve

                # Aceptar cookies si aparece
                try:
                    await page.click("button:has-text('Aceptar')", timeout=2000)
                except Exception:
                    pass

                # Extraer cards
                cards = await page.query_selector_all("div[data-qa='posting PROPERTY']")
                if not cards:
                    cards = await page.query_selector_all("[data-id]")
                log.info(f"    {len(cards)} cards detectadas")

                zona = "Castelar Norte" if "castelar" in search_url else "Ituzaingó Norte"

                for card in cards[:25]:
                    try:
                        data = await card.evaluate("""(el) => {
                            const link = el.querySelector('a[href*="/propiedades/"]');
                            const price = el.querySelector('[data-qa="POSTING_CARD_PRICE"]');
                            const addr = el.querySelector('[data-qa="POSTING_CARD_LOCATION"]');
                            const title = el.querySelector('h3, [data-qa="POSTING_CARD_DESCRIPTION"]');
                            const feats = el.querySelector('[data-qa="POSTING_CARD_FEATURES"]');
                            const img = el.querySelector('img');
                            return {
                                url: link ? link.href : null,
                                price: price ? price.innerText : '',
                                address: addr ? addr.innerText : '',
                                title: title ? title.innerText : '',
                                features: feats ? feats.innerText : '',
                                image: img ? (img.src || img.dataset.src) : null,
                            };
                        }""")

                        url = data.get("url")
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)

                        price = parse_price(data.get("price", ""))
                        if price is None:
                            continue

                        combined = data.get("title", "") + " " + data.get("features", "")
                        beds = extract_beds(combined)
                        baths = extract_baths(combined)
                        garage = extract_garages(combined)
                        sup_total, sup_cub = extract_surface(combined)

                        results.append(Listing(
                            id=make_id(PORTAL, url),
                            title=(data.get("title") or "Casa en venta")[:100],
                            address=(data.get("address") or "")[:160],
                            zona=zona,
                            portal=PORTAL,
                            url=url,
                            price=price,
                            beds=beds,
                            baths=baths,
                            garage=garage,
                            sup_total=sup_total,
                            sup_cub=sup_cub,
                            desc=data.get("title", "")[:600],
                            image=data.get("image"),
                        ))
                    except Exception as e:
                        log.warning(f"  Error parseando card: {e}")
            except Exception as e:
                log.warning(f"  Error en {search_url}: {e}")

        await browser.close()

    log.info(f"  TOTAL ZonaProp: {len(results)} avisos")
    return results
