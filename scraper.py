#!/usr/bin/env python3
"""Seguimiento BÜRK de jugadores en torneos de Pickle Pro Tour.

Versión 5:
- Extrae las URL reales de las categorías y grupos desde el HTML del torneo.
- Navega directamente a esas URL: no simula clics sobre decenas de botones.
- Procesa primero las páginas de categoría y usa los grupos individuales como respaldo.
- Evita duplicados, muestra progreso inmediato y no sobrescribe datos si falla.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
if TYPE_CHECKING:
    from playwright.sync_api import Page

BASE_URL = "https://pickleprotour.com"
ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "jugadores.json"
OUTPUT_PATH = ROOT / "docs" / "resultados.json"
DEBUG_DIR = ROOT / "debug"

ENCABEZADO_PARTIDOS = re.compile(r"GRUPO\s+\d+\s*-\s*PARTIDOS", re.I)
URL_VISOR_RE = re.compile(
    r"abrirCuadroVisor\(\s*['\"]([^'\"]*torneo(?:grupo|cuadro)\.aspx[^'\"]*)['\"]",
    re.I,
)
URL_ORDEN_RE = re.compile(
    r"abrirOJVisor\(\s*['\"]([^'\"]*ordenjuego\.aspx[^'\"]*)['\"]",
    re.I,
)
MAX_RUNTIME_SECONDS = 7 * 60
NAVIGATION_TIMEOUT_MS = 12_000


def log(mensaje: str) -> None:
    print(mensaje, flush=True)


def limpiar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def normalizar(texto: str) -> str:
    """Normaliza tildes, signos y espacios para comparar nombres con seguridad."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return limpiar_texto(texto)


def cargar_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = json.load(f)

    torneo_id_env = os.getenv("TORNEO_ID", "").strip()
    torneo_nombre_env = os.getenv("TORNEO_NOMBRE", "").strip()
    if torneo_id_env:
        config["torneo_id"] = int(torneo_id_env)
    if torneo_nombre_env:
        config["torneo_nombre"] = torneo_nombre_env

    if not config.get("torneo_id"):
        raise ValueError("Falta 'torneo_id' en jugadores.json")
    if not isinstance(config.get("jugadores"), list) or not config["jugadores"]:
        raise ValueError("'jugadores' debe contener al menos un nombre")
    return config


def jugador_en_texto(nombre_jugador: str, texto_pareja: str) -> bool:
    nombre = normalizar(nombre_jugador)
    texto = normalizar(texto_pareja)
    return bool(nombre) and nombre in texto


def _texto_celda(celda: Tag) -> str:
    return limpiar_texto(celda.get_text(" / ", strip=True))


def _cabeceras_y_filas(tabla: Tag) -> tuple[list[str], list[Tag]]:
    filas = tabla.find_all("tr")
    if not filas:
        return [], []

    cabecera_idx = None
    cabeceras: list[str] = []
    for i, fila in enumerate(filas[:3]):
        celdas = fila.find_all(["th", "td"], recursive=False)
        textos = [_texto_celda(c) for c in celdas]
        texto_norm = " ".join(normalizar(t) for t in textos)
        if "resultado" in texto_norm and (
            "jugador" in texto_norm or "pareja" in texto_norm or "equipo" in texto_norm
        ):
            cabecera_idx = i
            cabeceras = textos
            break

    if cabecera_idx is None:
        return [], []
    return cabeceras, filas[cabecera_idx + 1 :]


def _buscar_indice(cabeceras: list[str], palabras: tuple[str, ...]) -> int | None:
    for i, cabecera in enumerate(cabeceras):
        normalizada = normalizar(cabecera)
        if any(p in normalizada for p in palabras):
            return i
    return None


def _indices_participantes(cabeceras: list[str], limite: int) -> list[int]:
    indices = [
        i
        for i, cabecera in enumerate(cabeceras)
        if any(p in normalizar(cabecera) for p in ("jugador", "pareja", "equipo"))
    ]
    if len(indices) >= 2:
        return indices
    return list(range(max(0, limite)))


