import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fases import detectar_fase
from scraper_runner import (
    _ganador_desde_resultado,
    calcular_logros,
    categoria_limpia,
    incorporar_partidos_enriquecidos,
)


def test_detectar_fases():
    assert detectar_fase("SEMIFINAL") == "semifinal"
    assert detectar_fase("Semi · CATEGORIA ABSOLUTA 3.5 Double MASCULINO") == "semifinal"
    assert detectar_fase("FINAL") == "final"
    assert detectar_fase("CUARTOS DE FINAL") == "cuartos"
    assert detectar_fase("GRUPO 3 - PARTIDOS") == "grupos"


def test_resultado_se_interpreta_segun_lado_del_jugador():
    jugadores = ["Ana Pérez", "Luis Gómez"]
    resultados = {n: {"partidos": [], "logros": []} for n in jugadores}
    partidos = [{
        "categoria": "FINAL · CATEGORIA PRO DOUBLE MIXTO",
        "pareja1": "Ana Pérez / Marta Ruiz",
        "pareja2": "Luis Gómez / Juan López",
        "horario_pista": "12/07/2026 18:00 / Pista: 1",
        "resultado": "21 - 17",
    }]
    incorporar_partidos_enriquecidos(partidos, jugadores, resultados, set(), "url", "PRO Double Mixto")
    assert resultados["Ana Pérez"]["partidos"][0]["ganado"] is True
    assert resultados["Luis Gómez"]["partidos"][0]["ganado"] is False


def test_logro_final():
    campeon = calcular_logros([{
        "categoria": "PRO Double Mixto", "fase": "final", "jugado": True, "ganado": True
    }])
    finalista = calcular_logros([{
        "categoria": "PRO Double Mixto", "fase": "final", "jugado": True, "ganado": False
    }])
    assert campeon == [{"titulo": "Campeón", "categoria": "PRO Double Mixto"}]
    assert finalista == [{"titulo": "Finalista", "categoria": "PRO Double Mixto"}]


def test_categoria_limpia():
    assert categoria_limpia(
        "GRUPO 3 - PARTIDOS · CATEGORIA ABSOLUTA 3.5 Double MASCULINO", "respaldo"
    ) == "ABSOLUTA 3.5 Double MASCULINO"
    assert categoria_limpia(
        "Grupos · CATEGORIA ABSOLUTA 3.5 Single MASCULINO", "respaldo"
    ) == "ABSOLUTA 3.5 Single MASCULINO"
    assert categoria_limpia(
        "1/4 · CATEGORIA ABSOLUTA 3.5 Double MASCULINO", "respaldo"
    ) == "ABSOLUTA 3.5 Double MASCULINO"


def test_marcador_a_varios_sets():
    assert _ganador_desde_resultado("21-8 / 19-21 / 20-22") == 2
    assert _ganador_desde_resultado("21-14 / 21-18") == 1


def test_victor_sebastian_es_campeon_y_final_pendiente_recibe_horario():
    jugadores = ["Victor Sebastian Davila"]
    resultados = {jugadores[0]: {"partidos": [], "logros": []}}
    firmas = set()
    cuadro = [{
        "categoria": "Final · CATEGORIA ABSOLUTA 3.5 Double MASCULINO",
        "pareja1": "Lucas Corral / Victor Sebastian",
        "pareja2": "Juan Luis Giner / Alejandro Castro",
        "horario_pista": "",
        "resultado": "",
        "ganador": None,
    }]
    orden = [{
        "categoria": "Final · CATEGORIA ABSOLUTA 3.5 Double MASCULINO",
        "pareja1": "Lucas Corral Falagan / Victor Sebastian Davila",
        "pareja2": "Juan Luis Giner Maroto / Alejandro Castro Lorenzo",
        "horario_pista": "12/07/2026 10:00 / Pista: 17",
        "resultado": "",
        "ganador": None,
        "estado_programacion": "Comienza a las 10:00",
    }]
    incorporar_partidos_enriquecidos(cuadro, jugadores, resultados, firmas, "cuadro", "respaldo")
    incorporar_partidos_enriquecidos(orden, jugadores, resultados, firmas, "orden", "respaldo")
    assert len(resultados[jugadores[0]]["partidos"]) == 1
    assert resultados[jugadores[0]]["partidos"][0]["horario_pista"].startswith("12/07/2026 10:00")

    cuadro[0]["resultado"] = "21-14 / 21-18"
    cuadro[0]["ganador"] = 1
    incorporar_partidos_enriquecidos(cuadro, jugadores, resultados, firmas, "cuadro", "respaldo")
    partido = resultados[jugadores[0]]["partidos"][0]
    assert partido["jugado"] is True
    assert partido["ganado"] is True
    assert calcular_logros([partido]) == [{
        "titulo": "Campeón", "categoria": "ABSOLUTA 3.5 Double MASCULINO"
    }]


