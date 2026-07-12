import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ventana import dentro_de_ventana


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


if __name__ == "__main__":
    test_ventana_automatica_del_torneo()
    test_rechaza_fechas_sin_zona_horaria()
    print("OK: ventana automática del torneo")
