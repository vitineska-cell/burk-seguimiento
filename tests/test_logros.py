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


if __name__ == "__main__":
    test_detectar_fases()
    test_resultado_se_interpreta_segun_lado_del_jugador()
    test_logro_final()
    test_categoria_limpia()
    test_marcador_a_varios_sets()
    test_victor_sebastian_es_campeon_y_final_pendiente_recibe_horario()
    print("OK: fases, victorias y logros")
