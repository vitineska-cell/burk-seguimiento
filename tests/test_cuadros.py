import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import scraper
from matching import jugador_en_texto_flexible
from seguimiento import (
    asociar_urls_cuadro,
    calcular_logros,
    extraer_partidos_cuadro,
    ganador_por_resultado,
    incorporar_partidos_cuadro,
    incorporar_partidos_mejorado,
)

scraper.jugador_en_texto = jugador_en_texto_flexible

FIXTURE = Path(__file__).parent / "fixture_cuadro.html"


def test_asocia_url_de_cuadro():
    html = """
    <div id="cuadros-todos"><div class="cuadros-categoria-block">
      <div class="cuadros-categoria-header">ABSOLUTA 3.5 Double MASCULINO</div>
      <div onclick="abrirCuadroVisor('torneoCuadro.aspx?id=22374&amp;visor=0', 'Cuadro')">Cuadro</div>
    </div></div>
    """
    destinos = [{"nombre": "ABSOLUTA 3.5 Double MASCULINO", "categoria_url": "x", "grupo_urls": []}]
    salida = asociar_urls_cuadro(html, destinos)
    assert salida[0]["cuadro_url"].endswith("torneoCuadro.aspx?id=22374&visor=0")


def test_parsea_cuadro_y_campeon():
    partidos = extraer_partidos_cuadro(
        FIXTURE.read_text(encoding="utf-8"), "ABSOLUTA 3.5 Double MASCULINO"
    )
    assert [p["fase"] for p in partidos] == ["Cuartos de final", "Semifinales", "Final"]
    resultados = {"Lucas Corral Falagan": {"partidos": []}}
    firmas = set()
    encontrados = incorporar_partidos_cuadro(
        partidos,
        ["Lucas Corral Falagan"],
        resultados,
        firmas,
        "https://example.test/cuadro",
    )
    assert encontrados == 3
    assert all(p["ganado"] is True for p in resultados["Lucas Corral Falagan"]["partidos"])
    logros = calcular_logros(resultados["Lucas Corral Falagan"]["partidos"])
    assert logros[0]["estado"] == "Campeón"


def test_resultados_orientados_en_grupos():
    assert ganador_por_resultado("21 - 10") == 1
    assert ganador_por_resultado("21-8 / 19-21 / 20-22") == 2
    resultados = {
        "Hugo Granados Jimenez": {"partidos": []},
        "Lucas Corral Falagan": {"partidos": []},
    }
    partidos = [{
        "categoria": "GRUPO 2 - PARTIDOS",
        "pareja1": "Hugo Granados",
        "pareja2": "Lucas Corral",
        "horario_pista": "10/07/2026 10:15 / Pista: 12",
        "resultado": "19 - 21",
    }]
    encontrados = incorporar_partidos_mejorado(
        partidos,
        list(resultados),
        resultados,
        set(),
        "https://example.test/grupo",
        "ABSOLUTA 4.5 Single MASCULINO",
    )
    assert encontrados == 2
    assert resultados["Hugo Granados Jimenez"]["partidos"][0]["ganado"] is False
    assert resultados["Lucas Corral Falagan"]["partidos"][0]["ganado"] is True


if __name__ == "__main__":
    test_asocia_url_de_cuadro()
    test_parsea_cuadro_y_campeon()
    test_resultados_orientados_en_grupos()
    print("Todos los tests de cuadros y logros pasan.")
