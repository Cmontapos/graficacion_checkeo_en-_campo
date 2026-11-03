# Cambios

## 2026-11-02 · Abrir Excel (.xlsx)
- **Qué:** la 2.0 y la versión 1 abren `.xlsx` y `.xlsm` además de CSV. Se usa la hoja `Datos` si existe (la que exporta GasLab) o la hoja con más datos. Un `.xls` antiguo da un mensaje pidiendo guardarlo como `.xlsx` o `.csv`. El botón ahora dice **Abrir archivo…**.
- **Dónde:** `graficar.py` → `read_excel()` y `EXCEL_SUFFIXES`; `load_csv()` decide por la extensión y lo común pasó a `_prepare()`. `requirements.txt` → `openpyxl`. `GasLab.spec` → `openpyxl` en `hiddenimports`, porque pandas lo importa de forma dinámica y PyInstaller no lo ve. `web/index.html` → textos y `accept`.
- **Selector de hoja:** si el libro tiene más de una hoja con datos, aparece **Hoja: …** junto al nombre del archivo. Empieza en la hoja de siempre, y al cambiarla la página vuelve a enviar el archivo con el encabezado `X-Sheet` y lo abre como un archivo nuevo. Si esa hoja no se puede abrir (por ejemplo, porque no tiene columna de tiempo), se avisa y sigue abierta la anterior. Código: `read_excel(sheet=)` devuelve también la hoja usada y la lista de hojas, `load_csv(sheet=)` las deja en `frame.attrs` e `info()` las manda como `sheet` y `sheets`. En la página: `showSheets()` y `fileText()`.
- **Ojo:** en los libros que exporta GasLab, la columna `Fecha y hora (zona)` está en hora local. Se vuelve a pasar a UTC como `fecha_hora_utc` y se quita `Transcurrido (s)`. Las fechas de Excel sin zona se toman como UTC, igual que en el CSV. Tests: `test_excel_*` y `test_old_xls_gives_a_clear_error`.

## 2026-11-02 · Tabletas: pellizcar en las gráficas y tocar para ver el valor
- **Qué:** en las gráficas, pellizcar con dos dedos acerca o aleja alrededor de los dedos; las demás gráficas siguen igual que con la rueda. En el mapa de calor y el terreno 3D, tocar una muestra muestra su valor. Con mouse no cambia nada.
- **Dónde:** `web/app.js` → `pinchZoom(div, axes)`, que se usa en `wire()`, en la gráfica grande del paso 2 y en la ruta (con los ejes x e y). `showValue` en `createHeatMap()` y `createTerrainMap()` atiende `mousemove` y también `click`, que es como llega un toque.
- **Ojo:**
  - El segundo dedo no llega a Plotly (`stopPropagation` en captura). Si llegara, Plotly lo contaría como doble toque y reiniciaría la vista.
  - Al soltar se reaplica el rango del pellizco, porque Plotly cierra ahí el arrastre del primer dedo y podría volver al rango anterior.
  - `preventDefault` evita que el navegador agrande toda la página.
  - Se probó con Brave headless y toques simulados por CDP: separar los dedos 5× acercó 5×, la otra gráfica siguió y la página no se agrandó.

## 2026-11-02 · GasLab 2.0 como app de Windows
- **Qué:** `GasLab.exe` ahora es la 2.0: sin consola, abre su propia ventana (Edge o Chrome con `--app`) y se cierra sola al cerrarla. Sin Edge ni Chrome abre una pestaña del navegador predeterminado. `iniciar.bat` hace lo mismo desde el código. La versión 1 sale del ejecutable (sigue en `graficar.py`).
- **Dónde:** `GasLab.spec` (entrada `gaslab_web.py`, empaqueta `web/`, sin PyQt/pyqtgraph/folium/tkinter). `gaslab_web.py` → opción `--ventana` (activa en el `.exe`), `open_window()`, `app_browser()`, `Pages`, `close_when_unused()`, `/api/ping` y `/api/bye`. `web/app.js` avisa cada 30 s y se despide con `sendBeacon` en `pagehide`. `build_windows.bat` comprueba que se empaquetó `web/`, y el workflow corre también `test_gaslab_web.py`.
- **Ojo:**
  - Se apaga 5 s después de que se despide la última página (una recarga vuelve a avisar antes).
  - Una página que deja de avisar sin despedirse cuenta como cerrada a los 10 min, porque las ventanas en segundo plano solo avisan una vez por minuto.
  - Si ninguna página abre en 2 min, también se apaga, para no dejar un proceso invisible.
  - Se probó un build de PyInstaller en Linux (página, carga de CSV, zip de QGIS, cierre automático). El `.exe` en sí no se probó todavía en Windows.
  - Test: `test_pages_close_after_last_window_but_not_on_reload`.
