package io.github.yosebchoi.hcgnotes;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.WindowManager;

import androidx.core.content.FileProvider;

import com.getcapacitor.BridgeActivity;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(ScreenPlugin.class);
        registerPlugin(UpdatePlugin.class);
        super.onCreate(savedInstanceState);
    }

    /** Keeps the screen on while the read timer runs (the page calls HcgScreen.keepOn / allowOff). */
    @CapacitorPlugin(name = "HcgScreen")
    public static class ScreenPlugin extends Plugin {
        @PluginMethod
        public void keepOn(PluginCall call) {
            getActivity().runOnUiThread(() -> getActivity().getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON));
            call.resolve();
        }

        @PluginMethod
        public void allowOff(PluginCall call) {
            getActivity().runOnUiThread(() -> getActivity().getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON));
            call.resolve();
        }
    }

    /**
     * In-app update: the page finds a newer build on the GitHub release and calls
     * HcgUpdate.install({url}); the APK is downloaded into the cache and handed to
     * Android's installer, which installs it over this app (same key, records kept).
     * Progress arrives as "progress" events ({percent}).
     */
    @CapacitorPlugin(name = "HcgUpdate")
    public static class UpdatePlugin extends Plugin {
        @PluginMethod
        public void install(PluginCall call) {
            String url = call.getString("url");
            if (url == null || !url.startsWith("https://github.com/YoSebChoi/YoSebChoi/releases/download/")) {
                call.reject("not an update of this app");
                return;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getContext().getPackageManager().canRequestPackageInstalls()) {
                // Android asks once per app: "allow installing apps from this source"
                Intent ask = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + getContext().getPackageName()));
                ask.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(ask);
                JSObject r = new JSObject();
                r.put("needsPermission", true);
                call.resolve(r);
                return;
            }
            new Thread(() -> {
                try {
                    File dir = new File(getContext().getCacheDir(), "updates");
                    dir.mkdirs();
                    File apk = new File(dir, "hcg-notes.apk");
                    HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                    c.setInstanceFollowRedirects(true);
                    c.setConnectTimeout(20000);
                    c.setReadTimeout(30000);
                    int total = c.getContentLength(), done = 0, last = -1;
                    try (InputStream in = c.getInputStream(); OutputStream out = new FileOutputStream(apk)) {
                        byte[] buf = new byte[64 * 1024];
                        for (int n; (n = in.read(buf)) > 0; ) {
                            out.write(buf, 0, n);
                            done += n;
                            int pct = total > 0 ? (int) (100L * done / total) : -1;
                            if (pct != last) {
                                last = pct;
                                JSObject p = new JSObject();
                                p.put("percent", pct);
                                notifyListeners("progress", p);
                            }
                        }
                    } finally {
                        c.disconnect();
                    }
                    Uri uri = FileProvider.getUriForFile(getContext(), getContext().getPackageName() + ".fileprovider", apk);
                    Intent open = new Intent(Intent.ACTION_VIEW);
                    open.setDataAndType(uri, "application/vnd.android.package-archive");
                    open.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                    getContext().startActivity(open);
                    JSObject r = new JSObject();
                    r.put("started", true);
                    call.resolve(r);
                } catch (Exception e) {
                    call.reject("download failed: " + e.getMessage());
                }
            }).start();
        }
    }
}
