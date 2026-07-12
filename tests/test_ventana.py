import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ventana import dentro_de_ventana, torneo_activo


def test_ventana_automatica_del_torneo():
    config = {
        "actualizacion_desde": "2026-07-12T00:00:00+02:00",
        "actualizacion_hasta": "2026-07-12T23:59:59+02:00",
    }
    assert dentro_de_ventana(config, datetime(2026, 7, 11, 21, 59, tzinfo=timezone.utc)) is False
    assert dentro_de_ventana(config, datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)) is True
    assert dentro_de_ventana(config, datetime(2026, 7, 12, 22, 0, tzinfo=timezone.utc)) is False


def test_rechaza_fechas_sin_zona_horaria():
    config = {
        "actualizacion_desde": "2026-07-12T00:00:00",
        "actualizacion_hasta": "2026-07-12T23:59:59",
    }
    try:
        dentro_de_ventana(config)
    except ValueError as exc:
        assert "zona horaria" in str(exc)
    else:
        raise AssertionError("Debía rechazar fechas sin zona horaria")


def test_selecciona_el_torneo_de_cada_ventana():
    config = {
        "torneos": [
            {
                "torneo_id": 2339,
                "torneo_nombre": "A Coruña Open",
                "actualizacion_desde": "2026-07-12T00:00:00+02:00",
                "actualizacion_hasta": "2026-07-12T23:59:59+02:00",
            },
            {
                "torneo_id": 2340,
                "torneo_nombre": "Mijas-Costa del Sol Open",
                "actualizacion_desde": "2026-09-11T00:00:00+02:00",
                "actualizacion_hasta": "2026-09-13T23:59:59+02:00",
            },
        ]
    }
    coruna = torneo_activo(config, datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc))
    descanso = torneo_activo(config, datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc))
    mijas = torneo_activo(config, datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc))

    assert coruna and coruna["torneo_id"] == 2339
    assert descanso is None
    assert mijas and mijas["torneo_id"] == 2340


def test_rechaza_ventanas_solapadas():
    torneo = {
        "torneo_id": 1,
        "actualizacion_desde": "2026-09-11T00:00:00+02:00",
        "actualizacion_hasta": "2026-09-13T23:59:59+02:00",
    }
    config = {"torneos": [torneo, {**torneo, "torneo_id": 2}]}
    try:
        torneo_activo(config, datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc))
    except ValueError as exc:
        assert "solapadas" in str(exc)
    else:
        raise AssertionError("Debía rechazar ventanas solapadas")


if __name__ == "__main__":
    test_ventana_automatica_del_torneo()
    test_rechaza_fechas_sin_zona_horaria()
    test_selecciona_el_torneo_de_cada_ventana()
    test_rechaza_ventanas_solapadas()
    print("OK: ventana automática del torneo")
