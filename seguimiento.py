"""Extracción de cuadros, resultados orientados y logros de jugadores BÜRK."""

from __future__ import annotations

import html as html_lib
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import scraper


CUADRO_URL_RE = re.compile(
    r"abrirCuadroVisor\(\s*['\"]([^'\"]*torneocuadro\.aspx[^'\"]*)['\"]",
    re.I,
)
FASE_ORDEN = {
    "fase de grupos": 0,
    "treintaidosavos": 1,
    "dieciseisavos": 2,
    "octavos de final": 3,
    "cuartos de final": 4,
    "semifinales": 5,
    "final": 6,
}


def _texto(tag: Any) -> str:
    return scraper.limpiar_texto(tag.get_text(" ", strip=True)) if tag else ""


def _url_cuadro(onclick: str) -> str | None:
    coincidencia = CUADRO_URL_RE.search(html_lib.unescape(onclick or ""))
    if not coincidencia:
        return None
    return urljoin(f"{scraper.BASE_URL}/", coincidencia.group(1))


def asociar_urls_cuadro(html: str, destinos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Añade la URL del cuadro eliminatorio a cada categoría detectada."""
    soup = BeautifulSoup(html, "html.parser")
    por_nombre: dict[str, str] = {}
    por_orden: list[str | None] = []

    bloques = soup.select("#cuadros-todos .cuadros-categoria-block")
    if not bloques:
        bloques = soup.select(".cuadros-categoria-block")

    for bloque in bloques:
        nombre = _texto(bloque.select_one(".cuadros-categoria-header"))
        url = None
        for elemento in bloque.select("[onclick]"):
            url = _url_cuadro(elemento.get("onclick", ""))
            if url:
                break
        por_orden.append(url)
        if nombre and url:
            por_nombre[scraper.normalizar(nombre)] = url

    salida: list[dict[str, Any]] = []
    for indice, destino in enumerate(destinos):
        copia = dict(destino)
        copia["cuadro_url"] = por_nombre.get(scraper.normalizar(destino.get("nombre", "")))
        if not copia["cuadro_url"] and indice < len(por_orden):
            copia["cuadro_url"] = por_orden[indice]
        salida.append(copia)
    return salida


def normalizar_fase(texto: str) -> str:
    fase = scraper.normalizar(texto)
    if "final" == fase:
        return "Final"
    if "semi" in fase:
        return "Semifinales"
    if "cuarto" in fase:
        return "Cuartos de final"
    if "octavo" in fase:
        return "Octavos de final"
    if "dieciseis" in fase:
        return "Dieciseisavos"
    if "treinta" in fase:
        return "Treintaidosavos"
    return scraper.limpiar_texto(texto) or "Cuadro"


def fase_orden(fase: str) -> int:
    return FASE_ORDEN.get(scraper.normalizar(fase), 0)


def resultado_jugado(resultado: str) -> bool:
    pares = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*-\s*(\d+)", resultado or "")]
    return bool(pares) and any(a != 0 or b != 0 for a, b in pares)


def ganador_por_resultado(resultado: str) -> int | None:
    """Devuelve 1 o 2 según el lado ganador; None si no hay resultado fiable."""
    pares = [(int(a), int(b)) for a, b in re.findall(r"(\d+)\s*-\s*(\d+)", resultado or "")]
    pares = [(a, b) for a, b in pares if a != b]
    if not pares:
        return None
    ganados_1 = sum(a > b for a, b in pares)
    ganados_2 = sum(b > a for a, b in pares)
    if ganados_1 == ganados_2:
        return 1 if pares[-1][0] > pares[-1][1] else 2
    return 1 if ganados_1 > ganados_2 else 2


def extraer_partidos_cuadro(html: str, categoria: str) -> list[dict[str, Any]]:
    """Lee todas las rondas y encuentros de un cuadro eliminatorio."""
    soup = BeautifulSoup(html, "html.parser")
    partidos: list[dict[str, Any]] = []

    for ronda in soup.select(".tournament-round"):
        fase = normalizar_fase(_texto(ronda.select_one(".round-header")))
        for encuentro in ronda.select(".match"):
            equipos = encuentro.select(":scope > .match-team")
            if len(equipos) < 2:
                equipos = encuentro.select(".match-team")
            if len(equipos) < 2:
                continue

            pareja1 = _texto(equipos[0].select_one(".team-name"))
            pareja2 = _texto(equipos[1].select_one(".team-name"))
            if not pareja1 and not pareja2:
                continue

            resultado = _texto(encuentro.select_one(".match-result"))
            ganador_lado = None
            if "winner" in (equipos[0].get("class") or []):
                ganador_lado = 1
            elif "winner" in (equipos[1].get("class") or []):
                ganador_lado = 2

            partidos.append(
                {
                    "categoria": categoria,
                    "categoria_nombre": categoria,
                    "grupo": "",
                    "fase": fase,
                    "tipo": "cuadro",
                    "pareja1": pareja1,
                    "pareja2": pareja2,
                    "horario_pista": "",
                    "resultado": resultado,
                    "jugado": resultado_jugado(resultado),
                    "ganador_lado": ganador_lado,
                }
            )
    return partidos


def _grupo_desde_etiqueta(etiqueta: str) -> str:
    coincidencia = re.search(r"GRUPO\s+\d+", etiqueta or "", re.I)
    return coincidencia.group(0).title() if coincidencia else ""


def incorporar_partidos_mejorado(
    partidos: list[dict[str, str]],
    jugadores: list[str],
    resultados: dict[str, dict[str, Any]],
    firmas_resultados: set[tuple[str, ...]],
    url_origen: str,
    categoria_respaldo: str,
) -> int:
    """Versión compatible con scraper.incorporar_partidos que añade fase y victoria."""
    encontrados = 0
    for partido in partidos:
        for nombre in jugadores:
            en_p1 = scraper.jugador_en_texto(nombre, partido["pareja1"])
            en_p2 = scraper.jugador_en_texto(nombre, partido["pareja2"])
            if not (en_p1 or en_p2):
                continue

            lado = 1 if en_p1 else 2
            rival = partido["pareja2"] if en_p1 else partido["pareja1"]
            resultado_txt = scraper.limpiar_texto(partido["resultado"])
            ganador = ganador_por_resultado(resultado_txt)
            jugado = resultado_jugado(resultado_txt)
            registro = {
                "categoria": partido.get("categoria", "") or categoria_respaldo,
                "categoria_nombre": categoria_respaldo,
                "grupo": _grupo_desde_etiqueta(partido.get("categoria", "")),
                "fase": "Fase de grupos",
                "tipo": "grupo",
                "rival": rival,
                "horario_pista": partido.get("horario_pista", ""),
                "resultado": resultado_txt,
                "jugado": jugado,
                "ganado": (ganador == lado) if jugado and ganador else None,
                "url_grupo": url_origen,
            }
            firma = (
                scraper.normalizar(nombre),
                "grupo",
                scraper.normalizar(categoria_respaldo),
                scraper.normalizar(registro["grupo"]),
                scraper.normalizar(rival),
                scraper.normalizar(registro["horario_pista"]),
                scraper.normalizar(resultado_txt),
            )
            if firma not in firmas_resultados:
                firmas_resultados.add(firma)
                resultados[nombre]["partidos"].append(registro)
                encontrados += 1
    return encontrados


def incorporar_partidos_cuadro(
    partidos: list[dict[str, Any]],
    jugadores: list[str],
    resultados: dict[str, dict[str, Any]],
    firmas_resultados: set[tuple[str, ...]],
    url_cuadro: str,
) -> int:
    encontrados = 0
    for partido in partidos:
        for nombre in jugadores:
            en_p1 = scraper.jugador_en_texto(nombre, partido.get("pareja1", ""))
            en_p2 = scraper.jugador_en_texto(nombre, partido.get("pareja2", ""))
            if not (en_p1 or en_p2):
                continue

            lado = 1 if en_p1 else 2
            rival = partido.get("pareja2", "") if en_p1 else partido.get("pareja1", "")
            ganador_lado = partido.get("ganador_lado")
            registro = {
                "categoria": partido.get("categoria", ""),
                "categoria_nombre": partido.get("categoria_nombre", partido.get("categoria", "")),
                "grupo": "",
                "fase": partido.get("fase", "Cuadro"),
                "tipo": "cuadro",
                "rival": rival or "Por determinar",
                "horario_pista": partido.get("horario_pista", ""),
                "resultado": partido.get("resultado", ""),
                "jugado": bool(partido.get("jugado")),
                "ganado": (ganador_lado == lado) if partido.get("jugado") and ganador_lado else None,
                "url_cuadro": url_cuadro,
            }
            firma = (
                scraper.normalizar(nombre),
                "cuadro",
                scraper.normalizar(registro["categoria_nombre"]),
                scraper.normalizar(registro["fase"]),
                scraper.normalizar(rival),
                scraper.normalizar(registro["resultado"]),
            )
            if firma not in firmas_resultados:
                firmas_resultados.add(firma)
                resultados[nombre]["partidos"].append(registro)
                encontrados += 1
    return encontrados


def _estado_logro(partido: dict[str, Any]) -> tuple[str, int]:
    fase = partido.get("fase", "")
    jugado = bool(partido.get("jugado"))
    ganado = partido.get("ganado")

    if fase == "Final":
        if jugado and ganado is True:
            return "Campeón", 100
        if jugado and ganado is False:
            return "Finalista", 90
        return "Final", 80
    if fase == "Semifinales":
        if jugado and ganado is True:
            return "Final", 80
        if jugado and ganado is False:
            return "Semifinalista", 70
        return "Semifinales", 70
    if fase == "Cuartos de final":
        if jugado and ganado is True:
            return "Semifinales", 70
        return "Cuartos de final", 60
    if fase == "Octavos de final":
        if jugado and ganado is True:
            return "Cuartos de final", 60
        return "Octavos de final", 50
    if fase == "Dieciseisavos":
        if jugado and ganado is True:
            return "Octavos de final", 50
        return "Dieciseisavos", 40
    return fase or "Cuadro", 30


def calcular_logros(partidos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Calcula el mejor punto alcanzado en cada categoría con cuadro."""
    por_categoria: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for partido in partidos:
        if partido.get("tipo") == "cuadro":
            por_categoria[partido.get("categoria_nombre") or partido.get("categoria", "")].append(partido)

    logros: list[dict[str, Any]] = []
    for categoria, encuentros in por_categoria.items():
        mejor_rango = max(fase_orden(e.get("fase", "")) for e in encuentros)
        candidatos = [e for e in encuentros if fase_orden(e.get("fase", "")) == mejor_rango]
        mejor = candidatos[-1]
        estado, nivel = _estado_logro(mejor)
        logros.append(
            {
                "categoria": categoria,
                "estado": estado,
                "nivel": nivel,
                "url_cuadro": mejor.get("url_cuadro", ""),
            }
        )
    return sorted(logros, key=lambda logro: (-logro["nivel"], scraper.normalizar(logro["categoria"])))


def resumen_jugador(partidos: list[dict[str, Any]]) -> dict[str, int]:
    jugados = [p for p in partidos if p.get("jugado")]
    return {
        "partidos": len(partidos),
        "jugados": len(jugados),
        "victorias": sum(p.get("ganado") is True for p in jugados),
        "derrotas": sum(p.get("ganado") is False for p in jugados),
        "pendientes": sum(not p.get("jugado") for p in partidos),
    }
