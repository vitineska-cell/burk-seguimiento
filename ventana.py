#!/usr/bin/env python3
"""Controla cuándo debe ejecutarse la actualización automática del torneo."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).parent / "jugadores.json"


def _limites(torneo: dict[str, Any]) -> tuple[datetime, datetime]:
    desde = datetime.fromisoformat(torneo["actualizacion_desde"])
    hasta = datetime.fromisoformat(torneo["actualizacion_hasta"])
    if desde.tzinfo is None or hasta.tzinfo is None:
        raise ValueError("Las fechas de actualización deben incluir zona horaria")
    if hasta < desde:
        raise ValueError("actualizacion_hasta no puede ser anterior a actualizacion_desde")
    return desde, hasta


def _torneos(config: dict[str, Any]) -> list[dict[str, Any]]:
    torneos = config.get("torneos")
    if torneos is None:
        return [config]
    if not isinstance(torneos, list) or not torneos:
        raise ValueError("'torneos' debe contener al menos un torneo")
    return torneos


def torneo_activo(
    config: dict[str, Any], ahora: datetime | None = None
) -> dict[str, Any] | None:
    instante = ahora or datetime.now(timezone.utc)
    if instante.tzinfo is None:
        raise ValueError("La hora de comprobación debe incluir zona horaria")
    activos = []
    for torneo in _torneos(config):
        desde, hasta = _limites(torneo)
        if desde <= instante <= hasta:
            activos.append(torneo)
    if len(activos) > 1:
        raise ValueError("Hay varias ventanas de torneo solapadas")
    return activos[0] if activos else None


def dentro_de_ventana(config: dict[str, Any], ahora: datetime | None = None) -> bool:
    return torneo_activo(config, ahora) is not None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    with CONFIG_PATH.open(encoding="utf-8") as archivo:
        config = json.load(archivo)
    torneo = torneo_activo(config)
    activo = "true" if torneo else "false"
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as salida:
            salida.write(f"activo={activo}\n")
            if torneo:
                salida.write(f"torneo_id={int(torneo['torneo_id'])}\n")
                salida.write(f"torneo_nombre={torneo.get('torneo_nombre', '')}\n")
    else:
        print(activo)


if __name__ == "__main__":
    main()
