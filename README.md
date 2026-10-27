# Graficación CSV de GasLab

Primera versión local: una ventana sencilla para abrir CSV, seleccionar variables y verlas en un visor rápido (pyqtgraph) o en el navegador (Plotly), con la ruta GPS sobre un mapa. Compatible con los CSV de MicroGas Receptor, DJI y Simulado. No modifica el CSV original.

## Abrir

Desde esta carpeta:

```bash
./iniciar.sh
```

O ejecuta `.venv/bin/python graficar.py`. Pulsa **Abrir CSV**, selecciona una o varias variables (o **Seleccionar todas las variables**), ajusta la columna de tiempo si hace falta y abre el **Visor rápido (ventana)**, la **Vista interactiva (navegador)** o el **Mapa GPS…**. El eje X (fecha local, tiempo transcurrido o número de muestra) se cambia dentro de cada visor.

Zona predeterminada: `UTC`. Puedes cambiarla a otra zona IANA (por ejemplo `America/Costa_Rica`). Fechas ISO 8601 con zona respetan esa zona; fechas sin zona se interpretan como UTC. Para fechas numéricas, se detecta Unix s/ms/us/ns por magnitud; selecciona la unidad explícita si es necesario. Las filas pueden venir en cualquier orden siempre que el CSV tenga encabezado: al cargar se ordenan cronológicamente (en memoria) por la columna de tiempo elegida; las filas sin fecha válida quedan al final. Si la columna de tiempo no se puede leer, se conserva el orden del archivo. Se recomienda fecha ISO completa, no una columna que contenga solamente la hora.

El filtro **Solo muestras nuevas SEN66** usa `sen66_new_data == 1` en archivos DJI para excluir lecturas retenidas del registro a 10 Hz. En CSV sin esa columna no filtra nada. Por defecto se muestran todas las filas.

## Visor rápido (ventana, pyqtgraph)

Botón **Visor rápido (ventana)** o `.venv/bin/python graficar.py datos.csv --qt` (también `.venv/bin/python visor_qt.py datos.csv`). Ventana propia con el mapa OpenStreetMap o satélite Esri a la izquierda (los tiles se descargan según el zoom y se guardan en `~/.cache/gaslab_tiles`) y las gráficas a la derecha, con aceleración de dibujo para archivos grandes. Las gráficas se organizan en tres columnas y las filas adicionales se recorren con la barra lateral. Zoom y desplazamiento sincronizados, cursor compartido entre gráficas y mapa, tramo con zoom resaltado en la ruta, ruta coloreada por variable, mín/prom/máx del tramo visible, Y ajustada al tramo, lista de variables a la izquierda, **clic en una gráfica para ampliarla** (Esc o otro clic para volver), cambio de eje X, exportar PNG y **Modo noche** (interfaz oscura, líneas más claras y mapa oscurecido; se recuerda al reabrir). Al pasar el mouse por una gráfica aparece un cuadro con muestra, eje X, valor, latitud, longitud y altura. Requiere `pyqtgraph` y PyQt5 (ver `requirements.txt`). Sin internet el mapa no muestra fondo, pero sí la ruta.

**Tramos, día/hora y rango manual** (detalle en `CHANGELOG.md`). Se carga todo el archivo y se puede limitar a una ventana de tiempo de tres formas; la ventana ampla las gráficas **y limita el mapa** (ruta, puntos, cobertura y encuadre) a esas muestras:
- **Inactividad > N s + Tramo:** lista los tramos continuos; una pausa mayor a N s entre dos muestras abre un tramo nuevo (1200 s por defecto). Elegir un tramo lo aplica.
- **Día + de … a …:** eliges el día y la hora de inicio y la hora de fin (solo se ofrecen horas con mediciones; por ejemplo día 16/09, de 06:00 a 07:00). Al elegir un día, el rango por defecto es todo el día.
- **Todo:** quita la ventana. La ruta no une puntos separados por una pausa mayor a la inactividad.
Con un tramo elegido las gráficas quedan **encerradas** en él: no se puede hacer zoom ni desplazarse fuera del tramo (**Restablecer zoom** vuelve al tramo completo).

**Exportar Excel…** guarda un `.xlsx` con las variables marcadas y las muestras visibles (el tramo elegido o la parte ampliada dentro de él): hojas Resumen, Datos, Gráficas (gráficos nativos de Excel) y Ruta (latitud/longitud sin fondo de mapa). Antes de guardar muestra qué se va a exportar.

**Letra** cambia el tamaño del texto de toda la ventana (8 a 28 pt, se recuerda al reabrir).