- **Icono:** el átomo y la G del logo GasLAB de las placas (`PCBs GasLAB/Power Corrected/Logo.pretty/GasLAB.kicad_mod`), en azul oscuro sobre un cuadro blanco redondeado. Está en `gaslab.ico` (para el `.exe`) y en `web/icono.png` (favicon). En modo app, Edge usa el favicon como icono de la ventana y de la barra de tareas. El logo completo no se usó porque a 16–32 px no se lee.

## 2026-10-30 · Mapa de calor: alcance de la nube ajustable
- **Qué:** control **Alcance** (1–4 veces el Tamaño, 2,5 por defecto, con ⓘ y su equivalente en metros) en la fila Nube: hasta dónde se pinta cada muestra. Antes estaba fijo en ~2,5 veces el Tamaño. El núcleo y el enfriamiento siguen dependiendo del Tamaño; el alcance solo estira el borde que se desvanece.
- **Dónde:** `mapa_calor.py` → `cloud(reach=)` y `export_cloud(reach=)`, `CLOUD_REACH` y `CLOUD_MAX_REACH` (reemplazan a `CLOUD_CUT`). La transparencia usa la distancia equivalente escalada por `CLOUD_REACH / reach`, así que con 2,5 se ve igual que antes. `gaslab_web.py` → parámetro `reach` de `/api/heat/image` y `/api/heat.zip`. `web/app.js` → `heatQuery()`, `showOutputs()` e `INFO.reach`.
- **Ojo:** el máximo es 4 porque a esa distancia la densidad es ~3·10⁻⁴ del centro y el promedio ponderado de valores ya se vuelve inestable. Test: `test_cloud_reach_sets_how_far_it_is_painted`.

## 2026-10-30 · Mapa de calor: enfriamiento hacia los lados
- **Qué:** control **Enfriamiento** (0–5, 1 por defecto, con ⓘ) en la fila Nube. Cada muestra conserva su valor medido en el centro y, hacia los lados, su valor baja hacia el mínimo de la escala, así que el color pasa por las divisiones hasta azul. El control define la rapidez; con 0, la nube se ve como antes (mismo color y solo se desvanece).
- **Dónde:** `mapa_calor.py` → `cloud(cool=)` y `export_cloud(cool=)`: valor = mínimo + (valor − mínimo) · densidad^cool, con la densidad limitada a 1 (donde hay muestras seguidas no se enfría). `gaslab_web.py` → `heat_image()` y `heat_zip()`, parámetro `cool` de `/api/heat/image` y `/api/heat.zip`. `web/app.js` → `heatQuery()`, `showOutputs()` e `INFO.cool`.
- **Ojo:** el `_valores.tif` exportado lleva también el valor enfriado, para que coincida con los colores. Test: `test_cloud_cools_toward_the_sides`.

