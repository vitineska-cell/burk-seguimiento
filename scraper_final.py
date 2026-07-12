#!/usr/bin/env python3
"""Punto de entrada definitivo del seguimiento BÜRK."""

import scraper
from matching import jugador_en_texto_flexible
from fases import detectar_fase

# El parser consulta estas funciones en tiempo de ejecución.
scraper.jugador_en_texto = jugador_en_texto_flexible

import scraper_runner  # noqa: E402
scraper_runner.jugador_en_texto = jugador_en_texto_flexible
scraper_runner.detectar_fase = detectar_fase


if __name__ == "__main__":
    scraper_runner.main()
