package io.github.yosebchoi.aptwatch;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;

import androidx.core.content.FileProvider;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import com.getcapacitor.BridgeActivity;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.TimeUnit;

public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(NetPlugin.class);
        registerPlugin(UpdatePlugin.class);
        super.onCreate(savedInstanceState);
    }

    /**
     * Naver 부동산 from the phone. The page cannot read land.naver.com itself (another site), so it asks here:
     *  - AptNet.get({url}) → {status, body, location}: one request, only to *.land.naver.com.
     *  - AptNet.schedule({jobs:[{cx, name, url, maxPages}], hours, notify}) → the background check (SnapshotWorker)
     *    reads those listing pages every `hours` hours while the app is closed (hours 0 stops it) and, with notify,
     *    tells the user when flats are gone, new or cheaper than at its last check.
     *  - AptNet.runNow() → one background check right away (for testing the schedule).
     *  - AptNet.collect() → {snapshots:[{cx, t, ok, articles, err}]}: what the background checks saved,
     *    handed over once (the page compares them in order, as if it had fetched them itself).
     * Nothing is sent anywhere else: the listings stay on this phone.
     */
    @CapacitorPlugin(name = "AptNet")
    public static class NetPlugin extends Plugin {
        @PluginMethod
        public void get(PluginCall call) {
            String url = call.getString("url");
            if (!SnapshotWorker.allowed(url)) {
                call.reject("only land.naver.com");
                return;
            }
            new Thread(() -> {
                try {
                    SnapshotWorker.Response r = SnapshotWorker.get(url);
                    JSObject o = new JSObject();
                    o.put("status", r.status);
                    o.put("body", r.body);
                    o.put("location", r.location);
                    call.resolve(o);
                } catch (Exception e) {
                    call.reject("network: " + e.getMessage());
                }
            }).start();
        }

        @PluginMethod
        public void schedule(PluginCall call) {
            JSArray jobs = call.getArray("jobs", new JSArray());
            int hours = call.getInt("hours", 12);
            Context ctx = getContext();
            ctx.getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE).edit()
                .putString("jobs", jobs.toString())
                .putBoolean("notify", call.getBoolean("notify", true))
                .apply();
            WorkManager wm = WorkManager.getInstance(ctx);
            if (hours <= 0 || jobs.length() == 0) {
                wm.cancelUniqueWork(SnapshotWorker.NAME);
            } else {
                PeriodicWorkRequest req = new PeriodicWorkRequest.Builder(SnapshotWorker.class, Math.max(hours, 1), TimeUnit.HOURS)
                    .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                    .setInitialDelay(Math.max(hours, 1), TimeUnit.HOURS)
                    .build();
                wm.enqueueUniquePeriodicWork(SnapshotWorker.NAME, ExistingPeriodicWorkPolicy.UPDATE, req);
            }
            call.resolve();
        }

        @PluginMethod
        public void runNow(PluginCall call) {
            WorkManager.getInstance(getContext()).enqueue(new OneTimeWorkRequest.Builder(SnapshotWorker.class)
                .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build());
            call.resolve();
        }

        @PluginMethod
        public void collect(PluginCall call) {
            JSArray out = new JSArray();
            File dir = SnapshotWorker.dir(getContext());
            File[] files = dir.listFiles();
            if (files != null) {
                java.util.Arrays.sort(files, (a, b) -> a.getName().compareTo(b.getName()));
                for (File f : files) {
                    try {
                        out.put(new JSONObject(SnapshotWorker.read(f)));
                    } catch (Exception ignored) {
                        // a half-written file from a killed worker: drop it
                    }
                    //noinspection ResultOfMethodCallIgnored
                    f.delete();
                }
            }
            JSObject r = new JSObject();
            r.put("snapshots", out);
            call.resolve(r);
        }
    }

    /**
     * In-app update: the page finds a newer build on the GitHub release and calls
     * AptUpdate.install({url}); the APK is downloaded into the cache and handed to
     * Android's installer, which installs it over this app (same key, saved records kept).
     * Progress arrives as "progress" events ({percent}).
     */
    @CapacitorPlugin(name = "AptUpdate")
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
                    File apk = new File(dir, "apt-watch.apk");
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
