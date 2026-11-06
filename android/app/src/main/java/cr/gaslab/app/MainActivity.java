package cr.gaslab.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.content.res.AssetManager;
import android.content.res.Configuration;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.util.Base64;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * GasLab 2.0 en Android: el servidor Python de la PC (gaslab_web.py) corre dentro de la app con Chaquopy y la misma
 * página de web/ se muestra en un WebView a pantalla completa. Aquí solo está lo que un WebView no hace solo:
 * abrir archivos con el selector de Android, guardar en Descargas (no hay descargas de enlaces blob:), la pantalla
 * completa de las gráficas y no quedar debajo de las barras del sistema.
 */
public class MainActivity extends Activity {
    private static final int PICK_FILE = 1;
    private static final String LOADING = "<html><body style=\"margin:0;height:100vh;display:flex;align-items:center;"
            + "justify-content:center;font:16px system-ui,sans-serif;color:#888;background:transparent\">Starting GasLab…</body></html>";
    private static final Pattern FILENAME = Pattern.compile("filename\\*=UTF-8''([^;]+)");

    private final ExecutorService io = Executors.newCachedThreadPool();
    private final Handler main = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private ValueCallback<Uri[]> pickCallback;
    private View fullView;
    private WebChromeClient.CustomViewCallback fullCallback;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        WebView.setWebContentsDebuggingEnabled(true);  // permite revisar la página desde chrome://inspect en la PC
        root = new FrameLayout(this);
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        // Android 15+ dibuja la app debajo de las barras del sistema: se deja ese margen (y el del teclado en pantalla).
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return WindowInsets.CONSUMED;
        });
        setContentView(root);
        styleBars();

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setSupportZoom(false);  // el zoom lo hacen las gráficas y el mapa, no la página
        settings.setBuiltInZoomControls(false);
        settings.setTextZoom(100);
        settings.setAllowFileAccess(false);
        web.setBackgroundColor(0);
        web.addJavascriptInterface(new Bridge(), "GasLabAndroid");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri url = request.getUrl();
                if ("127.0.0.1".equals(url.getHost())) return false;
                try {  // enlaces de afuera (p. ej. atribuciones del mapa): en el navegador
                    startActivity(new Intent(Intent.ACTION_VIEW, url));
                } catch (ActivityNotFoundException ignored) {
                }
                return true;
            }
        });
        web.setWebChromeClient(new Chrome());
        web.loadDataWithBaseURL(null, LOADING, "text/html", "utf-8", null);

        if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
        io.execute(this::startServer);
    }

    /** Copia la interfaz y arranca el servidor Python (importar pandas tarda unos segundos: fuera del hilo principal). */
    private void startServer() {
        try {
            File webDir = copyWeb();
            int port = Python.getInstance().getModule("gaslab_android")
                    .callAttr("start", webDir.getPath(), getCacheDir().getPath()).toInt();
            main.post(() -> web.loadUrl("http://127.0.0.1:" + port + "/"));
        } catch (Exception e) {
            String html = "<pre style=\"white-space:pre-wrap;font:13px monospace;padding:16px\">Could not start GasLab:\n\n"
                    + android.text.TextUtils.htmlEncode(String.valueOf(e)) + "</pre>";
            main.post(() -> web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null));
        }
    }

    /** assets/web -> archivos internos de la app, solo cuando la APK cambió (instalación o actualización). */
    private File copyWeb() throws Exception {
        File dir = new File(getFilesDir(), "web");
        File stamp = new File(dir, ".version");
        String version = String.valueOf(getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime);
        if (stamp.isFile() && version.equals(readAll(new java.io.FileInputStream(stamp)))) return dir;
        deleteTree(dir);
        copyAssets(getAssets(), "web", dir);
        try (OutputStream out = new FileOutputStream(stamp)) {
            out.write(version.getBytes(StandardCharsets.UTF_8));
        }
        return dir;
    }

    private static void copyAssets(AssetManager assets, String path, File target) throws IOException {
        String[] children = assets.list(path);
        if (children != null && children.length > 0) {
            if (!target.isDirectory() && !target.mkdirs()) throw new IOException("Could not create " + target);
            for (String child : children) copyAssets(assets, path + "/" + child, new File(target, child));
            return;
        }
        try (InputStream in = assets.open(path); OutputStream out = new FileOutputStream(target)) {
            copy(in, out);
        }
    }

    private static void deleteTree(File file) {
        File[] children = file.listFiles();
        if (children != null) for (File child : children) deleteTree(child);
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }

    private static void copy(InputStream in, OutputStream out) throws IOException {
        byte[] buffer = new byte[1 << 16];
        for (int n; (n = in.read(buffer)) > 0; ) out.write(buffer, 0, n);
    }

    private static String readAll(InputStream in) throws IOException {
        try (InputStream stream = in) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            copy(stream, out);
            return out.toString("UTF-8");
        }
    }

    /** Guarda en Descargas (MediaStore: no necesita permisos). Si el nombre ya existe, Android agrega (1), (2)… */
    private void saveToDownloads(String name, String mime, InputStream in) throws IOException {
        ContentResolver resolver = getContentResolver();
        ContentValues values = new ContentValues();
        values.put(MediaStore.Downloads.DISPLAY_NAME, name);
        values.put(MediaStore.Downloads.MIME_TYPE, mime);
        values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS);
        values.put(MediaStore.Downloads.IS_PENDING, 1);
        Uri uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
        if (uri == null) throw new IOException("Android did not allow creating the file");
        try (OutputStream out = resolver.openOutputStream(uri)) {
            if (out == null) throw new IOException("Android did not allow writing the file");
            copy(in, out);
        } catch (IOException e) {
            resolver.delete(uri, null, null);
            throw e;
        }
        values.clear();
        values.put(MediaStore.Downloads.IS_PENDING, 0);
        resolver.update(uri, values, null, null);
    }

    private static String cleanMime(String type) {
        if (type == null || type.isEmpty()) return "application/octet-stream";
        int semicolon = type.indexOf(';');
        return (semicolon >= 0 ? type.substring(0, semicolon) : type).trim();
    }

    /** Lo que llama la página (window.GasLabAndroid) para guardar archivos; ver saveFrom() en web/app.js. */
    private class Bridge {
        /** Baja `url` del servidor local y la guarda; al terminar llama a gaslabSaved(id, error, nombre) en la página. */
        @JavascriptInterface
        public void saveUrl(String id, String url, String fallback) {
            io.execute(() -> {
                String error = null, name = fallback;
                try {
                    URL target = new URL(url);
                    if (!"127.0.0.1".equals(target.getHost())) throw new IOException("address not allowed");
                    HttpURLConnection connection = (HttpURLConnection) target.openConnection();
                    connection.setConnectTimeout(10000);
                    connection.setReadTimeout(0);  // un GeoTIFF grande puede tardar en prepararse
                    if (connection.getResponseCode() != 200) {
                        InputStream err = connection.getErrorStream();
                        String body = err == null ? "" : readAll(err);
                        try {
                            error = new JSONObject(body).getString("error");
                        } catch (Exception ignored) {
                            error = "Error " + connection.getResponseCode();
                        }
                    } else {
                        Matcher match = FILENAME.matcher(String.valueOf(connection.getHeaderField("Content-Disposition")));
                        if (match.find()) name = URLDecoder.decode(match.group(1), "UTF-8");
                        try (InputStream in = connection.getInputStream()) {
                            saveToDownloads(name, cleanMime(connection.getContentType()), in);
                        }
                    }
                    connection.disconnect();
                } catch (Exception e) {
                    error = "Could not save: " + e.getMessage();
                }
                String js = "gaslabSaved(" + JSONObject.quote(id) + "," + (error == null ? "null" : JSONObject.quote(error))
                        + "," + JSONObject.quote(name) + ")";
                main.post(() -> web.evaluateJavascript(js, null));
            });
        }

        /** Guarda bytes ya hechos en la página (el PNG del mapa). Devuelve '' o el mensaje de error. */
        @JavascriptInterface
        public String saveBase64(String name, String mime, String base64) {
            try {
                saveToDownloads(name, cleanMime(mime), new ByteArrayInputStream(Base64.decode(base64, Base64.DEFAULT)));
                return "";
            } catch (Exception e) {
                return "Could not save: " + e.getMessage();
            }
        }
    }

    private class Chrome extends WebChromeClient {
        /** «Abrir archivo…»: el selector de documentos de Android (CSV, .dat, Excel en Descargas, Drive, USB…). */
        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (pickCallback != null) pickCallback.onReceiveValue(null);
            pickCallback = callback;
            Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
            try {
                startActivityForResult(intent, PICK_FILE);
                return true;
            } catch (ActivityNotFoundException e) {
                pickCallback = null;
                return false;
            }
        }

        /** «Pantalla completa» de las gráficas. */
        @Override
        public void onShowCustomView(View view, CustomViewCallback callback) {
            if (fullView != null) {
                callback.onCustomViewHidden();
                return;
            }
            fullView = view;
            fullCallback = callback;
            ((FrameLayout) getWindow().getDecorView()).addView(view,
                    new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.hide(WindowInsets.Type.systemBars());
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        }

        @Override
        public void onHideCustomView() {
            if (fullView == null) return;
            ((FrameLayout) getWindow().getDecorView()).removeView(fullView);
            fullView = null;
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) controller.show(WindowInsets.Type.systemBars());
            if (fullCallback != null) fullCallback.onCustomViewHidden();
            fullCallback = null;
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != PICK_FILE || pickCallback == null) return;
        Uri uri = resultCode == RESULT_OK && data != null ? data.getData() : null;
        pickCallback.onReceiveValue(uri == null ? null : new Uri[]{uri});
        pickCallback = null;
    }

    /** Íconos de las barras del sistema oscuros en tema claro y claros en tema oscuro. */
    private void styleBars() {
        WindowInsetsController controller = getWindow().getInsetsController();
        if (controller == null) return;
        boolean night = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        int light = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
        controller.setSystemBarsAppearance(night ? 0 : light, light);
    }

    @Override
    public void onConfigurationChanged(Configuration config) {
        super.onConfigurationChanged(config);
        styleBars();
    }

    /** Atrás: sale de la pantalla completa; si no, deja GasLab en segundo plano sin perder el archivo abierto. */
    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (fullView != null) {
            web.evaluateJavascript("document.fullscreenElement && document.exitFullscreen()", null);
            return;
        }
        moveTaskToBack(true);
    }
}