def _dividir_equipos(valores: list[str]) -> tuple[str, str] | None:
    valores = [v for v in valores if limpiar_texto(v)]
    if len(valores) < 2:
        return None
    if len(valores) == 2:
        return valores[0], valores[1]
    mitad = len(valores) // 2
    if mitad == 0:
        return None
    return " / ".join(valores[:mitad]), " / ".join(valores[mitad:])


def _etiqueta_tabla(tabla: Tag) -> str:
    grupo = ""
    categoria = ""

    for previo in tabla.find_all_previous(
        ["h1", "h2", "h3", "h4", "h5", "h6", "div", "p", "span", "strong"], limit=120
    ):
        texto = limpiar_texto(previo.get_text(" ", strip=True))
        if not texto or len(texto) > 220:
            continue
        if not grupo:
            coincidencia = ENCABEZADO_PARTIDOS.search(texto)
            if coincidencia:
                grupo = limpiar_texto(coincidencia.group(0))
        if not categoria and re.search(r"\bCATEGORIA\b", texto, re.I):
            categoria = texto
        if grupo and categoria:
            break

    partes: list[str] = []
    if grupo:
        partes.append(grupo)
    if categoria and normalizar(categoria) not in normalizar(grupo):
        partes.append(categoria)
    return " · ".join(partes)


def extraer_todas_las_tablas_partidos(html: str) -> list[dict[str, str]]:
    """Devuelve todos los partidos de todas las tablas válidas de la vista."""
    soup = BeautifulSoup(html, "html.parser")
    partidos: list[dict[str, str]] = []

    for tabla in soup.find_all("table"):
        cabeceras, filas = _cabeceras_y_filas(tabla)
        if not cabeceras:
            continue

        idx_resultado = _buscar_indice(cabeceras, ("resultado", "marcador"))
        idx_horario = _buscar_indice(cabeceras, ("horario", "pista", "fecha", "hora"))
        if idx_resultado is None:
            continue

        limite_participantes = min(i for i in (idx_horario, idx_resultado) if i is not None)
        idx_participantes = _indices_participantes(cabeceras, limite_participantes)
        etiqueta = _etiqueta_tabla(tabla)

        for fila in filas:
            celdas = fila.find_all("td", recursive=False)
            if not celdas:
                continue
            valores = [_texto_celda(c) for c in celdas]
            if idx_resultado >= len(valores):
                continue

            participantes = [valores[i] for i in idx_participantes if i < len(valores)]
            equipos = _dividir_equipos(participantes)
            if not equipos:
                continue

            pareja1, pareja2 = equipos
            horario = valores[idx_horario] if idx_horario is not None and idx_horario < len(valores) else ""
            partidos.append(
                {
                    "categoria": etiqueta,
                    "pareja1": pareja1,
                    "pareja2": pareja2,
                    "horario_pista": horario,
                    "resultado": valores[idx_resultado],
                }
            )

    unicos: list[dict[str, str]] = []
    vistos: set[tuple[str, ...]] = set()
    for partido in partidos:
        firma = tuple(
            normalizar(partido[k])
            for k in ("categoria", "pareja1", "pareja2", "horario_pista", "resultado")
        )
        if firma not in vistos:
            vistos.add(firma)
            unicos.append(partido)
    return unicos


def extraer_categoria_y_tabla_partidos(html: str) -> tuple[str, list[dict[str, str]]]:
    """Compatibilidad con las pruebas: devuelve la primera tabla/grupo."""
    partidos = extraer_todas_las_tablas_partidos(html)
    if not partidos:
        return "", []
    categoria = partidos[0]["categoria"]
    salida = [
        {
            "pareja1": p["pareja1"],
            "pareja2": p["pareja2"],
            "horario_pista": p["horario_pista"],
            "resultado": p["resultado"],
        }
        for p in partidos
        if p["categoria"] == categoria
    ]
    return categoria, salida


