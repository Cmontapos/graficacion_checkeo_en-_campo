"""Arranque de GasLab 2.0 dentro de la APK de Android (Chaquopy).

La app nativa (MainActivity.java) copia la carpeta web/ a su almacenamiento interno, llama a start() en un hilo
aparte y muestra la página en un WebView. El servidor es el mismo de la PC (gaslab_web.Handler), solo cambian las
carpetas: la interfaz y el caché de teselas del terreno quedan dentro de la app.
"""
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

PORT = 47800  # fijo para que el WebView conserve lo guardado en la página (tema, etc.) entre aperturas
_server = None


def start(web_dir, cache_dir):
    """Arranca el servidor (una sola vez por proceso) y devuelve el puerto."""
    global _server
    if _server is None:
        import gaslab_web
        import terreno
        gaslab_web.WEB_DIR = Path(web_dir)
        terreno.CACHE = Path(cache_dir) / 'gaslab_tiles' / 'terrarium'
        try:
            _server = ThreadingHTTPServer(('127.0.0.1', PORT), gaslab_web.Handler)
        except OSError:  # puerto ocupado: uno libre
            _server = ThreadingHTTPServer(('127.0.0.1', 0), gaslab_web.Handler)
        threading.Thread(target=_server.serve_forever, daemon=True).start()
    return _server.server_address[1]
