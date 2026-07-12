#!/usr/bin/env python3
"""Ejecutor robusto del scraper BÜRK con resultados y logros por fase."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from scraper import (
    BASE_URL, MAX_RUNTIME_SECONDS, OUTPUT_PATH,
    cargar_config, contar_grupos_en_partidos,
    extraer_destinos_torneo, extraer_partidos_cuadro,
    extraer_partidos_orden_juego, extraer_todas_las_tablas_partidos,
    extraer_urls_orden_juego,
    guardar_debug, limpiar_texto, log, normalizar,
    resultado_esta_jugado,
)
from matching import jugador_en_texto_flexible as jugador_en_texto

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


def cargar_url(url: str, intentos: int = 3, timeout: int = 35) -> str:
    """Descarga HTML server-rendered con reintentos y sin depender del navegador."""
    ultimo_error: Exception | None = None
    for intento in range(1, intentos + 1):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "Chrome/130 Safari/537.36"
                    ),
                    "Accept-Language": "es-ES,es;q=0.9",
                },
            )
            with urlopen(request, timeout=timeout) as respuesta:
                contenido = respuesta.read()
                charset = respuesta.headers.get_content_charset() or "utf-8"
            return contenido.decode(charset, errors="replace")
        except Exception as exc:
            ultimo_error = exc
            if intento < intentos:
                time.sleep(intento)
    raise RuntimeError(f"No se pudo cargar {url}: {ultimo_error}")


def detectar_fase(texto: str) -> str:
    valor = normalizar(texto)
    if "final" in valor and "semifinal" not in valor:
        return "final"
    if (
        "semifinal" in valor
        or "semi final" in valor
        or valor == "semi"
        or valor.startswith("semi ")
    ):
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
    base = re.sub(
        r"^(?:GRUPOS|1\s*/\s*16|1\s*/\s*8|1\s*/\s*4|DIECISEISAVOS|OCTAVOS|"
        r"CUARTOS(?:\s+DE\s+FINAL)?|SEMI(?:FINAL)?|FINAL)"
        r"\s*[·-]?\s*",
        "",
        base,
        flags=re.I,
    )
    base = re.sub(r"\bCATEGORIA\b\s*", "", base, flags=re.I)
    return limpiar_texto(base).strip(" ·-") or respaldo


def _ganador_desde_resultado(resultado: str) -> int | None:
    """Interpreta uno o varios sets y devuelve 1/2; no adivina empates."""
    parciales = re.findall(r"(\d+)\s*[-–:]\s*(\d+)", resultado or "")
    if not parciales:
        return None
    ganados_1 = sum(int(a) > int(b) for a, b in parciales)
    ganados_2 = sum(int(b) > int(a) for a, b in parciales)
    if ganados_1 == ganados_2:
        return None
    return 1 if ganados_1 > ganados_2 else 2


def _firma_equipo(texto: str) -> tuple[str, ...]:
    """Firma estable aunque Orden de juego muestre apellidos adicionales."""
    miembros = []
    for miembro in re.split(r"\s*/\s*", texto or ""):
        tokens = normalizar(miembro).split()
        if tokens:
            miembros.append(" ".join(tokens[:2]))
    return tuple(sorted(miembros))


def _fusionar_registro(existente: dict[str, Any], nuevo: dict[str, Any]) -> None:
    """Completa un cruce ya visto con resultado, horario o estado más reciente."""
    if nuevo.get("resultado"):
        existente["resultado"] = nuevo["resultado"]
        existente["jugado"] = nuevo["jugado"]
    if nuevo.get("ganado") is not None:
        existente["ganado"] = nuevo["ganado"]
    if nuevo.get("horario_pista"):
        existente["horario_pista"] = nuevo["horario_pista"]
    if nuevo.get("estado_programacion"):
        existente["estado_programacion"] = nuevo["estado_programacion"]
    url_existente = normalizar(existente.get("url_grupo", ""))
    url_nueva = normalizar(nuevo.get("url_grupo", ""))
    if nuevo.get("url_grupo") and (
        not existente.get("url_grupo")
        or ("torneocuadro aspx" in url_nueva and "torneocuadro aspx" not in url_existente)
    ):
        existente["url_grupo"] = nuevo["url_grupo"]


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
            ganador = partido.get("ganador") or (
                _ganador_desde_resultado(resultado) if jugado else None
            )
            ganado = None
            if ganador in (1, 2):
                ganado = (ganador == 1) if en_p1 else (ganador == 2)
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
            if partido.get("estado_programacion"):
                registro["estado_programacion"] = partido["estado_programacion"]

            firma_base = (
                normalizar(nombre),
                normalizar(registro["categoria"]),
                registro["fase"],
                *_firma_equipo(rival),
            )
            existente = next(
                (
                    item
                    for item in resultados[nombre]["partidos"]
                    if normalizar(item.get("categoria", "")) == firma_base[1]
                    and item.get("fase") == registro["fase"]
                    and _firma_equipo(item.get("rival", "")) == _firma_equipo(rival)
                ),
                None,
            )
            if existente is not None:
                _fusionar_registro(existente, registro)
                continue
            if firma_base not in firmas:
                firmas.add(firma_base)
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


def salida_tiene_cambios(anterior: dict[str, Any], nueva: dict[str, Any]) -> bool:
    """Compara los datos deportivos ignorando fecha y diagnóstico técnico."""
    claves = ("torneo_id", "torneo_nombre", "jugadores")
    return any(anterior.get(clave) != nueva.get(clave) for clave in claves)


def main() -> None:
    inicio = time.monotonic()
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores: list[str] = config["jugadores"]
    resultados: dict[str, dict[str, Any]] = {n: {"partidos": [], "logros": []} for n in jugadores}
    firmas: set[tuple[str, ...]] = set()
    categorias_procesadas = paginas_grupo_procesadas = errores = filas_detectadas = 0
    cuadros_procesados = dias_orden_procesados = 0

    log(f"Torneo seleccionado: {torneo_nombre or torneo_id} (id={torneo_id})")
    url_torneo = f"{BASE_URL}/torneo.aspx?id={torneo_id}"
    html_torneo = cargar_url(url_torneo)
    titulo = BeautifulSoup(html_torneo, "html.parser").title
    titulo_web = limpiar_texto(titulo.get_text(" ", strip=True).split("|")[0]) if titulo else ""
    if titulo_web:
        torneo_nombre = titulo_web

    url_panel_cuadros = f"{BASE_URL}/torneo_panel.ashx?panel=cuadros&id={torneo_id}"
    html_listado = cargar_url(url_panel_cuadros)
    destinos = extraer_destinos_torneo(html_listado, torneo_id)
    if not destinos:
        guardar_debug("sin_destinos.html", html_listado)
        raise RuntimeError("No se localizaron URL de categorías, grupos o cuadros")
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
                partidos_categoria = extraer_todas_las_tablas_partidos(cargar_url(url_categoria))
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
            log(
                f"[{indice}/{len(destinos)}] {nombre_categoria}: "
                f"{len(partidos_categoria)} partidos, {encontrados} BÜRK"
            )
        if usar_respaldo:
            for url_grupo in destino["grupo_urls"]:
                try:
                    partidos_grupo = extraer_todas_las_tablas_partidos(cargar_url(url_grupo))
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

        for url_cuadro in destino.get("cuadro_urls", []):
            try:
                partidos_cuadro = extraer_partidos_cuadro(
                    cargar_url(url_cuadro), nombre_categoria
                )
                if not partidos_cuadro:
                    continue
                filas_detectadas += len(partidos_cuadro)
                encontrados = incorporar_partidos_enriquecidos(
                    partidos_cuadro, jugadores, resultados, firmas,
                    url_cuadro, nombre_categoria,
                )
                cuadros_procesados += 1
                log(
                    f"  cuadro {nombre_categoria}: {len(partidos_cuadro)} cruces, "
                    f"{encontrados} coincidencias BÜRK"
                )
            except Exception as exc:
                errores += 1
                log(f"ERROR cuadro {nombre_categoria}: {type(exc).__name__}: {exc}")

    try:
        url_panel_orden = f"{BASE_URL}/torneo_panel.ashx?panel=ordenjuego&id={torneo_id}"
        urls_orden = extraer_urls_orden_juego(cargar_url(url_panel_orden), torneo_id)
        for url_orden in urls_orden:
            fecha = parse_qs(urlparse(url_orden).query).get("f", [""])[0]
            partidos_orden = extraer_partidos_orden_juego(cargar_url(url_orden), fecha)
            filas_detectadas += len(partidos_orden)
            incorporar_partidos_enriquecidos(
                partidos_orden, jugadores, resultados, firmas,
                url_orden, "Orden de juego",
            )
            dias_orden_procesados += 1
        log(
            f"Orden de juego: {dias_orden_procesados} día(s), "
            f"{len(urls_orden)} publicado(s)"
        )
    except Exception as exc:
        errores += 1
        log(f"ERROR orden de juego: {type(exc).__name__}: {exc}")

    if filas_detectadas == 0:
        raise RuntimeError("La extracción no produjo filas válidas")
    for datos in resultados.values():
        datos["partidos"].sort(
            key=lambda x: (
                x["jugado"],
                x.get("horario_pista", ""),
                FASES.get(x.get("fase", "grupos"), 0),
            )
        )
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
    salida: dict[str, Any] = {
        "torneo_id": torneo_id, "torneo_nombre": torneo_nombre,
        "diagnostico": {"categorias_detectadas": len(destinos), "grupos_unicos_detectados": total_grupos,
                        "categorias_procesadas": categorias_procesadas,
                        "grupos_directos_procesados": paginas_grupo_procesadas,
                        "cuadros_procesados": cuadros_procesados,
                        "dias_orden_juego_procesados": dias_orden_procesados,
                        "errores": errores, "filas_partido_leidas": filas_detectadas},
        "jugadores": resultados,
    }
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    anterior: dict[str, Any] = {}
    if OUTPUT_PATH.exists():
        try:
            anterior = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            anterior = {}
    if anterior and not salida_tiene_cambios(anterior, salida):
        log("Sin cambios deportivos: se conserva resultados.json y no se crea un commit.")
        return
    salida["actualizado"] = datetime.now(timezone.utc).isoformat()
    OUTPUT_PATH.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Listo: {total} partidos para {len(jugadores)} jugadores BÜRK.")


if __name__ == "__main__":
    main()
