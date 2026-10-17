import copy
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import scraper_runner as r
from matching import IdentidadesOficiales
from scraper import extraer_partidos_cuadro, extraer_partidos_orden_juego, extraer_todas_las_tablas_partidos

ROOT = Path(__file__).parent
NOMBRE = 'Bárbara Molina Durán'
CAT = '+50 PRO Double FEMENINO'

def fuentes():
    return (extraer_todas_las_tablas_partidos((ROOT / 'fixture_barbara_grupos.html').read_text()),
            extraer_partidos_cuadro((ROOT / 'fixture_barbara_cuadro.html').read_text()),
            extraer_partidos_orden_juego((ROOT / 'fixture_barbara_orden.html').read_text()))

def test_regresion_real_barbara_alias_y_resultados_completos():
    grupos, cuadro, orden = fuentes()
    identidades = IdentidadesOficiales(orden)
    assert identidades.persona('Mercedes Cascales') == identidades.persona('Merche Cascales Campos') == '99000337'
    datos = {NOMBRE: {'partidos': []}}
    incidencias, firmas = [], set()
    for partidos, url in [(grupos, 'grupos'), (cuadro, 'cuadro'), (orden, 'orden')]:
        r.incorporar_partidos_enriquecidos(partidos, [NOMBRE], datos, firmas, url, CAT if url != 'orden' else 'Orden de juego', incidencias, identidades)
    matches = datos[NOMBRE]['partidos']
    assert len(matches) == 4
    assert not incidencias
    assert all(p['jugado'] for p in matches)
    assert sum(p['ganado'] for p in matches) == 2
    assert next(p for p in matches if 'Gabriela' in p['rival'])['resultado'] == '21-7'
    semifinal = next(p for p in matches if p['fase'] == 'semifinal')
    assert semifinal['resultado'] == '12-21 / 10-21'
    assert semifinal['id_partido'] == '116725'
    assert r.calcular_logros(matches) == [{'titulo': 'Semifinalista', 'categoria': CAT}]

def test_ids_distintos_no_se_unen_por_nombres_parecidos():
    ids = IdentidadesOficiales([{'referencias_jugadores': [['Ana Perez', '1'], ['Ana Perez Gomez', '2']]}])
    assert not r._equipos_coinciden('Ana Perez', 'Ana Perez Gomez', ids)
    ambiguo = IdentidadesOficiales([{'referencias_jugadores': [['Ana Perez', '1'], ['Ana Perez', '2']]}])
    assert ambiguo.persona('Ana Perez') is None

def test_partido_desconocido_no_bloquea_el_siguiente():
    datos = {NOMBRE: {'partidos': []}}
    incidencias = []
    partidos = [{'categoria': 'Grupos · CATEGORIA Categoría', 'pareja1': NOMBRE,
                 'pareja2': 'Rival Nueva', 'resultado': '21-10'},
                {'categoria': CAT, 'pareja1': NOMBRE, 'pareja2': 'Rival Conocida', 'resultado': '21-9'}]
    r.incorporar_partidos_enriquecidos(partidos, [NOMBRE], datos, set(), 'oficial', 'Orden de juego', incidencias)
    assert len(incidencias) == 1
    assert len(datos[NOMBRE]['partidos']) == 1
    assert datos[NOMBRE]['partidos'][0]['resultado'] == '21-9'

def test_pendiente_no_borra_resultado_y_correccion_oficial_si():
    original = {'resultado': '21-7', 'jugado': True, 'ganado': True}
    r._fusionar_registro(original, {'resultado': 'sin resultado', 'jugado': False, 'ganado': None,
                                   'estado_programacion': 'Comienza a las 20:45'})
    assert original['resultado'] == '21-7' and original['ganado']
    r._fusionar_registro(original, {'resultado': '20-22', 'jugado': True, 'ganado': False})
    assert original['resultado'] == '20-22' and original['ganado'] is False

def test_resultados_previos_se_conservan_ante_fuente_incompleta():
    partido = {'categoria': CAT, 'fase': 'grupos', 'equipo': NOMBRE, 'rival': 'Anna Castells',
               'resultado': '21-7', 'jugado': True, 'ganado': True, 'url_grupo': 'oficial'}
    anterior = {'torneo_id': 2341, 'jugadores': {NOMBRE: {'partidos': [partido]}}}
    nuevos = {NOMBRE: {'partidos': []}}
    avisos = []
    r.conservar_resultados_confirmados(anterior, nuevos, 2341, avisos)
    assert nuevos[NOMBRE]['partidos'][0]['resultado'] == '21-7'
    assert nuevos[NOMBRE]['partidos'][0]['pendiente_verificacion']
    assert avisos[0]['tipo'] == 'resultado_conservado'
    otro = {NOMBRE: {'partidos': []}}
    r.conservar_resultados_confirmados(anterior, otro, 999, [])
    assert not otro[NOMBRE]['partidos']

