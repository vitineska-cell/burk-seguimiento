#!/usr/bin/env python3
"""Resume las fuentes guardadas por el extractor, sin navegador ni nuevas peticiones."""
import json
from pathlib import Path
from bs4 import BeautifulSoup
from scraper import extraer_todas_las_tablas_partidos, extraer_partidos_cuadro, extraer_partidos_orden_juego

def main():
    root = Path(__file__).parent / 'debug'
    root.mkdir(exist_ok=True)
    resumen = []
    for file in sorted(root.glob('*.html')):
        html = file.read_text(encoding='utf-8')
        url = file.with_suffix('.url')
        resumen.append({'archivo': file.name, 'url': url.read_text() if url.exists() else '',
                        'grupos': len(extraer_todas_las_tablas_partidos(html)),
                        'cuadros': len(extraer_partidos_cuadro(html)),
                        'orden_juego': len(extraer_partidos_orden_juego(html))})
    (root / 'diagnostico_fuentes.json').write_text(json.dumps(resumen, ensure_ascii=False, indent=2))
    print(f'Diagnóstico disponible: {len(resumen)} fuentes guardadas.')

if __name__ == '__main__':
    main()
