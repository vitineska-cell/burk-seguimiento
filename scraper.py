#!/usr/bin/env python3
"""Seguimiento BÜRK de jugadores en torneos de Pickle Pro Tour.

Versión 4:
- Localiza únicamente controles de grupo visibles y realmente clicables.
- Lee las tablas por sus cabeceras (Jugador/Pareja, Horario/Pista y Resultado),
  sin depender de que el título exacto "GRUPO N - PARTIDOS" esté en un único nodo.
- Admite individuales, dobles y páginas que contienen varias tablas de partidos.
- Normaliza tildes, saltos de línea y elementos HTML intermedios en los nombres.
- Elimina duplicados y genera diagnósticos útiles cuando la web cambia.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

BASE_URL = "https://pickleprotour.com"
ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "jugadores.json"
OUTPUT_PATH = ROOT / "docs" / "resultados.json"
DEBUG_DIR = ROOT / "debug"

BOTON_GRUPO = re.compile(r"^GRUPO\s+\d+\s*$", re.I)
ENCABEZADO_PARTIDOS = re.compile(r"GRUPO\s+\d+\s*-\s*PARTIDOS", re.I)


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
            resultado = valores[idx_resultado]

            partidos.append(
                {
                    "categoria": etiqueta,
                    "pareja1": pareja1,
                    "pareja2": pareja2,
                    "horario_pista": horario,
                    "resultado": resultado,
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
    """Compatibilidad con las pruebas antiguas: devuelve la primera tabla/grupo."""
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


def abrir_vista_grupos(page: Page, torneo_id: int) -> int:
    url = f"{BASE_URL}/torneo.aspx?id={torneo_id}"
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    page.get_by_text("Grupos y Cuadros", exact=True).first.click(timeout=15_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_000)
    return marcar_botones_grupo(page)


def marcar_botones_grupo(page: Page) -> int:
    """Marca controles clicables y visibles, evitando duplicados ocultos desktop/móvil."""
    return int(
        page.evaluate(
            r"""
            () => {
              const patron = /^GRUPO\s+\d+\s*$/i;
              const selectores = 'button, a, input[type="button"], input[type="submit"], [role="button"], [onclick]';
              const candidatos = Array.from(document.querySelectorAll(selectores));
              const visibles = candidatos.filter(el => {
                const texto = (el.innerText || el.value || el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                const estilo = window.getComputedStyle(el);
                return patron.test(texto) && rect.width > 0 && rect.height > 0 &&
                       estilo.display !== 'none' && estilo.visibility !== 'hidden';
              });
              visibles.forEach((el, i) => el.setAttribute('data-burk-group-index', String(i)));
              return visibles.length;
            }
            """
        )
    )


def esperar_tabla_partidos(page: Page) -> None:
    page.wait_for_function(
        r"""
        () => Array.from(document.querySelectorAll('table')).some(tabla => {
          const texto = (tabla.innerText || '').toLowerCase();
          return texto.includes('resultado') && (texto.includes('jugador') || texto.includes('pareja') || texto.includes('equipo'));
        })
        """,
        timeout=15_000,
    )
    page.wait_for_timeout(300)


def volver_a_grupos(page: Page, torneo_id: int) -> int:
    try:
        volver = page.get_by_text(re.compile(r"volver", re.I)).first
        volver.click(timeout=8_000)
        page.wait_for_timeout(500)
        cantidad = marcar_botones_grupo(page)
        if cantidad:
            return cantidad
    except Exception:
        pass
    return abrir_vista_grupos(page, torneo_id)


def resultado_esta_jugado(resultado: str) -> bool:
    valor = normalizar(resultado)
    return valor not in ("", "-", "sin resultado", "pendiente", "por jugar")


def guardar_debug(nombre: str, contenido: str) -> None:
    DEBUG_DIR.mkdir(exist_ok=True)
    (DEBUG_DIR / nombre).write_text(contenido, encoding="utf-8")


def main() -> None:
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores: list[str] = config["jugadores"]
    resultados = {nombre: {"partidos": []} for nombre in jugadores}
    firmas_resultados: set[tuple[str, ...]] = set()

    total_botones = 0
    procesados = 0
    errores = 0
    tablas_detectadas = 0
    filas_detectadas = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="es-ES")

        print(f"Abriendo torneo id={torneo_id}...")
        total_botones = abrir_vista_grupos(page, torneo_id)
        print(f"Detectados {total_botones} controles de grupo visibles y clicables.")
        if total_botones == 0:
            guardar_debug("sin_botones.html", page.content())
            raise RuntimeError("No se encontró ningún control GRUPO N. Se guardó debug/sin_botones.html")

        for i in range(total_botones):
            try:
                cantidad_actual = marcar_botones_grupo(page)
                if i >= cantidad_actual:
                    cantidad_actual = abrir_vista_grupos(page, torneo_id)
                if i >= cantidad_actual:
                    raise RuntimeError(f"El grupo {i + 1} ya no existe; ahora solo hay {cantidad_actual}")

                boton = page.locator(f'[data-burk-group-index="{i}"]')
                texto_boton = limpiar_texto(
                    boton.inner_text(timeout=5_000)
                    or boton.get_attribute("value")
                    or f"GRUPO {i + 1}"
                )
                boton.scroll_into_view_if_needed(timeout=5_000)
                boton.click(timeout=10_000)
                esperar_tabla_partidos(page)

                partidos_vista = extraer_todas_las_tablas_partidos(page.content())
                if partidos_vista:
                    tablas_detectadas += len({p["categoria"] for p in partidos_vista}) or 1
                    filas_detectadas += len(partidos_vista)
                else:
                    guardar_debug(f"grupo_{i + 1:03d}_sin_tabla.html", page.content())
                    raise RuntimeError("La vista no contiene una tabla de partidos reconocible")

                encontrados = 0
                for partido in partidos_vista:
                    for nombre in jugadores:
                        en_p1 = jugador_en_texto(nombre, partido["pareja1"])
                        en_p2 = jugador_en_texto(nombre, partido["pareja2"])
                        if not (en_p1 or en_p2):
                            continue
                        rival = partido["pareja2"] if en_p1 else partido["pareja1"]
                        resultado_txt = limpiar_texto(partido["resultado"])
                        registro = {
                            "categoria": partido["categoria"] or texto_boton,
                            "rival": rival,
                            "horario_pista": partido["horario_pista"],
                            "resultado": resultado_txt,
                            "jugado": resultado_esta_jugado(resultado_txt),
                        }
                        firma = (
                            normalizar(nombre),
                            normalizar(registro["categoria"]),
                            normalizar(rival),
                            normalizar(registro["horario_pista"]),
                            normalizar(resultado_txt),
                        )
                        if firma not in firmas_resultados:
                            firmas_resultados.add(firma)
                            resultados[nombre]["partidos"].append(registro)
                            encontrados += 1

                procesados += 1
                print(
                    f"  [{i + 1}/{total_botones}] {texto_boton}: "
                    f"{len(partidos_vista)} fila(s), {encontrados} coincidencia(s) BÜRK"
                )
                volver_a_grupos(page, torneo_id)

            except Exception as exc:
                errores += 1
                print(f"  ERROR [{i + 1}/{total_botones}]: {type(exc).__name__}: {exc}")
                try:
                    guardar_debug(f"error_grupo_{i + 1:03d}.html", page.content())
                except Exception:
                    pass
                abrir_vista_grupos(page, torneo_id)

        browser.close()

    print(f"\nGrupos procesados: {procesados}/{total_botones}; errores: {errores}")
    print(f"Tablas detectadas: {tablas_detectadas}; filas de partido: {filas_detectadas}")

    if procesados == 0 or filas_detectadas == 0:
        raise RuntimeError(
            "La extracción no produjo ninguna tabla/fila válida; no se sobrescribirá resultados.json"
        )
    if errores and errores >= max(5, total_botones // 3):
        raise RuntimeError(
            f"Demasiados errores ({errores}/{total_botones}); no se sobrescribirá resultados.json"
        )

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
            "controles_grupo": total_botones,
            "grupos_procesados": procesados,
            "errores": errores,
            "filas_partido_leidas": filas_detectadas,
        },
        "jugadores": resultados,
    }

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    total = sum(len(v["partidos"]) for v in resultados.values())
    print(f"Listo: {total} partido(s) encontrados para {len(jugadores)} jugadores BÜRK.")
    print(f"Guardado en {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
