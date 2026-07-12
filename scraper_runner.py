#!/usr/bin/env python3
"""Ejecutor robusto del scraper BÜRK con resultados y logros por fase."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright

from scraper import (
    BASE_URL, MAX_RUNTIME_SECONDS, NAVIGATION_TIMEOUT_MS, OUTPUT_PATH,
    cargar_config, cargar_pagina, contar_grupos_en_partidos,
    extraer_destinos_torneo, extraer_todas_las_tablas_partidos,
    guardar_debug, jugador_en_texto, limpiar_texto, log, normalizar,
    resultado_esta_jugado,
)

LISTADO_TIMEOUT_MS = 25_000
FASES = {
    "grupos": 0, "dieciseisavos": 1, "octavos": 2,
    "cuartos": 3, "semifinal": 4, "final": 5,
}


def listado_cuadros_cargado(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    contenedor = soup.select_one('.tab-lazy-content[data-panel="cuadros"]')
    if contenedor is None or not contenedor.select_one(".cuadros-categoria-block"):
        return False
    return any("torneogrupo.aspx" in ((e.get("onclick") or "").lower())
               for e in contenedor.select("[onclick]"))


def esperar_listado_cuadros(page: Page, timeout_ms: int = LISTADO_TIMEOUT_MS) -> str:
    limite = time.monotonic() + timeout_ms / 1000
    ultimo_html = ""
    while time.monotonic() < limite:
        ultimo_html = page.content()
        if listado_cuadros_cargado(ultimo_html):
            return ultimo_html
        page.wait_for_timeout(250)
    guardar_debug("listado_cuadros_no_cargado.html", ultimo_html or page.content())
    raise RuntimeError("La sección Grupos y Cuadros no terminó de cargar")


def detectar_fase(texto: str) -> str:
    valor = normalizar(texto)
    if "final" in valor and "semifinal" not in valor:
        return "final"
    if "semifinal" in valor or "semi final" in valor:
        return "semifinal"
    if "cuartos" in valor or "1 4" in valor:
        return "cuartos"
    if "octavos" in valor or "1 8" in valor:
        return "octavos"
    if "dieciseisavos" in valor or "1 16" in valor:
        return "dieciseisavos"
    return "grupos"


def categoria_limpia(texto: str, respaldo: str) -> str:
    base = texto or respaldo
    base = re.sub(r"GRUPO\s+\d+\s*-\s*PARTIDOS\s*[·-]?\s*", "", base, flags=re.I)
    base = re.sub(r"\bCATEGORIA\b\s*", "", base, flags=re.I)
    return limpiar_texto(base).strip(" ·-") or respaldo


def _marcador(resultado: str) -> tuple[int, int] | None:
    numeros = re.findall(r"\d+", resultado or "")
    if len(numeros) < 2:
        return None
    return int(numeros[0]), int(numeros[1])


def incorporar_partidos_enriquecidos(
    partidos: list[dict[str, str]], jugadores: list[str],
    resultados: dict[str, dict[str, Any]], firmas: set[tuple[str, ...]],
    url_origen: str, categoria_respaldo: str,
) -> int:
    encontrados = 0
    for partido in partidos:
        for nombre in jugadores:
            en_p1 = jugador_en_texto(nombre, partido["pareja1"])
            en_p2 = jugador_en_texto(nombre, partido["pareja2"])
            if not (en_p1 or en_p2):
                continue
            rival = partido["pareja2"] if en_p1 else partido["pareja1"]
            resultado = limpiar_texto(partido["resultado"])
            jugado = resultado_esta_jugado(resultado)
            puntos = _marcador(resultado) if jugado else None
            ganado = None
            if puntos:
                propios, ajenos = puntos if en_p1 else (puntos[1], puntos[0])
                ganado = propios > ajenos
            categoria_raw = partido.get("categoria", "") or categoria_respaldo
            registro = {
                "categoria": categoria_limpia(categoria_raw, categoria_respaldo),
                "fase": detectar_fase(categoria_raw),
                "rival": rival,
                "horario_pista": partido.get("horario_pista", ""),
                "resultado": resultado,
                "jugado": jugado,
                "ganado": ganado,
                "url_grupo": url_origen,
            }
            firma = tuple(normalizar(str(registro[k])) for k in
                          ("categoria", "fase", "rival", "horario_pista", "resultado"))
            clave = (normalizar(nombre),) + firma
            if clave not in firmas:
                firmas.add(clave)
                resultados[nombre]["partidos"].append(registro)
                encontrados += 1
    return encontrados


def calcular_logros(partidos: list[dict[str, Any]]) -> list[dict[str, str]]:
    por_categoria: dict[str, list[dict[str, Any]]] = {}
    for partido in partidos:
        por_categoria.setdefault(partido.get("categoria") or "Categoría", []).append(partido)
    logros = []
    for categoria, items in por_categoria.items():
        eliminatorias = [p for p in items if FASES.get(p.get("fase", "grupos"), 0) > 0 and p.get("jugado")]
        if not eliminatorias:
            continue
        ultimo = max(eliminatorias, key=lambda p: FASES.get(p.get("fase", "grupos"), 0))
        fase = ultimo.get("fase", "grupos")
        ganado = ultimo.get("ganado")
        if fase == "final":
            texto = "Campeón" if ganado else "Finalista"
        elif fase == "semifinal":
            texto = "Finalista" if ganado else "Semifinalista"
        elif fase == "cuartos":
            texto = "Semifinalista" if ganado else "Cuartofinalista"
        elif fase == "octavos":
            texto = "Cuartofinalista" if ganado else "Octavofinalista"
        else:
            texto = "Fase eliminatoria"
        logros.append({"titulo": texto, "categoria": categoria})
    return sorted(logros, key=lambda x: (x["titulo"] != "Campeón", x["categoria"]))


def main() -> None:
    inicio = time.monotonic()
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores: list[str] = config["jugadores"]
    resultados: dict[str, dict[str, Any]] = {n: {"partidos": [], "logros": []} for n in jugadores}
    firmas: set[tuple[str, ...]] = set()
    categorias_procesadas = paginas_grupo_procesadas = errores = filas_detectadas = 0

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
            page.locator('[data-tab="panel-cuadros"]').first.click(timeout=15_000)
            html_listado = esperar_listado_cuadros(page)
            destinos = extraer_destinos_torneo(html_listado, torneo_id)
            if not destinos:
                raise RuntimeError("No se localizaron URL de categorías o grupos")
            total_grupos = len({u for d in destinos for u in d["grupo_urls"]})
            log(f"Detectadas {len(destinos)} categorías y {total_grupos} grupos únicos.")

            for indice, destino in enumerate(destinos, 1):
                if time.monotonic() - inicio > MAX_RUNTIME_SECONDS:
                    raise RuntimeError("Tiempo máximo interno superado")
                nombre_categoria = destino["nombre"]
                partidos_categoria: list[dict[str, str]] = []
                url_categoria = destino["categoria_url"]
                if url_categoria:
                    try:
                        partidos_categoria = extraer_todas_las_tablas_partidos(cargar_pagina(page, url_categoria))
                    except Exception as exc:
                        errores += 1
                        log(f"ERROR categoría {indice}: {type(exc).__name__}: {exc}")
                grupos_leidos = contar_grupos_en_partidos(partidos_categoria)
                usar_respaldo = not partidos_categoria or (
                    len(destino["grupo_urls"]) > 1 and grupos_leidos < len(destino["grupo_urls"])
                )
                if partidos_categoria:
                    filas_detectadas += len(partidos_categoria)
                    encontrados = incorporar_partidos_enriquecidos(
                        partidos_categoria, jugadores, resultados, firmas,
                        url_categoria or url_torneo, nombre_categoria)
                    categorias_procesadas += 1
                    log(f"[{indice}/{len(destinos)}] {nombre_categoria}: {len(partidos_categoria)} partidos, {encontrados} BÜRK")
                if usar_respaldo:
                    for url_grupo in destino["grupo_urls"]:
                        try:
                            partidos_grupo = extraer_todas_las_tablas_partidos(cargar_pagina(page, url_grupo))
                            if not partidos_grupo:
                                continue
                            filas_detectadas += len(partidos_grupo)
                            incorporar_partidos_enriquecidos(
                                partidos_grupo, jugadores, resultados, firmas,
                                url_grupo, nombre_categoria)
                            paginas_grupo_procesadas += 1
                        except Exception as exc:
                            errores += 1
                            log(f"ERROR grupo: {type(exc).__name__}: {exc}")
        finally:
            browser.close()

    if filas_detectadas == 0:
        raise RuntimeError("La extracción no produjo filas válidas")
    for datos in resultados.values():
        datos["partidos"].sort(key=lambda x: (not x["jugado"], x.get("horario_pista", "")))
        datos["logros"] = calcular_logros(datos["partidos"])
        jugados = [p for p in datos["partidos"] if p["jugado"]]
        datos["resumen"] = {
            "jugados": len(jugados),
            "victorias": sum(p.get("ganado") is True for p in jugados),
            "derrotas": sum(p.get("ganado") is False for p in jugados),
            "proximos": sum(not p["jugado"] for p in datos["partidos"]),
        }
    total = sum(len(v["partidos"]) for v in resultados.values())
    if total == 0:
        raise RuntimeError("No hubo coincidencias con jugadores BÜRK")
    salida = {
        "torneo_id": torneo_id, "torneo_nombre": torneo_nombre,
        "actualizado": datetime.now(timezone.utc).isoformat(),
        "diagnostico": {"categorias_detectadas": len(destinos), "grupos_unicos_detectados": total_grupos,
                        "categorias_procesadas": categorias_procesadas,
                        "grupos_directos_procesados": paginas_grupo_procesadas,
                        "errores": errores, "filas_partido_leidas": filas_detectadas},
        "jugadores": resultados,
    }
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Listo: {total} partidos para {len(jugadores)} jugadores BÜRK.")


if __name__ == "__main__":
    main()