**Mapa de calor (puntos, celdas o cobertura).** La fila **Mapa de calor** colorea el mapa según una variable. Con **Puntos** (por defecto) cada muestra se dibuja en su latitud/longitud con el color de su valor (escala azul → rojo; los valores altos quedan encima; tamaño ajustable en px y, al pasar el mouse, muestra el valor del punto). Con **Celdas** divide el mapa en celdas cuadradas (0,5 a 250 m) y colorea cada una. Con **Valor = Muestras (cobertura)** el color es el porcentaje de las muestras con GPS que cayó en la celda (más claro = zona más medida). Con **Valor = una variable** (CO₂, PM, temperatura… cualquier columna numérica) cada muestra se coloca en su latitud/longitud y la celda toma el **Promedio**, el **Máximo** o el **Percentil 95** de las muestras que caen en ella (escala azul → rojo, como el mapa de CO₂ de referencia). Opciones:
- **Celdas de 0,5–2 m:** el GPS tiene un error típico de 1–3 m, así que celdas más pequeñas que eso no ganan detalle real (se parecen a los puntos).
- **Suavizado** (1–3 celdas, solo celdas): reparte cada valor con un núcleo gaussiano; solo se dibuja hasta ~2 veces el suavizado desde la ruta, no se inventan valores lejos de lo medido.
- **Desfase** (s): retraso del sensor; el valor registrado en t se coloca donde estaba el equipo en t − desfase (sin él, los picos de CO₂ aparecen corridos hacia adelante en la ruta). Necesita columna de tiempo.
- **Válido de … a …:** valores fuera del rango se ignoran (p. ej. en `Flight_Data…csv` el CO₂ trae ceros y lecturas de ~10 ppm del arranque: usar mínimo 300).
- Respeta el tramo o día elegido. Al pasar el mouse por el mapa, la leyenda muestra el valor y las muestras de la celda.

**Exportar GeoTIFF/QGIS…** guarda la variable elegida como `<nombre>_puntos.geojson` (una entidad por muestra con su valor y fecha UTC), `<nombre>.tif` (las celdas: GeoTIFF Float32 en Web Mercator EPSG:3857, sin dato = -9999) y `<nombre>.qgz`: proyecto QGIS con la **capa de puntos** coloreada por valor (20 clases con leyenda, los altos encima) y la **capa de celdas**, sobre OpenStreetMap / Esri satélite. Queda encendida la que se estaba viendo (Puntos o Celdas); la otra se enciende en el panel de capas. Opcionalmente agrega debajo otro GeoTIFF, por ejemplo el mosaico térmico `temperatura_python.tif` de [TermoReferencia](../termoreferencia/README.md), con otra escala de colores. No necesita GDAL ni QGIS para generarse (`mapa_calor.py`, solo numpy y Pillow).

Si el CSV no trae columnas de GPS con un nombre conocido (`latitud`, `latitude`, `lat`…), al abrirlo el visor pregunta cuáles son la latitud y la longitud (en grados decimales).

## Vista interactiva (navegador)

Botón **Vista interactiva (navegador)** o `--web salida.html` en la CLI. Genera un HTML autónomo (Plotly con WebGL, incluido en el archivo) con el mapa a la izquierda y las gráficas a la derecha. Las gráficas se organizan en tres columnas; las filas adicionales se recorren con la barra lateral (en pantallas estrechas se adaptan a menos columnas). Funciones: zoom y desplazamiento sincronizados entre gráficas, cursor compartido (al pasar el mouse por una gráfica o por el mapa se marca ese instante en todo), el tramo con zoom se resalta en la ruta, ruta coloreada por una variable, mapa OpenStreetMap o satélite Esri, mín/prom/máx del tramo visible, ajuste automático del eje Y, activar/desactivar variables y ampliar una gráfica con clic en su título (Esc para volver). Solo los fondos del mapa necesitan internet. El botón de la ventana abre la vista desde un servidor local (`http://127.0.0.1`), porque OpenStreetMap bloquea los tiles pedidos sin Referer, y un HTML abierto como archivo no envía ninguno; por eso un HTML guardado con `--web` y abierto con doble clic arranca con el fondo satélite (el OSM puede salir bloqueado). El HTML contiene los datos del CSV. Requiere `plotly` (ver `requirements.txt`). Las filas se ordenan por la columna de tiempo, igual que en el visor rápido.

## Ruta y satélite

