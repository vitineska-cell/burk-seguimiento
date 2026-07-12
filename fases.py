from __future__ import annotations

from scraper import normalizar


def detectar_fase(texto: str) -> str:
    """Detecta la ronda evitando confundir 'cuartos de final' con la final."""
    valor = normalizar(texto)
    if "semifinal" in valor or "semi final" in valor:
        return "semifinal"
    if "cuartos" in valor or "1 4" in valor:
        return "cuartos"
    if "octavos" in valor or "1 8" in valor:
        return "octavos"
    if "dieciseisavos" in valor or "1 16" in valor:
        return "dieciseisavos"
    if "final" in valor:
        return "final"
    return "grupos"