def _url_desde_onclick(onclick: str) -> str | None:
    coincidencia = URL_VISOR_RE.search(html_lib.unescape(onclick or ""))
    if not coincidencia:
        return None
    return urljoin(f"{BASE_URL}/", coincidencia.group(1))


def _es_url_categoria(url: str, torneo_id: int) -> bool:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return (
        parsed.path.lower().endswith("torneogrupo.aspx")
        and str(torneo_id) in params.get("idT", [])
        and bool(params.get("g"))
    )


def _es_url_grupo(url: str) -> bool:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return (
        parsed.path.lower().endswith("torneogrupo.aspx")
        and bool(params.get("id"))
        and not params.get("idT")
    )


def _es_url_cuadro(url: str) -> bool:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    return parsed.path.lower().endswith("torneocuadro.aspx") and bool(params.get("id"))


def extraer_destinos_torneo(html: str, torneo_id: int) -> list[dict[str, Any]]:
    """Extrae cada categoría con su URL agregada y sus grupos individuales."""
    soup = BeautifulSoup(html, "html.parser")
    bloques = soup.select("#cuadros-todos .cuadros-categoria-block")
    if not bloques:
        bloques = soup.select(".cuadros-categoria-block")

    destinos: list[dict[str, Any]] = []
    vistos: set[str] = set()

    for bloque in bloques:
        cabecera = bloque.select_one(".cuadros-categoria-header")
        nombre = limpiar_texto(cabecera.get_text(" ", strip=True)) if cabecera else "Categoría"
        categoria_url: str | None = None
        grupos: list[str] = []
        cuadros: list[str] = []

        for elemento in bloque.select("[onclick]"):
            url = _url_desde_onclick(elemento.get("onclick", ""))
            if not url:
                continue
            if _es_url_categoria(url, torneo_id) and categoria_url is None:
                categoria_url = url
            elif _es_url_grupo(url) and url not in grupos:
                grupos.append(url)
            elif _es_url_cuadro(url) and url not in cuadros:
                cuadros.append(url)

        clave = categoria_url or "|".join(grupos + cuadros)
        if clave and clave not in vistos:
            vistos.add(clave)
            destinos.append(
                {
                    "nombre": nombre,
                    "categoria_url": categoria_url,
                    "grupo_urls": grupos,
                    "cuadro_urls": cuadros,
                }
            )

    if not destinos:
        categorias: list[str] = []
        grupos: list[str] = []
        cuadros: list[str] = []
        for elemento in soup.select("[onclick]"):
            url = _url_desde_onclick(elemento.get("onclick", ""))
            if not url:
                continue
            if _es_url_categoria(url, torneo_id) and url not in categorias:
                categorias.append(url)
            elif _es_url_grupo(url) and url not in grupos:
                grupos.append(url)
            elif _es_url_cuadro(url) and url not in cuadros:
                cuadros.append(url)
        destinos.extend(
            {
                "nombre": f"Categoría {i}",
                "categoria_url": url,
                "grupo_urls": [],
                "cuadro_urls": [],
            }
            for i, url in enumerate(categorias, 1)
        )
        if not categorias and grupos:
            destinos.append(
                {
                    "nombre": "Grupos",
                    "categoria_url": None,
                    "grupo_urls": grupos,
                    "cuadro_urls": cuadros,
                }
            )

    return destinos