## 2026-10-30 · GasLab 2.0, paso 4: terreno 3D
- **Qué:** pestaña **4 · Terreno 3D**: relieve real (AWS Terrain Tiles) con Esri satélite, y cada muestra como un cubo pequeño a la altura que midió el GPS, con el color de su división (misma señal y escala del paso 3). Escala real, sin exagerar. Al pasar el mouse se ven el valor, la altura medida, la del terreno y la altura sobre el terreno. Un aviso indica la columna de altura usada y cuántas muestras quedaban bajo el relieve; esas se dibujan sobre el suelo. Sin opción de guardar, como se pidió.
- **Dónde:** `terreno.py` (nuevo: `elevation()` con interpolación bilineal y caché en `~/.cache/gaslab_tiles/terrarium`); `gaslab_web.py` → `Dataset.terrain()` y `/api/terrain`; `heat_samples()` devuelve también la altura. `web/app.js` → `enterTerrain()`, `createTerrainMap()`, `refreshTerrain()` y `drawPoints3d()`; `fillSignal()` comparte la señal entre los pasos 3 y 4, y `renderHeatTable(data, prefix)` sirve para las dos tablas.
- **Ojo:**
  - Se usa el zoom 13 del relieve porque algunas teselas del 14 vienen vacías (−32768).
  - `fitBounds` con inclinación y relieve deja la cámara en NaN, y MapLibre reajusta la cámara cuando el relieve termina de cargar. Por eso el encuadre se calcula en plano (`cameraForBounds`) y se repite en `idle`.
  - Los cubos se recalculan en cada `zoomend` para medir unos 7 píxeles con cualquier zoom.
  - Tests: `test_terrain_*`, con teselas simuladas (sin internet).

## 2026-10-30 · Mapa de calor: nube de 0,1–2 m, paleta intensa y ayudas ⓘ
- **Qué:** el tamaño de la nube va de 0,1 a 2 m (1 m por defecto) y la opacidad es del 95 % por defecto. La paleta es más intensa (`INTENSE_RAMP`, colores puros) y el centro de cada muestra es más opaco; se usa en la nube, la tabla, la leyenda, las barras 3D y QGIS. **Divisiones iniciales** y **% mínimo por división** quedan separados, cada uno con su botón ⓘ y una ventanita de explicación (se cierra con ✕, Esc o clic fuera).
- **Nube por zona visible:** con nubes tan pequeñas, una imagen de toda la ruta se veía pixelada al acercar. Ahora `/api/heat/image` calcula solo la zona visible a la resolución de la pantalla y se pide de nuevo al mover el mapa. Incluye un margen de 3 veces el tamaño de nube, para que las muestras justo fuera de la vista tiñan el borde. `/api/heat` ya no manda imagen: solo la escala, la tabla y las muestras.
- **Dónde:** `mapa_calor.py` → `INTENSE_RAMP`, `cloud(bounds=, res=)`; `gaslab_web.py` → `Dataset.heat_image()`, `MAX_IMAGE_PX`; `web/app.js` → `refreshCloud()`, `INFO` y `closeInfo()`.
- **Ojo:** el GeoTIFF exportado sigue cubriendo toda la ruta (hasta 2500 píxeles de lado), así que en rutas largas su píxel puede ser mayor que la nube; el nombre de la capa indica el tamaño del píxel. El `.qgz` se volvió a validar con PyQGIS.

## 2026-10-30 · GasLab 2.0, paso 3: mapa de calor 2D (nubes) y 3D (barras)
- **Qué:** pestaña **3 · Mapa de calor** para una sola señal (con los valores ajustados en Límites), con toda la configuración arriba y selector 2D/3D sobre Esri satélite.
  - **Escala adaptativa:** N divisiones iguales; las que tienen menos del % mínimo de muestras se unen a su vecina. Tabla de rango, muestras y % por división, recuadro con el rango completo y leyenda en el mapa.
  - **2D:** nube gaussiana por muestra, saturada en el punto, con tamaño (m) y opacidad.
  - **3D:** una barra por muestra, de altura proporcional al valor, con altura máxima y ancho ajustables.
  - **Guardar:** imagen PNG con la leyenda, y un .zip con dos GeoTIFF (nube RGBA y valores), los puntos en GeoJSON y el proyecto .qgz.
