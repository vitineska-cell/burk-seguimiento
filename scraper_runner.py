#!/usr/bin/env python3
"""Ejecutor robusto del scraper BÜRK.

La web de Pickle Pro Tour carga "Grupos y Cuadros" de forma asíncrona.
Este ejecutor espera a que las categorías y sus URL reales estén presentes
antes de iniciar la extracción, evitando leer el placeholder "Cargando...".
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

from scraper import (
    BASE_URL,
    MAX_RUNTIME_SECONDS,
    NAVIGATION_TIMEOUT_MS,
    OUTPUT_PATH,
    cargar_config,
    cargar_pagina,
    contar_grupos_en_partidos,
    extraer_destinos_torneo,
    extraer_todas_las_tablas_partidos,
    guardar_debug,
    incorporar_partidos,
    limpiar_texto,
    log,
    normalizar,
)

LISTADO_TIMEOUT_MS = 25_000


def listado_cuadros_cargado(html: str) -> bool:
    """Indica si el contenido asíncrono ya contiene categorías y URL navegables."""
    soup = BeautifulSoup(html, "html.parser")
    contenedor = soup.select_one('.tab-lazy-content[data-panel="cuadros"]')
    if contenedor is None:
        return False

    if not contenedor.select_one(".cuadros-categoria-block"):
        return False

    for elemento in contenedor.select("[onclick]"):
        onclick = (elemento.get("onclick") or "").lower()
        if "torneogrupo.aspx" in onclick:
            return True
    return False


def esperar_listado_cuadros(page: Page, timeout_ms: int = LISTADO_TIMEOUT_MS) -> str:
    """Espera activamente hasta que desaparece el placeholder y llegan las URL."""
    limite = time.monotonic() + timeout_ms / 1000
    ultimo_html = ""

    while time.monotonic() < limite:
        ultimo_html = page.content()
        if listado_cuadros_cargado(ultimo_html):
            return ultimo_html
        page.wait_for_timeout(250)

    guardar_debug("listado_cuadros_no_cargado.html", ultimo_html or page.content())
    raise RuntimeError(
        "La sección Grupos y Cuadros no terminó de cargar dentro del tiempo esperado"
    )


def main() -> None:
    inicio = time.monotonic()
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores: list[str] = config["jugadores"]

    resultados: dict[str, dict[str, list[dict[str, Any]]]] = {
        nombre: {"partidos": []} for nombre in jugadores
    }
    firmas_resultados: set[tuple[str, ...]] = set()

    categorias_procesadas = 0
    paginas_grupo_procesadas = 0
    errores = 0
    filas_detectadas = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="es-ES")
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)

        try:
            log(f"Torneo seleccionado: {torneo_nombre or torneo_id} (id={torneo_id})")
            url_torneo = f"{BASE_URL}/torneo.aspx?id={torneo_id}"
            page.goto(url_torneo, wait_until="domcontentloaded", timeout=30_000)

            titulo_web = limpiar_texto(page.title().split("|")[0])
            if titulo_web:
                torneo_nombre = titulo_web
                log(f"Nombre confirmado por la web: {torneo_nombre}")

            pestaña = page.locator('[data-tab="panel-cuadros"]').first
            pestaña.click(timeout=15_000)
            log("Esperando la carga dinámica de Grupos y Cuadros...")
            html_listado = esperar_listado_cuadros(page)

            destinos = extraer_destinos_torneo(html_listado, torneo_id)
            if not destinos:
                guardar_debug("sin_destinos.html", html_listado)
                raise RuntimeError("No se localizaron URL de categorías o grupos en el torneo")

            total_grupos = len({url for destino in destinos for url in destino["grupo_urls"]})
            log(f"Detectadas {len(destinos)} categorías y {total_grupos} grupos únicos.")

            for indice, destino in enumerate(destinos, 1):
                if time.monotonic() - inicio > MAX_RUNTIME_SECONDS:
                    raise RuntimeError(
                        "Tiempo máximo interno superado; no se sobrescribirá resultados.json"
                    )

                nombre_categoria = destino["nombre"]
                partidos_categoria: list[dict[str, str]] = []
                url_categoria = destino["categoria_url"]

                if url_categoria:
                    try:
                        html_categoria = cargar_pagina(page, url_categoria)
                        partidos_categoria = extraer_todas_las_tablas_partidos(html_categoria)
                    except Exception as exc:
                        errores += 1
                        log(
                            f"  ERROR categoría {indice}/{len(destinos)} "
                            f"{nombre_categoria}: {type(exc).__name__}: {exc}"
                        )
                        try:
                            guardar_debug(f"error_categoria_{indice:02d}.html", page.content())
                        except Exception:
                            pass

                grupos_leidos = contar_grupos_en_partidos(partidos_categoria)
                grupos_esperados = len(destino["grupo_urls"])
                usar_respaldo = not partidos_categoria or (
                    grupos_esperados > 1 and grupos_leidos < grupos_esperados
                )

                if partidos_categoria:
                    filas_detectadas += len(partidos_categoria)
                    encontrados = incorporar_partidos(
                        partidos_categoria,
                        jugadores,
                        resultados,
                        firmas_resultados,
                        url_categoria or url_torneo,
                        nombre_categoria,
                    )
                    categorias_procesadas += 1
                    log(
                        f"  [{indice}/{len(destinos)}] {nombre_categoria}: "
                        f"{len(partidos_categoria)} partido(s), "
                        f"{encontrados} coincidencia(s) BÜRK"
                    )

                if usar_respaldo and destino["grupo_urls"]:
                    log(
                        f"    Respaldo: leyendo {len(destino['grupo_urls'])} grupo(s) "
                        f"directos de {nombre_categoria}"
                    )
                    for num_grupo, url_grupo in enumerate(destino["grupo_urls"], 1):
                        if time.monotonic() - inicio > MAX_RUNTIME_SECONDS:
                            raise RuntimeError(
                                "Tiempo máximo interno superado; no se sobrescribirá resultados.json"
                            )
                        try:
                            html_grupo = cargar_pagina(page, url_grupo)
                            partidos_grupo = extraer_todas_las_tablas_partidos(html_grupo)
                            if not partidos_grupo:
                                raise RuntimeError("Sin tabla de partidos reconocible")

                            filas_detectadas += len(partidos_grupo)
                            incorporar_partidos(
                                partidos_grupo,
                                jugadores,
                                resultados,
                                firmas_resultados,
                                url_grupo,
                                nombre_categoria,
                            )
                            paginas_grupo_procesadas += 1
                            log(
                                f"      grupo {num_grupo}/{len(destino['grupo_urls'])}: OK"
                            )
                        except Exception as exc:
                            errores += 1
                            log(
                                f"      ERROR grupo {num_grupo}/{len(destino['grupo_urls'])}: "
                                f"{type(exc).__name__}: {exc}"
                            )

        finally:
            browser.close()

    log(
        f"Resumen: categorías procesadas={categorias_procesadas}; "
        f"grupos directos procesados={paginas_grupo_procesadas}; errores={errores}; "
        f"filas leídas={filas_detectadas}"
    )

    if filas_detectadas == 0:
        raise RuntimeError(
            "La extracción no produjo ninguna fila válida; no se sobrescribirá resultados.json"
        )

    for datos in resultados.values():
        datos["partidos"].sort(
            key=lambda partido: (
                partido["jugado"],
                normalizar(partido.get("horario_pista", "")),
                normalizar(partido.get("categoria", "")),
            )
        )

    total = sum(len(datos["partidos"]) for datos in resultados.values())
    if total == 0:
        raise RuntimeError(
            "Se leyeron partidos, pero ninguno coincide con los jugadores BÜRK; "
            "no se sobrescribirá resultados.json"
        )

    salida = {
        "torneo_id": torneo_id,
        "torneo_nombre": torneo_nombre,
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "diagnostico": {
            "categorias_detectadas": len(destinos),
            "grupos_unicos_detectados": total_grupos,
            "categorias_procesadas": categorias_procesadas,
            "grupos_directos_procesados": paginas_grupo_procesadas,
            "errores": errores,
            "filas_partido_leidas": filas_detectadas,
        },
        "jugadores": resultados,
    }

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as archivo:
        json.dump(salida, archivo, ensure_ascii=False, indent=2)

    log(f"Listo: {total} partido(s) encontrados para {len(jugadores)} jugadores BÜRK.")
    log(f"Guardado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
