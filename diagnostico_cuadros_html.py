#!/usr/bin/env python3
"""Guarda el HTML real de categorías y cuadros eliminatorios para analizarlos."""

from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from scraper import (
    BASE_URL,
    NAVIGATION_TIMEOUT_MS,
    cargar_config,
    cargar_pagina,
    extraer_destinos_torneo,
    limpiar_texto,
    log,
)
from scraper_runner import esperar_listado_cuadros


DEBUG_DIR = Path(__file__).parent / "debug" / "cuadros"


def extraer_cuadros(html: str) -> list[tuple[str, str]]:
    """Devuelve categoría y URL de cada cuadro eliminatorio sin duplicados."""
    soup = BeautifulSoup(html, "html.parser")
    cuadros: list[tuple[str, str]] = []
    vistos: set[str] = set()

    for bloque in soup.select("#cuadros-todos .cuadros-categoria-block"):
        cabecera = bloque.select_one(".cuadros-categoria-header")
        categoria = limpiar_texto(cabecera.get_text(" ", strip=True)) if cabecera else "Categoría"
        for elemento in bloque.select('[onclick*="torneoCuadro.aspx"], [onclick*="torneocuadro.aspx"]'):
            onclick = elemento.get("onclick", "")
            inicio = onclick.lower().find("torneocuadro.aspx")
            if inicio < 0:
                continue
            fragmento = onclick[inicio:]
            fin = min(
                [pos for pos in (fragmento.find("'"), fragmento.find('"')) if pos >= 0]
                or [len(fragmento)]
            )
            url = urljoin(f"{BASE_URL}/", fragmento[:fin].replace("&amp;", "&"))
            if url not in vistos:
                vistos.add(url)
                cuadros.append((categoria, url))
    return cuadros


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
                log(f"Diagnóstico categoría {indice}/{len(destinos)} guardado")

            cuadros = extraer_cuadros(html_listado)
            for indice, (categoria, url) in enumerate(cuadros, 1):
                html = cargar_pagina(page, url)
                (DEBUG_DIR / f"cuadro_{indice:02d}.html").write_text(html, encoding="utf-8")
                log(f"Diagnóstico cuadro {indice}/{len(cuadros)} guardado: {categoria}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