- **Dónde:** `mapa_calor.py` → `adaptive_classes()`, `cloud()` (suavizado por FFT, sin scipy), `write_rgba_geotiff()`, `_rgba_pipe()`, `_classes_pipe()` y `export_cloud()`. `write_qgis()` acepta un pipe propio por capa y clases propias para los puntos. `gaslab_web.py` → `Dataset.heat()`, `heat_zip()`, `/api/heat` y `/api/heat.zip`. `web/app.js` → `enterHeat()`, `refreshHeat()`, `drawHeat()`, `drawBars()` y `setHeatView()`. `web/vendor/maplibre-gl.*` (4.7.1).
- **Ojo:** el `.qgz` se validó con PyQGIS: las 5 capas son válidas, en EPSG:3857, y la escala es discreta con las mismas divisiones. El PNG necesita que Esri responda con CORS, y hoy lo hace. Tests: `test_adaptive_classes_*`, `test_cloud_*` y `test_heat_and_qgis_zip`.

## 2026-10-30 · GasLab 2.0: una sola selección de variables para todas las pestañas
- **Qué:** las filas de límites del paso 2 son exactamente las variables marcadas en el paso 1, y al revés: Todas, Típicos (CO₂ · SO₂ · H₂S) o Ninguna en el paso 1 se ven en el paso 2, y + Agregar límite, ✕ o cambiar el Dato en el paso 2 se ven en el paso 1. Sin variables, el paso 2 lo indica. El máximo y el mínimo escritos se recuerdan por variable.
- **Dónde:** `web/app.js` → `setSelected()` y `state.bounds` (reemplaza a `state.limits`); `showStep(1)` vuelve a dibujar la lista y las gráficas.

## 2026-10-28 · GasLab 2.0: botón Todas y movimiento como en la versión anterior
- **Qué:** botón **Todas** en la lista de variables. Las gráficas se desplazan arrastrando y hacen zoom con la rueda (antes, arrastrar dibujaba un recuadro de zoom). Mientras se mueve una gráfica, las demás la siguen en vivo, y el eje Y se ajusta al tramo visible. También aplica a la gráfica del paso 2.
- **Dónde:** `web/app.js` → `dragmode: 'pan'` en `baseLayout()`, `wire()`/`follow()` (evento `plotly_relayouting`), `yRange()`/`yAxis()` y `fetchWindow()`. Se pide al servidor el tramo visible más un ancho a cada lado, para poder desplazar sin huecos mientras llegan los datos con más detalle.

## 2026-10-28 · GasLab 2.0, paso 2: límites (saturación)
- **Qué:** pestañas en la cabecera (**1 · Datos**, **2 · Límites**). En el paso 2, filas `Dato | Máximo | Mínimo`: las muestras fuera del rango quedan en el límite, sin descartarse. Hay una fila por cada variable del paso 1 y un botón **+ Agregar límite**. Un campo vacío significa sin límite. Una gráfica grande con botones por variable, líneas de los límites, conteo de muestras ajustadas, **Comparar con original** y **Pantalla completa** (Esc sale).
- **Dónde:** `gaslab_web.py` → `Dataset.values()`, `parse_limits()`, `series(limits=, original=)` (parámetros `limits` en JSON y `original=1` de `/api/series`); `web/app.js` → `showStep()`, `syncLimitRows()`, `renderLimits()`, `renderPick()`, `refreshBig()`.
- **Ojo:** la reducción mín/máx se calcula sobre los datos originales y luego se ajusta, lo que da el mismo resultado porque recortar no cambia cuál es el mínimo o el máximo de cada grupo. Los límites se pierden al abrir otro CSV. Test: `test_limits_saturate_without_dropping_samples`.

## 2026-10-28 · GasLab 2.0: app en el navegador (rama `develop-2.0`)
- **Qué:** `gaslab_web.py` abre la app en el navegador: elegir el CSV con el administrador de archivos, lista de variables (CO₂, SO₂ y H₂S marcadas por defecto), ruta GPS sin fondo + altura contra la hora a la izquierda, variables contra la hora del día a la derecha, zona horaria (UTC por defecto). Zoom sincronizado, tramo resaltado en la ruta y cursor compartido.
- **Rendimiento:** reducción mín/máx por píxel en el servidor (`minmax()`) y nueva petición del tramo visible al hacer zoom (`/api/series?start=&end=`); la ruta se limita a 20.000 puntos (`/api/route`).
- **Dónde:** `gaslab_web.py` (servidor y API, reutiliza `load_csv`/`parse_time` de `graficar.py`); `web/index.html`, `web/app.css`, `web/app.js`. `iniciar.sh` y `make run` abren ahora la 2.0; `graficar.py` sigue con la v1.
- **Ojo:** las horas se pasan a Plotly como texto "de reloj" (`wall()` en `app.js`): con números, Plotly las corre según la zona horaria del navegador. Tests: `test_gaslab_web.py`. El ejecutable de Windows aún no incluye la 2.0.

