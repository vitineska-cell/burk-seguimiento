#!/usr/bin/env python3
"""Genera muestras reales para diagnosticar la extracción de nombres."""

from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scraper import (
    BASE_URL,
    NAVIGATION_TIMEOUT_MS,
    cargar_config,
    cargar_pagina,
    extraer_destinos_torneo,
    extraer_todas_las_tablas_partidos,
    normalizar,
)
from scraper_runner import esperar_listado_cuadros

DEBUG_DIR = Path(__file__).parent / "debug"


def main() -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    jugadores = config["jugadores"]
    resumen = []

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
            listado = esperar_listado_cuadros(page)
            destinos = extraer_destinos_torneo(listado, torneo_id)

            for indice, destino in enumerate(destinos, 1):
                url = destino.get("categoria_url")
                if not url:
                    continue

                html = cargar_pagina(page, url)
                texto = normalizar(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
                coincidencias_raw = [
                    jugador for jugador in jugadores if normalizar(jugador) in texto
                ]
                partidos = extraer_todas_las_tablas_partidos(html)

                entrada = {
                    "indice": indice,
                    "categoria": destino.get("nombre"),
                    "url": url,
                    "coincidencias_en_html": coincidencias_raw,
                    "numero_partidos_parseados": len(partidos),
                    "muestra_partidos": partidos[:3],
                }
                resumen.append(entrada)

                if coincidencias_raw:
                    (DEBUG_DIR / f"categoria_con_jugador_{indice:02d}.html").write_text(
                        html, encoding="utf-8"
                    )

            (DEBUG_DIR / "diagnostico_nombres.json").write_text(
                json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        finally:
            browser.close()


if __name__ == "__main__":
    main()
