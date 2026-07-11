#!/usr/bin/env python3
"""Punto de entrada del seguimiento BÜRK con cuadros y logros."""

import scraper
from matching import jugador_en_texto_flexible
from seguimiento import incorporar_partidos_mejorado

# Los módulos de extracción consultan estas funciones en tiempo de ejecución.
scraper.jugador_en_texto = jugador_en_texto_flexible
scraper.incorporar_partidos = incorporar_partidos_mejorado

from scraper_runner_v2 import main  # noqa: E402


if __name__ == "__main__":
    main()
