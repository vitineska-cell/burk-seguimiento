#!/usr/bin/env python3
"""Ejecutor BÜRK con fase de grupos, cuadros eliminatorios y logros."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any

from playwright.sync_api import sync_playwright

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
from scraper_runner import esperar_listado_cuadros
from seguimiento import (
    asociar_urls_cuadro,
    calcular_logros,
    extraer_partidos_cuadro,
    fase_orden,
    incorporar_partidos_cuadro,
    resumen_jugador,
)


def _clave_partido(partido: dict[str, Any]) -> tuple[Any, ...]:
    pendiente_primero = 0 if not partido.get("jugado") else 1
    return (
        normalizar(partido.get("categoria_nombre", partido.get("categoria", ""))),
        pendiente_primero,
        fase_orden(partido.get("fase", "")),
        normalizar(partido.get("horario_pista", "")),
    )


def main() -> None:
    inicio = time.monotonic()
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores: list[str] = config["jugadores"]

    resultados: dict[str, dict[str, Any]] = {
        nombre: {"partidos": [], "logros": [], "resumen": {}} for nombre in jugadores
    }
    firmas_resultados: set[tuple[str, ...]] = set()

    categorias_procesadas = 0
    grupos_directos_procesados = 0
    cuadros_procesados = 0
    errores = 0
    filas_grupos = 0
    filas_cuadros = 0

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

            page.locator('[data-tab="panel-cuadros"]').first.click(timeout=15_000)
            log("Esperando la carga dinámica de Grupos y Cuadros...")
            html_listado = esperar_listado_cuadros(page)

            destinos = extraer_destinos_torneo(html_listado, torneo_id)
            destinos = asociar_urls_cuadro(html_listado, destinos)
            if not destinos:
                guardar_debug("sin_destinos.html", html_listado)
                raise RuntimeError("No se localizaron categorías, grupos o cuadros en el torneo")

            total_grupos = len({url for destino in destinos for url in destino["grupo_urls"]})
            total_cuadros = sum(bool(destino.get("cuadro_url")) for destino in destinos)
            log(
                f"Detectadas {len(destinos)} categorías, {total_grupos} grupos únicos "
                f"y {total_cuadros} cuadros."
            )

            for indice, destino in enumerate(destinos, 1):
                if time.monotonic() - inicio > MAX_RUNTIME_SECONDS:
                    raise RuntimeError(
                        "Tiempo máximo interno superado; no se sobrescribirá resultados.json"
                    )

                nombre_categoria = destino["nombre"]
                partidos_categoria: list[dict[str, str]] = []
                url_categoria = destino.get("categoria_url")

                if url_categoria:
                    try:
                        html_categoria = cargar_pagina(page, url_categoria)
                        partidos_categoria = extraer_todas_las_tablas_partidos(html_categoria)
                    except Exception as exc:
                        errores += 1
                        log(
                            f"  ERROR grupos {indice}/{len(destinos)} {nombre_categoria}: "
                            f"{type(exc).__name__}: {exc}"
                        )

                grupos_leidos = contar_grupos_en_partidos(partidos_categoria)
                grupos_esperados = len(destino["grupo_urls"])
                usar_respaldo = not partidos_categoria or (
                    grupos_esperados > 1 and grupos_leidos < grupos_esperados
                )

                if partidos_categoria:
                    filas_grupos += len(partidos_categoria)
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
                        f"{len(partidos_categoria)} partido(s) de grupo, "
                        f"{encontrados} coincidencia(s) BÜRK"
                    )

                if usar_respaldo and destino["grupo_urls"]:
                    for url_grupo in destino["grupo_urls"]:
                        try:
                            html_grupo = cargar_pagina(page, url_grupo)
                            partidos_grupo = extraer_todas_las_tablas_partidos(html_grupo)
                            if not partidos_grupo:
                                raise RuntimeError("Sin tabla de partidos reconocible")
                            filas_grupos += len(partidos_grupo)
                            incorporar_partidos(
                                partidos_grupo,
                                jugadores,
                                resultados,
                                firmas_resultados,
                                url_grupo,
                                nombre_categoria,
                            )
                            grupos_directos_procesados += 1
                        except Exception as exc:
                            errores += 1
                            log(f"    ERROR grupo directo: {type(exc).__name__}: {exc}")

                url_cuadro = destino.get("cuadro_url")
                if url_cuadro:
                    try:
                        html_cuadro = cargar_pagina(page, url_cuadro)
                        partidos_cuadro = extraer_partidos_cuadro(html_cuadro, nombre_categoria)
                        filas_cuadros += len(partidos_cuadro)
                        encontrados_cuadro = incorporar_partidos_cuadro(
                            partidos_cuadro,
                            jugadores,
                            resultados,
                            firmas_resultados,
                            url_cuadro,
                        )
                        cuadros_procesados += 1
                        log(
                            f"    Cuadro: {len(partidos_cuadro)} encuentro(s), "
                            f"{encontrados_cuadro} coincidencia(s) BÜRK"
                        )
                    except Exception as exc:
                        errores += 1
                        log(f"    ERROR cuadro: {type(exc).__name__}: {exc}")
        finally:
            browser.close()

    filas_detectadas = filas_grupos + filas_cuadros
    log(
        f"Resumen: categorías={categorias_procesadas}; grupos directos={grupos_directos_procesados}; "
        f"cuadros={cuadros_procesados}; errores={errores}; filas grupos={filas_grupos}; "
        f"filas cuadros={filas_cuadros}"
    )
    if filas_detectadas == 0:
        raise RuntimeError("La extracción no produjo filas válidas; no se sobrescribirá resultados.json")

    for datos in resultados.values():
        datos["partidos"].sort(key=_clave_partido)
        datos["logros"] = calcular_logros(datos["partidos"])
        datos["resumen"] = resumen_jugador(datos["partidos"])

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
            "cuadros_detectados": total_cuadros,
            "categorias_procesadas": categorias_procesadas,
            "grupos_directos_procesados": grupos_directos_procesados,
            "cuadros_procesados": cuadros_procesados,
            "errores": errores,
            "filas_grupo_leidas": filas_grupos,
            "filas_cuadro_leidas": filas_cuadros,
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
