# Seguimiento BÜRK · Pickle Pro Tour

Panel para ver de un vistazo los partidos de los jugadores patrocinados por
BÜRK en cada torneo del Pickle Pro Tour: fase de grupos, cuadro eliminatorio,
logros, resultados, próximo partido (día, hora o estado, pista y rival) y
enlace directo a la información oficial.

---

## 🚀 Puesta en marcha (solo la primera vez)

### 1. Crear el repositorio

1. Entra en [github.com/new](https://github.com/new)
2. Nombre del repositorio: `burk-seguimiento` (o el que prefieras)
3. Marca la opción **Public** (necesario para que GitHub Pages sea gratis)
4. Pulsa **Create repository**

### 2. Subir estos ficheros

1. En la página del repositorio recién creado, pulsa **uploading an existing file**
2. Arrastra **todos** los ficheros y carpetas de este proyecto (manteniendo la
   estructura de carpetas: `.github/`, `docs/`, `tests/`, etc.)
3. Pulsa **Commit changes**

### 3. Activar GitHub Pages (el panel visual)

1. En el repositorio, ve a **Settings → Pages**
2. En "Branch", selecciona `main` y la carpeta `/docs`
3. Pulsa **Save**
4. Espera 1-2 minutos. Tu panel estará en algo como:
   `https://tu-usuario.github.io/burk-seguimiento/`
   (GitHub te muestra la URL exacta en esa misma pantalla)

### 4. Ejecutar el scraper por primera vez

1. Ve a la pestaña **Actions** del repositorio
2. Si aparece un aviso pidiendo habilitar Actions, acéptalo
3. Click en **Actualizar resultados BÜRK** (en la lista de la izquierda)
4. Click en el botón **Run workflow** → **Run workflow** (botón verde)
5. Espera 1-2 minutos y refresca la página del panel (paso 3)

---

## 🔁 Uso normal cada torneo

**Antes del torneo:**
Edita `jugadores.json` directamente en GitHub (ábrelo, pulsa el icono del
lápiz ✏️, cambia `torneo_id` por el del nuevo torneo y revisa la lista de
jugadores). El ID del torneo está en su URL:
`pickleprotour.com/torneo.aspx?id=XXXX` ← ese número.

**Durante el fin de semana:**
Dentro de las fechas `actualizacion_desde` y `actualizacion_hasta`, GitHub
comprueba los resultados cada 10 minutos. Fuera de esa ventana termina sin
consultar Pickle Pro Tour. También puedes forzar una actualización desde
**Actions → Actualizar resultados BÜRK → Run workflow**. El panel comprueba
cada 60 segundos si hay nuevos datos publicados.

---

## 🗂️ Qué hace cada fichero

| Fichero | Para qué sirve |
|---|---|
| `jugadores.json` | **El único que edita Víctor.** Torneo activo + lista de jugadores BÜRK. |
| `scraper.py` | Lee grupos, cuadros eliminatorios y orden de juego en pickleprotour.com. |
| `docs/index.html` | El panel visual (lo que ves en el navegador). |
| `docs/resultados.json` | Los datos que genera el scraper; los lee `index.html`. |
| `.github/workflows/actualizar.yml` | Define el botón "Run workflow". |
| `tests/` | Pruebas internas del código, no hace falta tocarlas. |
| `vista_previa.html` | Ejemplo visual con datos ficticios (no forma parte del panel real). |

---

## ⚠️ Si algo falla

El paso más delicado es cuando el scraper busca los grupos del torneo (esa
parte de la web usa JavaScript y no se pudo probar en directo antes de
lanzarlo). Si el **Run workflow** falla o el panel se queda vacío tras
ejecutarlo:

1. Ve a **Actions**, entra en la ejecución que falló (aparecerá con una ❌)
2. Copia el texto del log (botón de copiar o selecciona todo)
3. Pégaselo a Claude en la conversación — con eso se ajusta el scraper en
   minutos, sin que tengas que entender el código.

---

## 🔮 Próximos pasos posibles

- **Bot de Telegram**: aviso automático al grupo del equipo cuando un
  jugador BÜRK termina un partido.
- **Actualización automática** cada 15 min los findes de torneo (hoy es
  manual, a propósito, tal y como se pidió).

No construidos todavía — se añaden cuando el panel esté validado con datos
reales del primer torneo.
