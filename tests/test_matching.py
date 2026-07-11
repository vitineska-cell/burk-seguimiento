import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from matching import jugador_en_texto_flexible


def test_nombres_abreviados_reales_del_torneo():
    casos = [
        ("Oscar Villar Sancosmed", "Oscar Villar"),
        ("Hugo Granados Jimenez", "Hugo Granados"),
        ("Lucas Corral Falagan", "Lucas Corral / Victor Sebastian"),
        ("Jose Manuel Granados Sánchez", "Jose Manuel Granados"),
        ("Brenda Fariña Solís", "Brenda Fariña"),
        ("Victor Sebastian Davila", "Lucas Corral / Victor Sebastian"),
        ("Laura Davila Alcala", "Laura Davila"),
        ("Bárbara Molina Durán", "Bárbara Molina"),
    ]
    for completo, abreviado in casos:
        assert jugador_en_texto_flexible(completo, abreviado)


def test_no_acepta_solo_nombre_de_pila_ni_otro_granados():
    assert not jugador_en_texto_flexible("Hugo Granados Jimenez", "Hugo")
    assert not jugador_en_texto_flexible(
        "Hugo Granados Jimenez", "Jose Manuel Granados / Rival"
    )
    assert not jugador_en_texto_flexible(
        "Laura Davila Alcala", "Victor Sebastian / Lucas Corral"
    )


if __name__ == "__main__":
    test_nombres_abreviados_reales_del_torneo()
    test_no_acepta_solo_nombre_de_pila_ni_otro_granados()
    print("Todos los tests de nombres abreviados pasan.")