## 2026-10-28 · Diagnóstico del empaquetado de Windows
- **Qué:** `build_windows.bat` valida el entorno `.venv` existente y lo recrea si no funciona en esta PC; detecta el Python de Microsoft Store antes de crear el entorno; al terminar comprueba que se haya incluido `python3XX.dll` y mantiene abierta la ventana para mostrar el resultado.
- **Errores guiados:** si falta Python, se detecta Microsoft Store o falta el DLL tras compilar, el script muestra el paso recomendado para corregirlo.
- **Documentación:** `README.md` incluye estos casos y recuerda copiar la carpeta `dist\GasLab\` completa.

## 2026-10-26 · Mapa de calor: modo Puntos y celdas desde 0,5 m
- **Qué:** selector **Puntos / Celdas** en la fila Mapa de calor. **Puntos** (por defecto) dibuja cada muestra en su coordenada con el color de su valor (los altos encima, tamaño en px, valor bajo el cursor). Celdas de **0,5 y 1 m** añadidas. El `.qgz` exportado trae ahora una **capa de puntos** (GeoJSON, renderer graduado de 20 clases, ordenado por valor) además de las celdas; queda encendida la del modo elegido. CLI: `--celdas`, `--tam-punto`.
- **Dónde:** `mapa_calor.py` → `_points_layer()`, `write_qgis(points=…)`, `export(mode=…, point_mm=…)`; `visor_qt.py` → `draw_heat_points()`, `cover_hover()`, `drawbox`/`sizebox`.
- **Ojo:** la XML de la capa vectorial se validó con PyQGIS (capa válida, 20 clases, orden por valor). Celdas más pequeñas que el error del GPS (1–3 m) no añaden detalle real.

## 2026-10-26 · Mapa de calor de una variable, georreferenciado (GeoTIFF + QGIS)
- **Qué:** la casilla **Cobertura** pasó a una fila **Mapa de calor** con **Valor** (Muestras = cobertura de antes, o cualquier variable numérica), **Promedio / Máximo / Percentil 95** por celda, celda de 2 a 250 m, **suavizado** gaussiano recortado a ~2 sigma de la ruta, **desfase** del sensor (s) y **rango válido**. **Exportar GeoTIFF/QGIS…** escribe `.tif` (EPSG:3857), `_puntos.geojson` y `.qgz` (OSM + Esri), con opción de agregar otro GeoTIFF debajo (p. ej. el mosaico térmico de TermoReferencia).
- **Cualquier CSV:** si no hay columnas de GPS con nombre conocido, el visor pregunta cuáles son latitud y longitud; en la CLI, `--lat`/`--lon`. Probado con `mediciones_16sep.csv`, `mediciones_16sep_gps_dron.csv` (`--gps-dron`) y `Flight_Data_6_Sensor_2_ppm_Avg_cal_n0.csv` (Campbell, `;` y coma decimal).
- **Dónde:** `mapa_calor.py` (nuevo: `grid()`, `lag_positions()`, `write_geotiff()`, `write_qgis()`, `export()`); `visor_qt.py` → `_build_heat_bar()`, `heat_inputs()`, `update_coverage()`, `cover_hover()`, `export_heat()`, `ask_gps_columns()`; `graficar.py` → `make_heatmap()` y opciones `--calor…`.
- **Sin dependencias pesadas:** GeoTIFF con Pillow (sin GDAL) y proyecto QGIS escribiendo el XML (sin PyQGIS ni pyproj; el CRS va con proj4 + authid). `Pillow` agregado a `requirements.txt`; `mapa_calor` a `GasLab.spec`.
- **Ojo:** en Flight_Data el CO₂ trae ceros y ~10 ppm al arrancar: usar mínimo válido ~300. Coordenadas en grados decimales (no NMEA ddmm.mmmm). Tests: `HeatMapTests`; el `.qgz` se validó abriéndolo con PyQGIS (capas válidas, EPSG:3857 y el mosaico térmico en EPSG:32633 alineado).

## 2026-10-19 · Exportar Excel del tramo; el tramo elegido encierra las gráficas
- **Qué:** botón **Exportar Excel…** en el visor rápido. Exporta las **variables marcadas** y las **muestras visibles**: el tramo (o día/horas) elegido, o solo la parte ampliada dentro de él. Antes de guardar muestra un resumen (muestras, inicio → fin, variables). El libro trae las hojas **Resumen** (mín/prom/máx con fórmulas), **Datos**, **Gráficas** (un gráfico nativo de Excel por variable, en 3 columnas) y **Ruta** (longitud contra latitud, sin fondo de mapa).
- **Tramo cerrado:** con un tramo, día u horas elegidos, las curvas solo contienen esas muestras y el zoom/desplazamiento no puede salir del tramo; **Restablecer zoom** vuelve al tramo completo, y las estadísticas y el cursor tampoco salen de él. **Todo** quita el límite.
- **Dónde:** `graficar.py` → `make_excel()`, `default_variables()`; `visor_qt.py` → `lock_plots()`, `span()`, `visible_idx()`, `reset_zoom()`, `export_excel()`.
- **Dependencia nueva:** `xlsxwriter` (en `requirements.txt` y `GasLab.spec`). Test: `test_excel_only_contains_the_given_rows`.

## 2026-10-15 · Ventana de tiempo que limita el mapa; arreglo del fondo del mapa
- **Qué:** nueva fila de la barra con **Inactividad > N s** + **Tramo** (tramos continuos), **Todo**, y en la fila siguiente **Día + de … a …** (hora de inicio y de fin del día elegido; reemplazó al rango manual con fecha completa y al selector de una sola hora). Elegir una ventana amplía las gráficas y limita el mapa (ruta, puntos, cobertura, encuadre) a esas muestras.
- **Dónde:** `visor_qt.py` → `compute_intervals()`, `on_interval()`, `fill_hours()`, `on_hour_from()`, `on_hour_to()`, `apply_hours()`, `apply_window()`, `clear_window()`, y `build_map()` (usa `self.window`).
- **Bug corregido:** el mapa no mostraba fondo (ni OSM ni satélite) porque al agregar el nivel máximo por proveedor (`PROVIDERS[...][3]`) `fetch_tile` seguía desempaquetando el proveedor en 3 valores y fallaba en silencio. Ahora usa `provider[:2]`.
- **Ojo:** los tramos y el rango manual usan la hora local de la zona elegida; no están en la vista web ni en la ventana de inicio; no hay test automático (probado a mano con `mediciones_16sep.csv`).

## 2026-10-14 · Día y hora, y tamaño de letra (visor rápido)
- **Qué:** los selectores **Día** y **Hora** (segunda fila de la barra) amplían las gráficas a un día u hora con muestras; **Letra** (8–28 pt, se guarda en QSettings) agranda toda la interfaz y las gráficas.
- **Dónde:** `visor_qt.py` → `Viewer.compute_days()`, `fill_hours()`, `on_day()`, `on_hour()` (sección `# ---------- day / hour ----------`) y `set_fontsize()` / `apply_font()`.
- Había reemplazado el selector de intervalos por huecos; volvió el 2026-10-15 junto con el rango manual (ver arriba).
- **Ojo:** día y hora salen de la columna de tiempo en hora local de la zona elegida; no están en la vista web ni en la ventana de inicio; no hay test automático.

## 2026-10-13 · CSV con bytes nulos
- `graficar.load_csv` quita los `\x00` (escritura interrumpida en SD/USB) y descarta las filas truncadas; un archivo de 0 bytes da un error claro.

## Antes
- Capa **Cobertura** (mapa de calor), fondos de mapa con nivel máximo por proveedor, vista web servida por `http://127.0.0.1` (OpenStreetMap bloquea tiles sin Referer), y empaquetado con PyInstaller/Makefile.
