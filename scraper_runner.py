#!/usr/bin/env python3
"""Ejecutor robusto del scraper BÜRK con resultados y logros por fase."""
from __future__ import annotations

import json
import copy
import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable
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
from matching import IdentidadesOficiales, jugador_en_texto_flexible as jugador_en_texto
from fases import detectar_fase

FASES = {
    "grupos": 0, "dieciseisavos": 1, "octavos": 2,
    "cuartos": 3, "semifinal": 4, "final": 5,
}
MAX_PARALLEL_REQUESTS = 6
STATUS_PATH = OUTPUT_PATH.with_name('estado.json')


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
                    "Cache-Control": "no-cache",
                },
            )
            with urlopen(request, timeout=timeout) as respuesta:
                contenido = respuesta.read()
                charset = respuesta.headers.get_content_charset() or "utf-8"
            html = contenido.decode(charset, errors="replace")
            nombre = hashlib.sha256(url.encode()).hexdigest()[:16]
            guardar_debug(nombre + '.html', html)
            guardar_debug(nombre + '.url', url)
            return html
        except Exception as exc:
            ultimo_error = exc
            if intento < intentos:
                time.sleep(intento)
    raise RuntimeError(f"No se pudo cargar {url}: {ultimo_error}")


def cargar_urls_en_paralelo(
    urls: list[str],
    cargador: Callable[[str], str] = cargar_url,
    max_workers: int = MAX_PARALLEL_REQUESTS,
) -> tuple[dict[str, str], dict[str, Exception]]:
    """Descarga URL independientes a la vez y conserva cada error por separado."""
    unicas = list(dict.fromkeys(url for url in urls if url))
    if not unicas:
        return {}, {}

    paginas: dict[str, str] = {}
    errores: dict[str, Exception] = {}
    trabajadores = max(1, min(max_workers, len(unicas)))
    with ThreadPoolExecutor(
        max_workers=trabajadores, thread_name_prefix="burk-http"
    ) as ejecutor:
        futuros = {ejecutor.submit(cargador, url): url for url in unicas}
        for futuro in as_completed(futuros):
            url = futuros[futuro]
            try:
                paginas[url] = futuro.result()
            except Exception as exc:
                errores[url] = exc
    return paginas, errores


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


def _equipos_coinciden(a: str, b: str, identidades=None) -> bool:
    """Admite apellidos omitidos, sin confundir individuales con dobles."""
    from itertools import permutations
    if identidades:
        ids_a, ids_b = identidades.equipo(a), identidades.equipo(b)
        if ids_a and ids_b:
            return ids_a == ids_b
    equipo_a = [normalizar(n).split() for n in a.split("/") if n.strip()]
    equipo_b = [normalizar(n).split() for n in b.split("/") if n.strip()]
    if not equipo_a or len(equipo_a) != len(equipo_b):
        return False

    def mismo_nombre(x, y):
        corto, largo = sorted((x, y), key=len)
        if len(corto) < 2 or corto[0] != largo[0]:
            return False
        restantes = iter(largo)
        return all(any(token == otro for otro in restantes) for token in corto)

    return any(all(mismo_nombre(x, y) for x, y in zip(equipo_a, orden))
               for orden in permutations(equipo_b))