def extraer_partidos_cuadro(
    html: str, categoria_respaldo: str = "Categoría"
) -> list[dict[str, Any]]:
    """Extrae todos los cruces de la vista ``torneoCuadro.aspx``.

    La web representa el cuadro con divs, no con las tablas usadas en grupos.
    La clase ``winner`` es la fuente más fiable para decidir el ganador cuando
    hay varios sets o un WO.
    """
    soup = BeautifulSoup(html, "html.parser")
    cabecera = soup.select_one(".tournament-header")
    categoria = limpiar_texto(cabecera.get_text(" ", strip=True)) if cabecera else categoria_respaldo
    categoria = re.sub(r"^CATEGORIA\s+", "", categoria, flags=re.I)
    categoria = categoria or categoria_respaldo
    partidos: list[dict[str, Any]] = []

    for ronda in soup.select(".tournament-round"):
        encabezado = ronda.select_one(".round-header")
        fase = limpiar_texto(encabezado.get_text(" ", strip=True)) if encabezado else ""
        for partido in ronda.select(".match"):
            equipos = partido.select(":scope > .match-team")
            if len(equipos) < 2:
                continue
            nombres = []
            for equipo in equipos[:2]:
                nombre_el = equipo.select_one(".team-name")
                nombres.append(
                    limpiar_texto(nombre_el.get_text(" / ", strip=True)) if nombre_el else ""
                )
            if not all(nombres):
                continue
            resultado_el = partido.select_one(":scope > .match-result")
            resultado = limpiar_texto(resultado_el.get_text(" ", strip=True)) if resultado_el else ""
            ganador = None
            if "winner" in (equipos[0].get("class") or []):
                ganador = 1
            elif "winner" in (equipos[1].get("class") or []):
                ganador = 2
            partidos.append(
                {
                    "categoria": f"{fase} · CATEGORIA {categoria}",
                    "pareja1": nombres[0],
                    "pareja2": nombres[1],
                    "horario_pista": "",
                    "resultado": resultado,
                    "ganador": ganador,
                }
            )
    return partidos


