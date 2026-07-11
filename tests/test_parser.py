import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import (
    extraer_categoria_y_tabla_partidos,
    extraer_todas_las_tablas_partidos,
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


if __name__ == "__main__":
    test_fixture_real()
    test_nombres_con_html_intermedio()
    test_dobles_en_cuatro_columnas_y_varios_grupos()
    print("Todos los tests del parser v4 pasan.")