def _fusionar_registro(existente: dict[str, Any], nuevo: dict[str, Any]) -> None:
    """Completa un cruce ya visto con resultado, horario o estado más reciente."""
    if nuevo.get("jugado") or (not existente.get("jugado") and nuevo.get("resultado")):
        existente["resultado"] = nuevo["resultado"]
        existente["jugado"] = nuevo["jugado"]
        existente["ganado"] = nuevo.get("ganado")
    if nuevo.get("horario_pista"):
        existente["horario_pista"] = nuevo["horario_pista"]
    if nuevo.get("estado_programacion") and not existente.get("jugado"):
        existente["estado_programacion"] = nuevo["estado_programacion"]
    if existente.get("jugado"):
        existente['estado_programacion'] = 'Partido finalizado'
    if nuevo.get('id_partido'):
        existente['id_partido'] = nuevo['id_partido']
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
    incidencias: list | None = None, identidades=None,
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
            jugado = partido.get('jugado', resultado_esta_jugado(resultado))
            if not jugado and not resultado_esta_jugado(resultado):
                resultado = ''
            ganador = partido.get("ganador") or (
                _ganador_desde_resultado(resultado) if jugado else None
            )
            ganado = None
            if jugado and ganador in (1, 2):
                ganado = (ganador == 1) if en_p1 else (ganador == 2)
            categoria_raw = partido.get("categoria", "") or categoria_respaldo
            categoria = categoria_limpia(categoria_raw, categoria_respaldo)
            if normalizar(categoria) == 'categoria' and normalizar(categoria_respaldo) not in ('categoria', 'orden de juego', ''):
                categoria = categoria_respaldo
            fase = detectar_fase(categoria_raw)
            equipo = partido["pareja1"] if en_p1 else partido["pareja2"]
            # La programación oficial puede omitir la categoría. Solo se une
            # cuando ambos equipos y la fase identifican un único cruce previo.
            if normalizar(categoria) in ("categoria", "orden de juego", ""):
                candidatos = [
                    p for p in resultados[nombre]["partidos"]
                    if p.get("fase") == fase
                    and _equipos_coinciden(p.get("equipo", ""), equipo, identidades)
                    and _equipos_coinciden(p.get("rival", ""), rival, identidades)
                ]
                if len(candidatos) != 1:
                    incidencia = {'jugador': nombre, 'rival': rival, 'fase': fase,
                                  'url': url_origen, 'tipo': 'categoria_no_resuelta',
                                  'partido': partido}
                    if incidencias is not None:
                        incidencias.append(incidencia)
                    log(f"AVISO: cruce sin categoría confirmada: {nombre} contra {rival}")
                    continue
                categoria = candidatos[0]["categoria"]
            # El marcador se presenta siempre desde el lado del jugador BÜRK.
            if en_p2:
                resultado = re.sub(
                    r"(\d+)\s*[-–:]\s*(\d+)",
                    lambda m: f"{m.group(2)}-{m.group(1)}", resultado,
                )
            registro = {
                "categoria": categoria,
                "fase": fase,
                "equipo": equipo,
                "rival": rival,
                "horario_pista": partido.get("horario_pista", ""),
                "resultado": resultado,
                "jugado": jugado,
                "ganado": ganado,
                "url_grupo": url_origen,
            }
            if partido.get('id_partido'):
                registro['id_partido'] = partido['id_partido']
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
                    and _equipos_coinciden(item.get("equipo", ""), equipo, identidades)
                    and _equipos_coinciden(item.get("rival", ""), rival, identidades)
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
        if ganado is None:
            continue
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


def leer_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def escribir_json(path, data):
    path.parent.mkdir(exist_ok=True)
    temporal = path.with_suffix('.tmp')
    temporal.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporal.replace(path)


def conservar_resultados_confirmados(anterior, resultados, torneo_id, incidencias, identidades=None, fuentes_incompletas=False):
    """Una fuente incompleta no borra resultados ya publicados del mismo torneo."""
    if anterior.get('torneo_id') != torneo_id:
        return
    for nombre, datos in resultados.items():
        for previo in anterior.get('jugadores', {}).get(nombre, {}).get('partidos', []):
            if not previo.get('jugado') and not fuentes_incompletas:
                continue
            actual = next((p for p in datos['partidos']
                           if p['categoria'] == previo['categoria'] and p['fase'] == previo['fase']
                           and _equipos_coinciden(p.get('equipo', ''), previo.get('equipo', ''), identidades)
                           and _equipos_coinciden(p['rival'], previo['rival'], identidades)), None)
            if actual is not None and actual.get('jugado'):
                continue  # Una corrección oficial actual sí sustituye el marcador anterior.
            if actual is not None and not previo.get('jugado'):
                continue
            if actual is not None and 'cancel' in normalizar(actual.get('estado_programacion', '')):
                continue
            if actual is None:
                actual = copy.deepcopy(previo)
                datos['partidos'].append(actual)
            else:
                _fusionar_registro(actual, previo)
            actual['pendiente_verificacion'] = True
            incidencias.append({'tipo': 'resultado_conservado', 'jugador': nombre,
                                'rival': previo['rival'], 'url': previo.get('url_grupo', '')})