- **Mapa GPS**: guarda un HTML y lo abre en el navegador, con OpenStreetMap como fondo inicial y una capa satelital Esri alternativa. Toca los puntos amarillos para consultar hora, CO₂ y GPS. Puedes ampliar y mover el mapa.
- El mapa necesita internet para cargar las bibliotecas y los fondos. El CSV se procesa localmente; el HTML contiene las coordenadas, por lo que compartirlo comparte esos datos.
- Las filas sin coordenadas válidas cortan la ruta; tampoco se unen sesiones distintas cuando existe la columna `session`. No se inventan ubicaciones ni se filtran saltos GPS válidos. Los CSV simulados sin GPS sí se pueden graficar, pero no generan rutas.
- Se conserva toda la ruta. Para no saturar el navegador, se muestran hasta aproximadamente 2.000 puntos consultables; el mapa informa la cantidad. En archivos grandes, generar el mapa puede tardar.
- Los fondos son servicios externos: su disponibilidad, cobertura y resolución dependen del proveedor. Se conserva la atribución del proveedor suministrada por Folium/xyzservices.

## Línea de comandos

```bash
# Visor rápido (ventana) con el CSV; --y elige las variables iniciales:
.venv/bin/python graficar.py datos.csv --y co2_ppm temperatura_c humedad_pct

# Vista interactiva en HTML y mapa satelital:
.venv/bin/python graficar.py datos.csv --web vista.html --mapa ruta.html

# CSV DJI, solo muestras nuevas y hora de recepción SEN66 en el control:
.venv/bin/python graficar.py datos.csv --solo-nuevas --tiempo sen66_muestra_utc

# Otra columna de tiempo numérico (milisegundos Unix):
.venv/bin/python graficar.py datos.csv --tiempo received_at_ms --unidad ms

# Mapa de calor georreferenciado de una variable -> <csv>_<variable>.tif + _puntos.geojson + .qgz:
.venv/bin/python graficar.py mediciones_16sep.csv --calor co2_ppm --celda 5 --suavizado 1.5 --desfase 3

# CSV Campbell (Flight_Data), percentil 95, ignorando lecturas < 300 ppm y con el mosaico térmico debajo:
.venv/bin/python graficar.py Flight_Data_6_Sensor_2_ppm_Avg_cal_n0.csv --calor CO2_Concentration_Avg_cal --min 300 \
    --estadistico p95 --celda 4 --capa ../termoreferencia/resultados/vulcano-porto-levante_python/temperatura_python.tif

# Cualquier CSV con columnas de GPS de nombre no reconocido, o usando el GPS del dron:
.venv/bin/python graficar.py otro.csv --calor NO2 --lat Y_gps --lon X_gps
.venv/bin/python graficar.py mediciones_16sep_gps_dron.csv --calor co2_ppm --gps-dron
```

Opciones de `--calor`: `--calor-salida`, `--celda` (m, desde 0.5; 10), `--celdas` (abrir QGIS con las celdas encendidas en lugar de los puntos), `--tam-punto` (mm, 1.8), `--estadistico media|maximo|p95|muestras`, `--suavizado` (celdas, 1; 0 = sin suavizar), `--desfase` (s), `--min`/`--max` (rango válido), `--capa` (GeoTIFF extra, repetible), `--lat`/`--lon`, `--gps-dron`. Las coordenadas deben venir en grados decimales.

CSV separados por coma, punto y coma o tabulador: el separador se detecta automáticamente. Se admiten decimales con coma en columnas separadas por punto y coma. Las columnas vacías/no numéricas no se ofrecen como variables. Los nombres de columna de otros equipos se reconocen sin importar mayúsculas, acentos ni unidades entre paréntesis (`TIMESTAMP`, `Latitude`, `GPS_Lat`, `CO2 (ppm)`, `Temperature (°C)`…) y se renombran al nombre que usa la app; para añadir otro, agrégalo a `COLUMN_ALIASES` en `graficar.py`. Los valores `-2147483648`, `2147483647`, `-9999` y `-99999` (marcadores de "sin dato" de registradores como Campbell) se tratan como faltantes, y las coordenadas 0,0 (GPS sin señal) no se dibujan en la ruta. Los valores faltantes dejan huecos en las gráficas. Los errores se muestran en la ventana o terminal.

## Instalación desde cero

