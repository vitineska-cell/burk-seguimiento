#!/usr/bin/env python3
"""Guarda el HTML real de las categorías para estudiar cuadros eliminatorios."""

from pathlib import Path

from playwright.sync_api import sync_playwright

from scraper import (
    BASE_URL,
    NAVIGATION_TIMEOUT_MS,
    cargar_config,
    cargar_pagina,
    extraer_destinos_torneo,
    log,
)
from scraper_runner import esperar_listado_cuadros


DEBUG_DIR = Path(__file__).parent / "debug" / "cuadros"


def main() -> None:
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="es-ES")
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
        try:
            page.goto(
                f"{BASE_URL}/torneo.aspx?id={torneo_id}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            page.locator('[data-tab="panel-cuadros"]').first.click(timeout=15_000)
            html_listado = esperar_listado_cuadros(page)
            (DEBUG_DIR / "listado.html").write_text(html_listado, encoding="utf-8")

            destinos = extraer_destinos_torneo(html_listado, torneo_id)
            for indice, destino in enumerate(destinos, 1):
                url = destino.get("categoria_url")
                if not url:
                    continue
                html = cargar_pagina(page, url)
                (DEBUG_DIR / f"categoria_{indice:02d}.html").write_text(html, encoding="utf-8")
                log(f"Diagnóstico cuadro {indice}/{len(destinos)} guardado")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
