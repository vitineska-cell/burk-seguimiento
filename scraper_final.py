#!/usr/bin/env python3
"""Punto de entrada definitivo del seguimiento BÜRK."""

import scraper
from matching import jugador_en_texto_flexible

# incorporar_partidos() consulta esta función en el módulo scraper en tiempo de ejecución.
scraper.jugador_en_texto = jugador_en_texto_flexible

from scraper_runner import main  # noqa: E402


if __name__ == "__main__":
    main()