def test_marcador_en_juego_no_cuenta_como_victoria():
    html = (ROOT / 'fixture_barbara_orden.html').read_text().replace('Partido finalizado', 'En juego')
    partidos = extraer_partidos_orden_juego(html)
    assert partidos and all(not p['jugado'] for p in partidos)
    datos = {NOMBRE: {'partidos': []}}
    for partido in partidos:
        partido['categoria'] = 'Grupos · CATEGORIA ' + CAT
    r.incorporar_partidos_enriquecidos(partidos, [NOMBRE], datos, set(), 'orden', CAT)
    assert all(p['ganado'] is None for p in datos[NOMBRE]['partidos'])
    assert not r.calcular_logros(datos[NOMBRE]['partidos'])

def test_fallo_total_publica_aviso_sin_borrar_datos():
    with tempfile.TemporaryDirectory() as temp:
        status, output = Path(temp)/'estado.json', Path(temp)/'resultados.json'
        output.write_text('{"torneo_id":2341,"jugadores":{}}')
        original = output.read_bytes()
        with patch.object(r, 'STATUS_PATH', status), patch.object(r, 'OUTPUT_PATH', output), patch.object(r, 'main', side_effect=RuntimeError('fuente temporalmente caída')):
            try:r.ejecutar()
            except RuntimeError:pass
            else:raise AssertionError('El fallo total debe constar en Actions')
        assert output.read_bytes() == original
        assert json.loads(status.read_text())['estado'] == 'error'

def test_ciclo_completo_y_sin_cambios_actualiza_solo_comprobacion():
    base='https://pickleprotour.com'
    categoria=base+'/torneogrupo.aspx?idT=2341&g=1004&visor=0'
    cuadro=base+'/torneoCuadro.aspx?id=22445&visor=0'
    orden=base+'/ordenJuego.aspx?id_torneo=2341&f=16-10-2026&visor=0'
    paginas={base+'/torneo.aspx?id=2341':'<title>Barcelona Open 2026</title>',
             base+'/torneo_panel.ashx?panel=cuadros&id=2341':f'''<div id="cuadros-todos"><div class="cuadros-categoria-block"><div class="cuadros-categoria-header"><a onclick="abrirCuadroVisor('{categoria}', 'Categoria')">{CAT}</a></div><a onclick="abrirCuadroVisor('{cuadro}', 'Cuadro')">Cuadro</a></div></div>''',
             categoria:(ROOT/'fixture_barbara_grupos.html').read_text(), cuadro:(ROOT/'fixture_barbara_cuadro.html').read_text(),
             base+'/torneo_panel.ashx?panel=ordenjuego&id=2341':f'''<a onclick="abrirOJVisor('{orden}', 'Viernes')">Viernes</a>''',
             orden:(ROOT/'fixture_barbara_orden.html').read_text()}
    def descargar(urls): return {u:paginas[u] for u in urls}, {}
    with tempfile.TemporaryDirectory() as temp:
        status, output = Path(temp)/'estado.json', Path(temp)/'resultados.json'
        with patch.object(r,'STATUS_PATH',status), patch.object(r,'OUTPUT_PATH',output), patch.object(r,'guardar_debug'), patch.object(r,'cargar_config',return_value={'torneo_id':2341,'jugadores':[NOMBRE]}), patch.object(r,'cargar_url',side_effect=paginas.__getitem__), patch.object(r,'cargar_urls_en_paralelo',side_effect=descargar):
            r.ejecutar()
            primero=output.read_bytes()
            estado=json.loads(status.read_text())
            assert estado['estado']=='ok'
            assert json.loads(primero)['jugadores'][NOMBRE]['resumen']['jugados']==4
            r.ejecutar()
            assert output.read_bytes()==primero
            assert json.loads(status.read_text())['comprobado'] >= estado['comprobado']
            paginas.pop(orden)
            r.ejecutar()
            assert json.loads(status.read_text())['estado']=='parcial'
            assert json.loads(output.read_text())['jugadores'][NOMBRE]['resumen']['jugados']==4

def test_alias_oficial_aprendido_se_conserva_entre_ciclos():
    anteriores={'mercedes cascales':['99000337'], 'merche cascales campos':['99000337']}
    actual=IdentidadesOficiales([{'referencias_jugadores':[['Merche Cascales Campos','99000337']]}],anteriores)
    assert actual.persona('Mercedes Cascales') == actual.persona('Merche Cascales Campos')
