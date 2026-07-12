from scraper_runner import (
    calcular_logros,
    categoria_limpia,
    detectar_fase,
    incorporar_partidos_enriquecidos,
)


def test_detectar_fases():
    assert detectar_fase("SEMIFINAL") == "semifinal"
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
