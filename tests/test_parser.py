import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import (
    extraer_categoria_y_tabla_partidos,
    extraer_destinos_torneo,
    extraer_partidos_cuadro,
    extraer_partidos_orden_juego,
    extraer_todas_las_tablas_partidos,
    extraer_urls_orden_juego,
    jugador_en_texto,
    normalizar,
)

FIXTURE = Path(__file__).parent / "fixture_grupo.html"


def test_fixture_real():
    html = FIXTURE.read_text(encoding="utf-8")
    categoria, partidos = extraer_categoria_y_tabla_partidos(html)
    assert "GRUPO 3 - PARTIDOS" in categoria
    assert "ABSOLUTA PRO Double MASCULINO" in categoria
    assert len(partidos) == 3
    assert partidos[1]["pareja1"] == "Oscar Villar Sancosmed / Compañero De Prueba"
    assert partidos[1]["resultado"] == "11-4, 11-6"


def test_nombres_con_html_intermedio():
    assert jugador_en_texto("Bárbara Molina Durán", "Bárbara / Molina / Durán")
    assert jugador_en_texto("Victor Sebastian Davila", "Víctor  Sebastian\nDávila")
    assert normalizar("José-Manuel") == "jose manuel"


def test_dobles_en_cuatro_columnas_y_varios_grupos():
    html = """
    <div>CATEGORIA ABSOLUTA 4.5 DOBLE MASCULINO</div>
    <div><span>GRUPO 1</span> - <strong>PARTIDOS</strong></div>
    <table>
      <tr><th>Jugador 1 P1</th><th>Jugador 2 P1</th><th>Jugador 1 P2</th><th>Jugador 2 P2</th><th>Horario / Pista</th><th>Resultado</th></tr>
      <tr><td>Oscar Villar</td><td>Sancosmed</td><td>Pedro Rial</td><td>Marcos Iglesias</td><td>11/07 17:30 / Pista: 6</td><td>sin resultado</td></tr>
    </table>
    <div>GRUPO 2 - PARTIDOS</div>
    <table>
      <tr><th>Pareja 1</th><th>Pareja 2</th><th>Horario / Pista</th><th>Resultado</th></tr>
      <tr><td>Hugo Granados Jimenez<br>Lucas Corral</td><td>Rival Uno<br>Rival Dos</td><td>12/07 10:00 / Pista: 2</td><td>11-8, 11-9</td></tr>
    </table>
    """
    partidos = extraer_todas_las_tablas_partidos(html)
    assert len(partidos) == 2
    assert jugador_en_texto("Oscar Villar Sancosmed", partidos[0]["pareja1"])
    assert jugador_en_texto("Hugo Granados Jimenez", partidos[1]["pareja1"])
    assert "Rival Uno" in partidos[1]["pareja2"]


def test_extrae_urls_directas_sin_duplicar():
    html = """
    <div id="cuadros-todos">
      <div class="cuadros-categoria-block">
        <div class="cuadros-categoria-header">
          <a onclick="abrirCuadroVisor('torneogrupo.aspx?idT=2339&amp;g=908&amp;visor=0', 'ABSOLUTA 3.5')">ABSOLUTA 3.5</a>
        </div>
        <div onclick="abrirCuadroVisor('torneoGrupo.aspx?id=1541&amp;visor=0', 'GRUPO 1')">GRUPO 1</div>
        <div onclick="abrirCuadroVisor('torneoGrupo.aspx?id=1542&amp;visor=0', 'GRUPO 2')">GRUPO 2</div>
        <div onclick="abrirCuadroVisor('torneoCuadro.aspx?id=22380&amp;visor=0', 'Cuadro')">Cuadro</div>
      </div>
      <div class="cuadros-categoria-block">
        <div class="cuadros-categoria-header">
          <a onclick="abrirCuadroVisor('torneogrupo.aspx?idT=2339&amp;g=909&amp;visor=0', 'ABSOLUTA 4.5')">ABSOLUTA 4.5</a>
        </div>
        <div onclick="abrirCuadroVisor('torneoGrupo.aspx?id=1529&amp;visor=0', 'GRUPO 1')">GRUPO 1</div>
      </div>
    </div>
    <div class="cuadros-categoria-block">
      <a onclick="abrirCuadroVisor('torneogrupo.aspx?idT=2339&amp;g=908&amp;visor=0', 'DUPLICADO')">DUPLICADO</a>
    </div>
    """
    destinos = extraer_destinos_torneo(html, 2339)
    assert len(destinos) == 2
    assert destinos[0]["nombre"] == "ABSOLUTA 3.5"
    assert destinos[0]["categoria_url"].endswith("idT=2339&g=908&visor=0")
    assert len(destinos[0]["grupo_urls"]) == 2
    assert destinos[0]["cuadro_urls"][0].endswith("id=22380&visor=0")
    assert destinos[1]["grupo_urls"][0].endswith("id=1529&visor=0")


def test_extrae_cuadro_real_con_campeones():
    html = (Path(__file__).parent / "fixture_cuadro.html").read_text(encoding="utf-8")
    partidos = extraer_partidos_cuadro(html)
    assert len(partidos) == 4
    final = partidos[-1]
    assert final["categoria"] == "Final · CATEGORIA ABSOLUTA 3.5 Double MASCULINO"
    assert final["pareja1"] == "Lucas Corral / Victor Sebastian"
    assert final["resultado"] == "21-14 / 21-18"
    assert final["ganador"] == 1


def test_extrae_horario_de_final_y_urls_diarias():
    panel = """
    <button onclick="abrirOJVisor('ordenJuego.aspx?id_torneo=2339&amp;f=12-07-2026&amp;visor=0','Domingo')"></button>
    """
    urls = extraer_urls_orden_juego(panel, 2339)
    assert urls == [
        "https://pickleprotour.com/ordenJuego.aspx?id_torneo=2339&f=12-07-2026&visor=0"
    ]
    html = (Path(__file__).parent / "fixture_orden_juego.html").read_text(encoding="utf-8")
    partidos = extraer_partidos_orden_juego(html)
    assert len(partidos) == 1
    assert partidos[0]["horario_pista"] == "12/07/2026 10:00 / Pista: 17"
    assert partidos[0]["resultado"] == ""
    assert partidos[0]["estado_programacion"] == "Comienza a las 10:00"


if __name__ == "__main__":
    test_fixture_real()
    test_nombres_con_html_intermedio()
    test_dobles_en_cuatro_columnas_y_varios_grupos()
    test_extrae_urls_directas_sin_duplicar()
    test_extrae_cuadro_real_con_campeones()
    test_extrae_horario_de_final_y_urls_diarias()
    print("Todos los tests del parser v5 pasan.")
