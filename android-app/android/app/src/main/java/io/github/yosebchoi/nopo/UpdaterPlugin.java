package io.github.yosebchoi.nopo;

import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import androidx.core.content.FileProvider;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import org.json.JSONObject;

/**
 * In-app updates for the sideloaded APK: compares this build with the one published on the
 * nopo-apk release, downloads the new APK and hands it to Android's installer (Android always
 * asks the person to confirm an install; the first time it also asks to allow this app as a source).
 */
@CapacitorPlugin(name = "Updater")
public class UpdaterPlugin extends Plugin {

    static final String RELEASE = "https://github.com/YoSebChoi/YoSebChoi/releases/download/nopo-apk/";

    private long currentVersion() throws Exception {
        PackageInfo info = getContext().getPackageManager().getPackageInfo(getContext().getPackageName(), 0);
        return Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode;
    }

    private static HttpURLConnection open(String url) throws Exception {
        // GitHub answers release downloads with a redirect to its file host
        for (int i = 0; i < 5; i++) {
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            c.setConnectTimeout(15000);
            c.setReadTimeout(30000);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(false);
            int code = c.getResponseCode();
            if (code >= 300 && code < 400 && c.getHeaderField("Location") != null) {
                url = new URL(new URL(url), c.getHeaderField("Location")).toString();
                c.disconnect();
                continue;
            }
            if (code != 200) throw new Exception("HTTP " + code);
            return c;
        }
        throw new Exception("too many redirects");
    }

    @PluginMethod
    public void check(PluginCall call) {
        new Thread(() -> {
            try {
                HttpURLConnection c = open(RELEASE + "nopo-map.json");
                ByteArrayOutputStream buf = new ByteArrayOutputStream();
                try (InputStream in = c.getInputStream()) {
                    byte[] b = new byte[8192];
                    for (int n; (n = in.read(b)) > 0; ) buf.write(b, 0, n);
                }
                JSONObject latest = new JSONObject(buf.toString("UTF-8"));
                JSObject ret = new JSObject();
                ret.put("current", currentVersion());
                ret.put("latest", latest.optLong("versionCode", 0));
                ret.put("url", RELEASE + "nopo-map.apk");
                call.resolve(ret);
            } catch (Exception e) {
                call.reject("update check failed: " + e.getMessage());
            }
        }).start();
    }

    @PluginMethod
    public void install(PluginCall call) {
        // Android 8+: this app must be allowed to install apps; the first time, open that setting
        if (Build.VERSION.SDK_INT >= 26 && !getContext().getPackageManager().canRequestPackageInstalls()) {
            Intent allow = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getContext().getPackageName()));
            allow.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(allow);
            JSObject ret = new JSObject();
            ret.put("needsPermission", true);
            call.resolve(ret);
            return;
        }
        String url = call.getString("url", RELEASE + "nopo-map.apk");
        new Thread(() -> {
            try {
                File apk = new File(getContext().getCacheDir(), "nopo-map-update.apk");
                HttpURLConnection c = open(url);
                long total = c.getContentLengthLong();
                long done = 0;
                int last = -1;
                try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(apk)) {
                    byte[] b = new byte[65536];
                    for (int n; (n = in.read(b)) > 0; ) {
                        out.write(b, 0, n);
                        done += n;
                        int pct = total > 0 ? (int) (done * 100 / total) : -1;
                        if (pct != last && pct % 5 == 0) {
                            last = pct;
                            JSObject p = new JSObject();
                            p.put("percent", pct);
                            notifyListeners("progress", p);
                        }
                    }
                }
                Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".fileprovider", apk);
                Intent intent = new Intent(Intent.ACTION_VIEW);
                intent.setDataAndType(uri, "application/vnd.android.package-archive");
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(intent);
                call.resolve();
            } catch (Exception e) {
                call.reject("update download failed: " + e.getMessage());
            }
        }).start();
    }
}
