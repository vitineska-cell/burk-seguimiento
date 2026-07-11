"""Reglas de comparación entre nombres BÜRK y nombres abreviados del torneo."""

from __future__ import annotations

import re

from scraper import normalizar


def jugador_en_texto_flexible(nombre_jugador: str, texto_pareja: str) -> bool:
    """Compara el nombre completo con los prefijos usados en Pickle Pro Tour.

    La plataforma suele omitir el último apellido: por ejemplo, muestra
    "Lucas Corral" para "Lucas Corral Falagan". Se prueba primero el nombre
    completo y después prefijos de al menos dos palabras, del más largo al
    más corto. Nunca se acepta únicamente el nombre de pila.
    """
    nombre = normalizar(nombre_jugador)
    texto = normalizar(texto_pareja)
    if not nombre or not texto:
        return False

    if re.search(rf"(?<![a-z0-9]){re.escape(nombre)}(?![a-z0-9])", texto):
        return True

    tokens = nombre.split()
    for longitud in range(len(tokens) - 1, 1, -1):
        prefijo = " ".join(tokens[:longitud])
        if re.search(rf"(?<![a-z0-9]){re.escape(prefijo)}(?![a-z0-9])", texto):
            return True

    return False
