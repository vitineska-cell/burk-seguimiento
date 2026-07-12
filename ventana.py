#!/usr/bin/env python3
"""Controla cuándo debe ejecutarse la actualización automática del torneo."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).parent / "jugadores.json"


def dentro_de_ventana(config: dict[str, Any], ahora: datetime | None = None) -> bool:
    desde = datetime.fromisoformat(config["actualizacion_desde"])
    hasta = datetime.fromisoformat(config["actualizacion_hasta"])
    if desde.tzinfo is None or hasta.tzinfo is None:
        raise ValueError("Las fechas de actualización deben incluir zona horaria")
    if hasta < desde:
        raise ValueError("actualizacion_hasta no puede ser anterior a actualizacion_desde")
    instante = ahora or datetime.now(timezone.utc)
    if instante.tzinfo is None:
        raise ValueError("La hora de comprobación debe incluir zona horaria")
    return desde <= instante <= hasta


def main() -> None:
    with CONFIG_PATH.open(encoding="utf-8") as archivo:
        config = json.load(archivo)
    print("true" if dentro_de_ventana(config) else "false")


if __name__ == "__main__":
    main()
