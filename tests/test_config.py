import json
from pathlib import Path


ROOT = Path(__file__).parent.parent


def cargar_config():
    return json.loads((ROOT / "jugadores.json").read_text(encoding="utf-8"))


def test_torneo_principal_coincide_con_un_torneo_programado():
    config = cargar_config()
    principal = {
        clave: config[clave]
        for clave in (
            "torneo_id",
            "torneo_nombre",
            "actualizacion_desde",
            "actualizacion_hasta",
        )
    }
    assert principal in config["torneos"]


def test_jugadores_validos_y_sin_duplicados():
    jugadores = cargar_config()["jugadores"]
    assert jugadores
    assert all(isinstance(nombre, str) and len(nombre.split()) >= 2 for nombre in jugadores)
    assert len(jugadores) == len(set(jugadores))


if __name__ == "__main__":
    test_torneo_principal_coincide_con_un_torneo_programado()
    test_jugadores_validos_y_sin_duplicados()
    print("OK: configuración de torneo y jugadores")