def extraer_urls_orden_juego(html: str, torneo_id: int) -> list[str]:
    """Devuelve las páginas diarias publicadas en Orden de juego."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for elemento in soup.select("[onclick]"):
        coincidencia = URL_ORDEN_RE.search(html_lib.unescape(elemento.get("onclick", "")))
        if not coincidencia:
            continue
        url = urljoin(f"{BASE_URL}/", coincidencia.group(1))
        params = parse_qs(urlparse(url).query)
        if str(torneo_id) not in params.get("id_torneo", []) or not params.get("f"):
            continue
        if url not in urls:
            urls.append(url)
    return urls


def _fecha_orden_juego(soup: BeautifulSoup, respaldo: str) -> str:
    dia = soup.select_one(".oj-dayval")
    texto = limpiar_texto(dia.get_text(" ", strip=True)) if dia else ""
    coincidencia = re.search(r"(\d{4})[./-](\d{2})[./-](\d{2})", texto)
    if coincidencia:
        return f"{coincidencia.group(3)}/{coincidencia.group(2)}/{coincidencia.group(1)}"
    coincidencia = re.search(r"(\d{2})[./-](\d{2})[./-](\d{4})", respaldo)
    return coincidencia.group(0).replace("-", "/") if coincidencia else respaldo


def extraer_partidos_orden_juego(
    html: str, fecha_respaldo: str = ""
) -> list[dict[str, Any]]:
    """Extrae partidos, ronda, pista y estado de la programación diaria."""
    soup = BeautifulSoup(html, "html.parser")
    fecha = _fecha_orden_juego(soup, fecha_respaldo)
    partidos: list[dict[str, Any]] = []

    for pista in soup.select(".oj-court"):
        pista_el = pista.select_one(".oj-court-nm")
        numero_pista = limpiar_texto(pista_el.get_text(" ", strip=True)) if pista_el else ""
        for partido in pista.select(":scope > .oj-match"):
            categorias = [
                limpiar_texto(el.get_text(" ", strip=True))
                for el in partido.select(".oj-chip-cat")
            ]
            categoria = next((c for c in categorias if normalizar(c) != "cuadro"), "Categoría")
            fase_el = partido.select_one(".oj-chip-r")
            fase = limpiar_texto(fase_el.get_text(" ", strip=True)) if fase_el else "Grupos"
            filas = partido.select(".oj-score-row")
            if len(filas) < 2:
                continue
            nombres: list[str] = []
            sets: list[list[str]] = []
            for fila in filas[:2]:
                nombres_el = fila.select_one(".oj-player-names")
                nombres.append(
                    limpiar_texto(nombres_el.get_text(" ", strip=True)) if nombres_el else ""
                )
                sets.append(
                    [limpiar_texto(el.get_text(" ", strip=True)) for el in fila.select(".oj-set")]
                )
            if not all(nombres):
                continue

            parciales: list[str] = []
            for izquierda, derecha in zip(sets[0], sets[1]):
                if izquierda.isdigit() and derecha.isdigit():
                    parciales.append(f"{izquierda}-{derecha}")
            resultado = " / ".join(parciales)
            estado_el = partido.select_one(".oj-status")
            estado = limpiar_texto(estado_el.get_text(" ", strip=True)) if estado_el else ""
            estado_normalizado = normalizar(estado)
            if not resultado and re.search(r"\bp\s*1\b.*\bwo\b", estado_normalizado):
                resultado = estado
                ganador = 2
            elif not resultado and re.search(r"\bp\s*2\b.*\bwo\b", estado_normalizado):
                resultado = estado
                ganador = 1
            else:
                ganador = None
            hora = re.search(r"\b([0-2]?\d:[0-5]\d)\b", estado)
            momento = f"{fecha} {hora.group(1)}" if hora else fecha
            if not hora and normalizar(estado) == "a continuacion":
                momento = f"{fecha} · A continuación"
            horario = momento
            if numero_pista:
                horario = f"{momento} / Pista: {numero_pista}"

            ganados = [
                sum("winner" in (el.get("class") or []) for el in fila.select(".oj-set"))
                for fila in filas[:2]
            ]
            if ganador is None and ganados[0] > ganados[1]:
                ganador = 1
            elif ganador is None and ganados[1] > ganados[0]:
                ganador = 2

            partidos.append(
                {
                    "categoria": f"{fase} · CATEGORIA {categoria}",
                    "pareja1": nombres[0],
                    "pareja2": nombres[1],
                    "horario_pista": horario,
                    "resultado": resultado,
                    "ganador": ganador,
                    "estado_programacion": estado,
                }
            )
    return partidos


def resultado_esta_jugado(resultado: str) -> bool:
    valor = normalizar(resultado)
    return valor not in ("", "-", "sin resultado", "pendiente", "por jugar")


def guardar_debug(nombre: str, contenido: str) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    (DEBUG_DIR / nombre).write_text(contenido, encoding="utf-8")


def cargar_pagina(page: "Page", url: str) -> str:
    page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    page.wait_for_timeout(350)
    return page.content()


def contar_grupos_en_partidos(partidos: list[dict[str, str]]) -> int:
    grupos = set()
    for partido in partidos:
        coincidencia = re.search(r"GRUPO\s+\d+", partido.get("categoria", ""), re.I)
        if coincidencia:
            grupos.add(normalizar(coincidencia.group(0)))
    return len(grupos)


def incorporar_partidos(
    partidos: list[dict[str, str]],
    jugadores: list[str],
    resultados: dict[str, dict[str, list[dict[str, Any]]]],
    firmas_resultados: set[tuple[str, ...]],
    url_origen: str,
    categoria_respaldo: str,
) -> int:
    encontrados = 0
    for partido in partidos:
        for nombre in jugadores:
            en_p1 = jugador_en_texto(nombre, partido["pareja1"])
            en_p2 = jugador_en_texto(nombre, partido["pareja2"])
            if not (en_p1 or en_p2):
                continue

            rival = partido["pareja2"] if en_p1 else partido["pareja1"]
            resultado_txt = limpiar_texto(partido["resultado"])
            registro = {
                "categoria": partido["categoria"] or categoria_respaldo,
                "rival": rival,
                "horario_pista": partido["horario_pista"],
                "resultado": resultado_txt,
                "jugado": resultado_esta_jugado(resultado_txt),
                "url_grupo": url_origen,
            }
            firma = (
                normalizar(nombre),
                normalizar(rival),
                normalizar(registro["horario_pista"]),
                normalizar(resultado_txt),
            )
            if firma not in firmas_resultados:
                firmas_resultados.add(firma)
                resultados[nombre]["partidos"].append(registro)
                encontrados += 1
    return encontrados


def main() -> None:
    from playwright.sync_api import sync_playwright

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

        log(f"Torneo seleccionado: {torneo_nombre or torneo_id} (id={torneo_id})")
        url_torneo = f"{BASE_URL}/torneo.aspx?id={torneo_id}"
        page.goto(url_torneo, wait_until="domcontentloaded", timeout=30_000)
        titulo_web = limpiar_texto(page.title().split("|")[0])
        if titulo_web:
            torneo_nombre = titulo_web
            log(f"Nombre confirmado por la web: {torneo_nombre}")
        page.get_by_text("Grupos y Cuadros", exact=True).first.click(timeout=15_000)
        page.wait_for_timeout(700)

        html_listado = page.content()
        destinos = extraer_destinos_torneo(html_listado, torneo_id)
        if not destinos:
            guardar_debug("sin_destinos.html", html_listado)
            browser.close()
            raise RuntimeError("No se localizaron URL de categorías o grupos en el torneo")

        total_grupos = len({url for d in destinos for url in d["grupo_urls"]})
        log(f"Detectadas {len(destinos)} categorías y {total_grupos} grupos únicos.")

        for indice, destino in enumerate(destinos, 1):
            if time.monotonic() - inicio > MAX_RUNTIME_SECONDS:
                browser.close()
                raise RuntimeError("Tiempo máximo interno superado; no se sobrescribirá resultados.json")

            nombre_categoria = destino["nombre"]
            partidos_categoria: list[dict[str, str]] = []
            url_categoria = destino["categoria_url"]

            if url_categoria:
                try:
                    html_categoria = cargar_pagina(page, url_categoria)
                    partidos_categoria = extraer_todas_las_tablas_partidos(html_categoria)
                except Exception as exc:
                    errores += 1
                    log(f"  ERROR categoría {indice}/{len(destinos)} {nombre_categoria}: {type(exc).__name__}")
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
                    f"{len(partidos_categoria)} partido(s), {encontrados} coincidencia(s) BÜRK"
                )

            if usar_respaldo and destino["grupo_urls"]:
                log(
                    f"    Respaldo: leyendo {len(destino['grupo_urls'])} grupo(s) directos "
                    f"de {nombre_categoria}"
                )
                for num_grupo, url_grupo in enumerate(destino["grupo_urls"], 1):
                    if time.monotonic() - inicio > MAX_RUNTIME_SECONDS:
                        browser.close()
                        raise RuntimeError("Tiempo máximo interno superado; no se sobrescribirá resultados.json")
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
                        log(f"      grupo {num_grupo}/{len(destino['grupo_urls'])}: OK")
                    except Exception as exc:
                        errores += 1
                        log(
                            f"      ERROR grupo {num_grupo}/{len(destino['grupo_urls'])}: "
                            f"{type(exc).__name__}: {exc}"
                        )

        browser.close()

    log(
        f"Resumen: categorías procesadas={categorias_procesadas}; "
        f"grupos directos procesados={paginas_grupo_procesadas}; errores={errores}; "
        f"filas leídas={filas_detectadas}"
    )

    if filas_detectadas == 0:
        raise RuntimeError("La extracción no produjo ninguna fila válida; no se sobrescribirá resultados.json")

    for datos in resultados.values():
        datos["partidos"].sort(
            key=lambda partido: (
                partido["jugado"],
                normalizar(partido.get("horario_pista", "")),
                normalizar(partido.get("categoria", "")),
            )
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
    total = sum(len(v["partidos"]) for v in resultados.values())
    if total == 0:
        raise RuntimeError(
            "Se leyeron partidos, pero ninguno coincide con los jugadores BÜRK; "
            "no se sobrescribirá resultados.json"
        )

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    log(f"Listo: {total} partido(s) encontrados para {len(jugadores)} jugadores BÜRK.")
    log(f"Guardado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