Python 3.10 o posterior con Tkinter. En Ubuntu, si falta Tkinter, instala el paquete `python3-tk`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./iniciar.sh
```

El entorno preparado en esta máquina reutiliza pandas y PyQt5 ya instalados mediante `--system-site-packages`; las dependencias adicionales están dentro de `.venv`.

## Ejemplo y pruebas

Las pruebas usan datos **sintéticos** definidos en `test_graficar.py` (GPS, un hueco y un cambio de día en Costa Rica); no son una medición real. Las imágenes y el mapa de `ejemplos/` son de una versión anterior.

```bash
.venv/bin/python -m unittest -v test_graficar.py
```

Referencias de los fondos: [Folium: capas de mapas](https://python-visualization.github.io/folium/v0.19.3/user_guide/raster_layers/tiles.html) y [Esri: atribución de mapas base](https://support.esri.com/en-us/knowledge-base/what-is-the-correct-way-to-cite-an-arcgis-online-basema-000012040).


## Incorporación y elección del archivo

El [manual MicroGas](../MicroGas/MANUAL_REPLICACION_DESDE_CERO.md) explica cómo obtener los CSV. Para una sesión larga del receptor usa **Archivos CSV → Exportar**: el botón del histórico solo exporta el buffer de hasta 7.200 muestras. El emisor y el receptor tienen 24 y 16 columnas respectivamente (incluida la altitud: `altura_m` al final en los CSV originales; el visor reconoce también `altitud_m`, `altitud` y `altura`); sus cantidades de filas no tienen por qué coincidir.

En CSV DJI selecciona `sen66_muestra_utc` y **Solo muestras nuevas** para estudiar lecturas; esa fecha es recepción en el control, no adquisición física en la Pi. Usa `fecha_hora_utc` sin filtro para estudiar el registro a ~10 Hz. En Receptor utiliza `fecha_hora_utc`. Los valores `payload_uptime_ms` son tiempo desde arranque y no deben interpretarse automáticamente como fechas Unix.

Conserva un CSV original sin modificar y guarda los resultados aparte. El programa ordena por la columna de tiempo seleccionada, pero no corrige coordenadas que saltan ni diferencia sesiones que no estén identificadas. Analiza vuelos por separado si no existe `session`.

## Guía de mantenimiento y diagnóstico

El mapa de calor georreferenciado (rejilla, desfase, GeoTIFF, GeoJSON y proyecto QGIS) está en `mapa_calor.py`. `graficar.py` separa carga (`load_csv`), fechas (`parse_time`/`time_axis`), segmentos GPS (`gps_segments`), mapa (`make_map`), vista web (`make_viewer`), ventana de selección (`gui`) y CLI (`main`); el visor rápido está en `visor_qt.py`. Al cambiar fechas o columnas ejecuta `test_graficar.py` y comprueba un CSV de cada app. Los datos de prueba son sintéticos y no validan GPS real.

| Problema | Comprobación |
|---|---|
| No abre la ventana | Entorno `.venv`, Tkinter y sesión gráfica; sin escritorio usa `--web` o `--mapa` |
| No hay ruta | Coordenadas numéricas válidas; MicroGas Simulado desde 0.4.0 genera GPS sintético; archivos antiguos pueden no incluirlo |
| Hora desplazada | Zona IANA, UTC de entrada y unidad Unix elegida |
| Mapa sin fondo | Internet y servicios del navegador; el HTML necesita recursos externos |
| CSV no carga | Encabezado, separador y que no se haya convertido al guardarlo en una hoja de cálculo |
| No guarda resultados | Carpeta de destino existente y con permisos; la CLI no crea carpetas de salida |

Las dependencias se instalan desde cero con los pasos anteriores; no copies `.venv` a otra máquina. Para reproducir una entrega registra también las versiones instaladas con `.venv/bin/python -m pip freeze`.


Marcadores del mapa: inicio 🏠 y fin ✈️ (cámbialos en `START_ICON` y `END_ICON` de `graficar.py`). En los cuadros de datos la altura se muestra como **Altitud**, después de latitud y longitud.

## Ejecutable de Windows

En Windows con Python 3.10+: doble clic a `build_windows.bat` (o `pyinstaller --noconfirm GasLab.spec` tras instalar `requirements-build.txt`). El resultado queda en `dist\GasLab\`; esa carpeta completa se puede copiar a otro equipo y ejecutar `GasLab.exe`. En GitHub, el workflow *Build Windows* (pestaña Actions → Run workflow, o al subir una etiqueta `v*`) lo compila y lo publica como artefacto `GasLab-windows`. El visor rápido se abre relanzando el mismo ejecutable con `--visor-qt`.

## Makefile

`make help` lista los objetivos: `make setup` (crea `.venv`), `make run`, `make test`, `make build` (genera `dist/GasLab/`) y `make clean`. En Windows hace falta GNU make (`choco install make` o `winget install ezwinports.make`); `build_windows.bat` sigue funcionando sin make.
