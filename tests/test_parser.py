"""
Valida extraer_partidos_de_grupo() y jugador_en_texto() contra un HTML de
ejemplo (fixture_grupo.html), sin necesitar conexión a pickleprotour.com.

Uso: python tests/test_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper import extraer_partidos_de_grupo, jugador_en_texto, procesar_grupo

FIXTURE = Path(__file__).parent / "fixture_grupo.html"


def test_categoria_y_partidos():
    html = FIXTURE.read_text(encoding="utf-8")
    categoria, partidos = extraer_partidos_de_grupo(html, torneo_nombre="A Coruña Open")

    assert categoria == "GRUPO 3 ABSOLUTA PRO Double MASCULINO", f"Categoría inesperada: {categoria!r}"
    assert len(partidos) == 3, f"Se esperaban 3 partidos, se encontraron {len(partidos)}"
    print("✅ Categoría y número de partidos correctos:", categoria)


def test_deteccion_de_jugador_con_acentos():
    assert jugador_en_texto("Oscar Villar Sancosmed", "Oscar Villar Sancosmed / Compañero De Prueba")
    assert jugador_en_texto("Bárbara Molina Durán", "bárbara molina duran / Alguien")  # sin tilde en el texto
    assert not jugador_en_texto("Oscar Villar Sancosmed", "Otro Jugador / Otro Mas")
    print("✅ Detección de nombres (con/sin tildes) correcta")


def test_procesar_grupo_completo():
    html = FIXTURE.read_text(encoding="utf-8")
    jugadores = ["Oscar Villar Sancosmed", "Hugo Granados Jimenez", "Jugador Que No Juega Este Grupo"]
    resultados = {n: {"partidos": []} for n in jugadores}

    procesar_grupo(html, jugadores, "https://pickleprotour.com/torneogrupo.aspx?id=1537", "A Coruña Open", resultados)

    assert len(resultados["Oscar Villar Sancosmed"]["partidos"]) == 1
    p = resultados["Oscar Villar Sancosmed"]["partidos"][0]
    assert p["rival"] == "Rival Uno / Rival Dos"
    assert p["jugado"] is True
    assert p["resultado"] == "11-4, 11-6"

    assert len(resultados["Hugo Granados Jimenez"]["partidos"]) == 1
    assert resultados["Hugo Granados Jimenez"]["partidos"][0]["jugado"] is False

    assert len(resultados["Jugador Que No Juega Este Grupo"]["partidos"]) == 0

    print("✅ procesar_grupo() asigna correctamente rival, resultado y estado 'jugado'")


if __name__ == "__main__":
    test_categoria_y_partidos()
    test_deteccion_de_jugador_con_acentos()
    test_procesar_grupo_completo()
    print("\n🎉 Todos los tests pasan. La lógica de extracción funciona correctamente.")