def test_barcelona_sin_categoria_no_duplica_ni_mezcla_modalidades():
    from scraper import extraer_partidos_orden_juego
    nombre = "Brenda Fariña Solís"
    resultados = {nombre: {"partidos": [], "logros": []}}
    firmas = set()
    html = (Path(__file__).parent / "fixture_barcelona_sin_categoria.html").read_text()
    orden = extraer_partidos_orden_juego(html)
    assert len(orden) == 7
    grupos = []
    for partido in orden:
        grupo = dict(partido)
        modalidad = "Double" if "/" in partido["pareja1"] else "Single"
        grupo["categoria"] = f"GRUPO 1 - PARTIDOS · CATEGORIA ABSOLUTA 4.5 {modalidad} FEMENINO"
        grupos.append(grupo)
    incorporar_partidos_enriquecidos(grupos, [nombre], resultados, firmas, "grupos", "respaldo")
    incorporar_partidos_enriquecidos(orden, [nombre], resultados, firmas, "orden", "Orden de juego")
    partidos = resultados[nombre]["partidos"]
    assert len(partidos) == 7
    assert sum("Single" in p["categoria"] for p in partidos) == 3
    celia = next(p for p in partidos if p["rival"] == "Celia Millon")
    assert celia["ganado"] is False
    assert celia["resultado"] == "15-21"
    assert "12:00" in celia["horario_pista"]


def test_apellido_intermedio_omitido_y_modalidades():
    from scraper_runner import _equipos_coinciden
    assert _equipos_coinciden("Juan Plana / David Rius Marti", "David Marti / Juan Plana")
    assert not _equipos_coinciden("Juan Plana / David Marti", "Juan Plana")
    assert not _equipos_coinciden("David Rius Marti", "David Garcia")


def test_categoria_ambigua_no_se_inventa():
    nombre = "Ana Pérez"
    resultados = {nombre: {"partidos": [], "logros": []}}
    firmas = set()
    partido = {"pareja1": nombre, "pareja2": "Marta Ruiz", "resultado": "21-10"}
    for categoria in ("ABSOLUTA Single FEMENINO", "+50 Single FEMENINO"):
        incorporar_partidos_enriquecidos([dict(partido, categoria=categoria)], [nombre], resultados, firmas, "grupo", categoria)
    incidencias = []
    incorporar_partidos_enriquecidos([dict(partido, categoria="Grupos · CATEGORIA Categoría")], [nombre], resultados, firmas, "orden", "Orden de juego", incidencias)
    assert len(incidencias) == 1
    assert incidencias[0]['tipo'] == 'categoria_no_resuelta'
    assert len(resultados[nombre]["partidos"]) == 2


if __name__ == "__main__":
    test_barcelona_sin_categoria_no_duplica_ni_mezcla_modalidades()
    test_categoria_ambigua_no_se_inventa()
    test_apellido_intermedio_omitido_y_modalidades()
    test_detectar_fases()
    test_resultado_se_interpreta_segun_lado_del_jugador()
    test_logro_final()
    test_categoria_limpia()
    test_marcador_a_varios_sets()
    test_victor_sebastian_es_campeon_y_final_pendiente_recibe_horario()
    print("OK: fases, victorias y logros")
