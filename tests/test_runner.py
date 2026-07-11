import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper_runner import listado_cuadros_cargado


def test_placeholder_no_se_considera_cargado():
    html = """
    <div class="tab-lazy-content" data-panel="cuadros" data-id="2339" data-loaded="1">
      <div class="tab-loading-placeholder">Cargando...</div>
    </div>
    """
    assert listado_cuadros_cargado(html) is False


def test_listado_con_categoria_y_url_se_considera_cargado():
    html = """
    <div class="tab-lazy-content" data-panel="cuadros" data-id="2339" data-loaded="1">
      <div id="cuadros-todos">
        <div class="cuadros-categoria-block">
          <div class="cuadros-categoria-header">
            <a onclick="abrirCuadroVisor('torneogrupo.aspx?idT=2339&amp;g=908&amp;visor=0', 'Categoría')">
              Categoría
            </a>
          </div>
        </div>
      </div>
    </div>
    """
    assert listado_cuadros_cargado(html) is True


if __name__ == "__main__":
    test_placeholder_no_se_considera_cargado()
    test_listado_con_categoria_y_url_se_considera_cargado()
    print("Todos los tests del ejecutor v6 pasan.")