def publicar_estado(config, incidencias, errores=0, error=None):
    previo = leer_json(STATUS_PATH)
    ahora = datetime.now(timezone.utc).isoformat()
    estado = 'error' if error else ('parcial' if errores or incidencias else 'ok')
    data = {'torneo_id': config.get('torneo_id'), 'estado': estado,
            'comprobado': ahora,
            'ultima_correcta': ahora if estado == 'ok' else previo.get('ultima_correcta'),
            'actualizacion_hasta': config.get('actualizacion_hasta'),
            'errores': errores, 'incidencias': [
                {k: v for k, v in i.items() if k != 'partido'} for i in incidencias]}
    if error:
        data['mensaje'] = str(error)
    escribir_json(STATUS_PATH, data)


def ejecutar():
    try:
        main()
    except Exception as exc:
        publicar_estado(cargar_config(), [], errores=1, error=exc)
        raise


def main() -> None:
    inicio = time.monotonic()
    config = cargar_config()
    torneo_id = int(config["torneo_id"])
    torneo_nombre = config.get("torneo_nombre", "")
    jugadores: list[str] = config["jugadores"]
    anterior = leer_json(OUTPUT_PATH)
    alias_previos = anterior.get('identidades', {}) if anterior.get('torneo_id') == torneo_id else {}
    incidencias = []
    identidades = IdentidadesOficiales(anteriores=alias_previos)
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

    urls_principales = [
        url
        for destino in destinos
        for url in ([destino.get("categoria_url")] + destino.get("cuadro_urls", []))
        if url
    ]
    paginas_principales, fallos_principales = cargar_urls_en_paralelo(urls_principales)

    for indice, destino in enumerate(destinos, 1):
        if time.monotonic() - inicio > MAX_RUNTIME_SECONDS:
            raise RuntimeError("Tiempo máximo interno superado")
        nombre_categoria = destino["nombre"]
        partidos_categoria: list[dict[str, str]] = []
        url_categoria = destino["categoria_url"]
        if url_categoria:
            if url_categoria in fallos_principales:
                errores += 1
                exc = fallos_principales[url_categoria]
                log(f"ERROR categoría {indice}: {type(exc).__name__}: {exc}")
            else:
                partidos_categoria = extraer_todas_las_tablas_partidos(
                    paginas_principales.get(url_categoria, "")
                )
        grupos_leidos = contar_grupos_en_partidos(partidos_categoria)
        usar_respaldo = not partidos_categoria or (
            len(destino["grupo_urls"]) > 1 and grupos_leidos < len(destino["grupo_urls"])
        )
        if partidos_categoria:
            filas_detectadas += len(partidos_categoria)
            encontrados = incorporar_partidos_enriquecidos(
                partidos_categoria, jugadores, resultados, firmas,
                url_categoria or url_torneo, nombre_categoria, incidencias)
            categorias_procesadas += 1
            log(
                f"[{indice}/{len(destinos)}] {nombre_categoria}: "
                f"{len(partidos_categoria)} partidos, {encontrados} BÜRK"
            )
        if usar_respaldo:
            paginas_grupo, fallos_grupo = cargar_urls_en_paralelo(destino["grupo_urls"])
            for url_grupo in destino["grupo_urls"]:
                if url_grupo in fallos_grupo:
                    errores += 1
                    exc = fallos_grupo[url_grupo]
                    log(f"ERROR grupo: {type(exc).__name__}: {exc}")
                    continue
                partidos_grupo = extraer_todas_las_tablas_partidos(
                    paginas_grupo.get(url_grupo, "")
                )
                if not partidos_grupo:
                    continue
                filas_detectadas += len(partidos_grupo)
                incorporar_partidos_enriquecidos(
                    partidos_grupo, jugadores, resultados, firmas,
                    url_grupo, nombre_categoria, incidencias)
                paginas_grupo_procesadas += 1

        for url_cuadro in destino.get("cuadro_urls", []):
            if url_cuadro in fallos_principales:
                errores += 1
                exc = fallos_principales[url_cuadro]
                log(f"ERROR cuadro {nombre_categoria}: {type(exc).__name__}: {exc}")
                continue
            partidos_cuadro = extraer_partidos_cuadro(
                paginas_principales.get(url_cuadro, ""), nombre_categoria
            )
            if not partidos_cuadro:
                continue
            filas_detectadas += len(partidos_cuadro)
            encontrados = incorporar_partidos_enriquecidos(
                partidos_cuadro, jugadores, resultados, firmas,
                url_cuadro, nombre_categoria, incidencias,
            )
            cuadros_procesados += 1
            log(
                f"  cuadro {nombre_categoria}: {len(partidos_cuadro)} cruces, "
                f"{encontrados} coincidencias BÜRK"
            )

    try:
        url_panel_orden = f"{BASE_URL}/torneo_panel.ashx?panel=ordenjuego&id={torneo_id}"
        urls_orden = extraer_urls_orden_juego(cargar_url(url_panel_orden), torneo_id)
        if not urls_orden and anterior.get('diagnostico', {}).get('dias_orden_juego_procesados'):
            raise RuntimeError('La orden de juego antes publicada no está disponible en este barrido')
        paginas_orden, fallos_orden = cargar_urls_en_paralelo(urls_orden)
        ordenes = []
        for url_orden in urls_orden:
            if url_orden in fallos_orden:
                errores += 1
                exc = fallos_orden[url_orden]
                log(f"ERROR día de orden de juego: {type(exc).__name__}: {exc}")
                continue
            fecha = parse_qs(urlparse(url_orden).query).get("f", [""])[0]
            partidos_orden = extraer_partidos_orden_juego(
                paginas_orden.get(url_orden, ""), fecha
            )
            if not partidos_orden:
                errores += 1
                incidencias.append({'tipo': 'orden_vacia', 'url': url_orden})
                continue
            filas_detectadas += len(partidos_orden)
            ordenes.append((url_orden, partidos_orden))
            dias_orden_procesados += 1
        identidades = IdentidadesOficiales((p for _, partidos in ordenes for p in partidos), alias_previos)
        for url_orden, partidos_orden in ordenes:
            incorporar_partidos_enriquecidos(
                partidos_orden, jugadores, resultados, firmas,
                url_orden, "Orden de juego",
                incidencias, identidades,
            )
        log(
            f"Orden de juego: {dias_orden_procesados} día(s), "
            f"{len(urls_orden)} publicado(s)"
        )
    except Exception as exc:
        errores += 1
        log(f"ERROR orden de juego: {type(exc).__name__}: {exc}")
        incidencias.append({'tipo': 'error_orden_juego', 'detalle': str(exc)})

    if filas_detectadas == 0:
        raise RuntimeError("La extracción no produjo filas válidas")
    conservar_resultados_confirmados(anterior, resultados, torneo_id, incidencias, identidades, errores > 0)
    ids_seguidos = set()
    for datos in resultados.values():
        for partido in datos['partidos']:
            for campo in ('equipo', 'rival'):
                ids = identidades.equipo(partido.get(campo, ''))
                if ids:
                    partido[campo + '_ids'] = list(ids)
                    ids_seguidos.update(ids)
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
                        "incidencias": len(incidencias),
                        "errores": errores, "filas_partido_leidas": filas_detectadas},
        "jugadores": resultados,
        "identidades": {nombre: sorted(ids) for nombre, ids in sorted(identidades.alias.items())
                        if ids & ids_seguidos},
    }
    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    guardar_debug('incidencias.json', json.dumps(incidencias, ensure_ascii=False, indent=2))
    publicar_estado(config, incidencias, errores)
    cambios_deportivos = salida_tiene_cambios(anterior, salida)
    if anterior and not cambios_deportivos and anterior.get('identidades') == salida['identidades']:
        log("Sin cambios deportivos: se conserva resultados.json y no se crea un commit.")
        return
    salida["actualizado"] = datetime.now(timezone.utc).isoformat() if cambios_deportivos else anterior['actualizado']
    escribir_json(OUTPUT_PATH, salida)
    log(f"Listo: {total} partidos para {len(jugadores)} jugadores BÜRK.")


if __name__ == "__main__":
    ejecutar()
