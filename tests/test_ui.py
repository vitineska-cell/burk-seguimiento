"""Smoke test del panel web con los resultados generados por el scraper."""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent.parent
HTML_PATH = ROOT / "docs" / "index.html"
JSON_PATH = ROOT / "docs" / "resultados.json"


def main() -> None:
    html = HTML_PATH.read_text(encoding="utf-8").replace(
        "<head>", '<head><base href="https://panel-burk.test/">', 1
    )
    json_text = JSON_PATH.read_text(encoding="utf-8")
    data = json.loads(json_text)
    esperados = len(data.get("jugadores", {}))
    if esperados == 0:
        raise AssertionError("El smoke test necesita al menos un jugador")

    errores: list[str] = []
    with sync_playwright() as p:
        kwargs = {"headless": True}
        executable = os.getenv("PLAYWRIGHT_CHROMIUM_PATH")
        if executable:
            kwargs["executable_path"] = executable
            kwargs["args"] = ["--no-sandbox"]
        browser = p.chromium.launch(**kwargs)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda error: errores.append(str(error)))
        page.route(
            "**/resultados.json*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json_text,
            ),
        )
        page.set_content(html, wait_until="domcontentloaded")
        page.wait_for_selector(".player-tab", timeout=10_000)

        assert page.locator(".player-tab").count() == esperados
        assert page.locator(".player-title").count() == 1
        assert page.locator(".category-card").count() >= 1
        assert page.locator(".category-card[open]").count() == 1

        if esperados > 1:
            segundo_nombre = list(data["jugadores"])[1]
            page.locator(".player-tab").nth(1).click()
            assert page.locator(".player-title").inner_text() == segundo_nombre

        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator(".player-nav").is_visible()
        assert page.locator(".player-panel").is_visible()
        browser.close()

    if errores:
        raise AssertionError(f"Errores JavaScript en el panel: {errores}")
    print(f"Smoke test web correcto: {esperados} jugadores y navegación responsive.")


if __name__ == "__main__":
    main()
