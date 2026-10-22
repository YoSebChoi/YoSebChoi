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
     *  - AptNet.get({url}) → {status, body, location}: one request, only to *.land.naver.com (cookies kept like a browser).
     *  - AptNet.request({url, method, body, headers}) → the same, also POST with a JSON body.
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

        /** AptNet.request({url, method, body, headers}) → {status, body, location}: like get, also POST with a JSON body
         *  (the new fin.land lists are read that way). */
        @PluginMethod
        public void request(PluginCall call) {
            String url = call.getString("url");
            if (!SnapshotWorker.allowed(url)) {
                call.reject("only land.naver.com");
                return;
            }
            String method = call.getString("method", "GET");
            JSObject body = call.getObject("body", null);
            JSObject headers = call.getObject("headers", null);
            new Thread(() -> {
                try {
                    SnapshotWorker.Response r = SnapshotWorker.send(url, method, body == null ? null : body.toString(), headers);
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

        /** AptNet.daily({on, hour, minute}) → {next}: the morning summary, every day at that time (9:00 by default),
         *  with or without changes; next is when the next one is booked (ms). */
        @PluginMethod
        public void daily(PluginCall call) {
            Context ctx = getContext();
            ctx.getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE).edit()
                .putBoolean("daily_on", call.getBoolean("on", true))
                .putInt("daily_hour", call.getInt("hour", 9))
                .putInt("daily_minute", call.getInt("minute", 0)).apply();
            SnapshotWorker.scheduleDaily(ctx);
            JSObject r = new JSObject();
            r.put("next", ctx.getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE).getLong("daily_next", 0));
            r.put("exact", DailyAlarm.exact(ctx));
            r.put("battery", ((android.os.PowerManager) ctx.getSystemService(Context.POWER_SERVICE)).isIgnoringBatteryOptimizations(ctx.getPackageName()));
            call.resolve(r);
        }

        /** AptNet.askPower({what}) → opens the setting that lets the morning summary come on time:
         *  "battery" (leave this app out of battery optimisation) or "alarm" (allow exact alarms, Android 12+). */
        @PluginMethod
        public void askPower(PluginCall call) {
            Context ctx = getContext();
            Intent open;
            if ("alarm".equals(call.getString("what")) && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                open = new Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:" + ctx.getPackageName()));
            } else {
                open = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + ctx.getPackageName()));
            }
            open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try { ctx.startActivity(open); }
            catch (Exception e) {
                Intent app = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + ctx.getPackageName()));
                app.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                ctx.startActivity(app);
            }
            call.resolve();
        }

        /** AptNet.testNotify({text}) → {sent}: the change notification right away, as the background check posts it. */
        @PluginMethod
        public void testNotify(PluginCall call) {
            boolean sent = SnapshotWorker.notifyChanges(getContext(), call.getString("text", "시험 알림: 이렇게 와요"));
            JSObject r = notifyState();
            r.put("sent", sent);
            call.resolve(r);
        }

        private JSObject notifyState() {
            Context ctx = getContext();
            JSObject r = new JSObject();
            boolean perm = Build.VERSION.SDK_INT < 33
                || androidx.core.content.ContextCompat.checkSelfPermission(ctx, "android.permission.POST_NOTIFICATIONS") == android.content.pm.PackageManager.PERMISSION_GRANTED;
            r.put("permission", perm);
            r.put("enabled", SnapshotWorker.notificationsOn(ctx));
            return r;
        }

        /** AptNet.notifyStatus() → {permission, enabled}: may this app notify, and is the 「매물 변화」 channel on. */
        @PluginMethod
        public void notifyStatus(PluginCall call) {
            call.resolve(notifyState());
        }

        /** AptNet.askNotify() → asks Android for the notification permission (Android 13+) the first time, and opens
         *  this app's notification settings when it was refused or a channel is off. */
        @PluginMethod
        public void askNotify(PluginCall call) {
            JSObject st = notifyState();
            JSObject r = new JSObject();
            if (!st.getBool("permission") && !prefsAsked()) {
                getContext().getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE).edit().putBoolean("asked_notify", true).apply();
                androidx.core.app.ActivityCompat.requestPermissions(getActivity(), new String[]{"android.permission.POST_NOTIFICATIONS"}, 7001);
                r.put("asked", true);
            } else if (!st.getBool("enabled")) {
                Intent open = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
                open.putExtra(Settings.EXTRA_APP_PACKAGE, getContext().getPackageName());
                open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                getContext().startActivity(open);
                r.put("opened", true);
            }
            call.resolve(r);
        }

        private boolean prefsAsked() {
            return getContext().getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE).getBoolean("asked_notify", false);
        }

        /** AptNet.workerStatus() → {start, last}: when the background check last started, and what its last run did. */
        @PluginMethod
        public void workerStatus(PluginCall call) {
            android.content.SharedPreferences prefs = getContext().getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE);
            JSObject r = new JSObject();
            r.put("start", prefs.getLong("last_start", 0));
            try { r.put("last", new JSONObject(prefs.getString("last_run", "{}"))); } catch (Exception e) { r.put("last", new JSONObject()); }
            call.resolve(r);
        }

        /** AptNet.testChange() → {complexes}: forgets one flat from each complex's last background check and runs
         *  a check now, so that check finds 「새 매물 1」 and notifies: the whole path, end to end. complexes is how
         *  many had a last check to change (0: the background check has not run yet). */
        @PluginMethod
        public void testChange(PluginCall call) {
            android.content.SharedPreferences prefs = getContext().getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE);
            android.content.SharedPreferences.Editor edit = prefs.edit();
            int n = 0;
            for (String key : prefs.getAll().keySet()) {
                if (!key.startsWith("units_")) continue;
                try {
                    JSONObject units = new JSONObject(prefs.getString(key, "{}"));
                    java.util.Iterator<String> it = units.keys();
                    if (!it.hasNext()) continue;
                    units.remove(it.next());
                    edit.putString(key, units.toString());
                    n++;
                } catch (Exception ignored) {
                    // a broken record: the next check writes a new one
                }
            }
            edit.putBoolean("notify", true).putBoolean("test_pending", true).apply();
            WorkManager.getInstance(getContext()).enqueue(new OneTimeWorkRequest.Builder(SnapshotWorker.class)
                .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).build());
            JSObject r = new JSObject();
            r.put("complexes", n);
            call.resolve(r);
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
