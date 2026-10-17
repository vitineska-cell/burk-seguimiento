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


class IdentidadesOficiales:
    """Relaciona alias únicamente cuando la fuente los vincula al mismo ID."""
    def __init__(self, partidos=(), anteriores=None):
        self.alias = {nombre: set(ids) for nombre, ids in (anteriores or {}).items()}
        for partido in partidos:
            for nombre, identificador in partido.get('referencias_jugadores', []):
                self.alias.setdefault(normalizar(nombre), set()).add(str(identificador))

    def persona(self, nombre):
        valor = normalizar(nombre)
        ids = self.alias.get(valor, set())
        if not ids:
            tokens = valor.split()
            if len(tokens) < 2:
                return None
            for alias, candidatos in self.alias.items():
                partes = alias.split()
                corto, largo = sorted((tokens, partes), key=len)
                restantes = iter(largo)
                if corto[0] == largo[0] and all(any(t == x for x in restantes) for t in corto):
                    ids = ids | candidatos
        return next(iter(ids)) if len(ids) == 1 else None

    def equipo(self, texto):
        miembros = [self.persona(n.strip()) for n in texto.split('/') if n.strip()]
        return tuple(sorted(miembros)) if miembros and all(miembros) else None
