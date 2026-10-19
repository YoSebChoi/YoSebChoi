package io.github.yosebchoi.aptwatch;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.annotation.NonNull;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/**
 * The background listing check: reads each complex's 매매 listing pages (jobs set by the page through
 * AptNet.schedule) and saves them in files for the page to compare when it opens next. It also tells
 * the user when listings that were there last time are gone, the moment a flat may have sold.
 * Requests go one at a time, a couple of seconds apart, a few pages per complex, twice a day.
 */
public class SnapshotWorker extends Worker {
    static final String NAME = "aptwatch-snapshots";
    static final String PREFS = "aptwatch";
    static final String CHANNEL = "listings";
    private static final int KEEP_FILES = 300;

    public SnapshotWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    static boolean allowed(String url) {
        try {
            URL u = new URL(url);
            String h = u.getHost();
            return "https".equals(u.getProtocol()) && (h.equals("land.naver.com") || h.endsWith(".land.naver.com"));
        } catch (Exception e) {
            return false;
        }
    }

    static class Response {
        int status;
        String body;
        String location;
    }

    /** One GET like the mobile site's own page makes. Redirects are not followed: Naver answers a
     *  blocked client with a redirect to an error page, and the caller should see that. */
    static Response get(String url) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setInstanceFollowRedirects(false);
        c.setConnectTimeout(15000);
        c.setReadTimeout(20000);
        c.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36");
        c.setRequestProperty("Accept", "application/json, text/javascript, */*; q=0.01");
        c.setRequestProperty("Accept-Language", "ko-KR,ko;q=0.9");
        c.setRequestProperty("Referer", "https://m.land.naver.com/");
        c.setRequestProperty("X-Requested-With", "XMLHttpRequest");
        try {
            Response r = new Response();
            r.status = c.getResponseCode();
            r.location = c.getHeaderField("Location");
            InputStream in = r.status >= 400 ? c.getErrorStream() : c.getInputStream();
            r.body = in == null ? "" : readAll(in);
            return r;
        } finally {
            c.disconnect();
        }
    }

    static String readAll(InputStream in) throws Exception {
        try (InputStream s = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[32 * 1024];
            for (int n; (n = s.read(buf)) > 0; ) out.write(buf, 0, n);
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }

    static String read(File f) throws Exception {
        return readAll(new FileInputStream(f));
    }

    static File dir(Context ctx) {
        File d = new File(ctx.getFilesDir(), "snapshots");
        //noinspection ResultOfMethodCallIgnored
        d.mkdirs();
        return d;
    }

    @NonNull
    @Override
    public Result doWork() {
        Context ctx = getApplicationContext();
        SharedPreferences prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        JSONArray jobs;
        try {
            jobs = new JSONArray(prefs.getString("jobs", "[]"));
        } catch (Exception e) {
            return Result.success();
        }
        StringBuilder news = new StringBuilder();
        int goneTotal = 0;
        for (int i = 0; i < jobs.length(); i++) {
            JSONObject job = jobs.optJSONObject(i);
            if (job == null) continue;
            String cx = job.optString("cx");
            String url = job.optString("url");
            int maxPages = Math.max(1, Math.min(job.optInt("maxPages", 8), 15));
            JSONObject snap = new JSONObject();
            JSONArray articles = new JSONArray();
            String err = null;
            try {
                for (int page = 1; page <= maxPages; page++) {
                    String pageUrl = url.replace("{page}", String.valueOf(page));
                    if (!allowed(pageUrl)) { err = "not land.naver.com"; break; }
                    if (page > 1 || i > 0) Thread.sleep(1500 + (long) (Math.random() * 1500));
                    Response r = get(pageUrl);
                    if (r.status != 200) {
                        err = "HTTP " + r.status + (r.location != null ? " → " + r.location : "");
                        break;
                    }
                    JSONObject result = new JSONObject(r.body).optJSONObject("result");
                    JSONArray list = result == null ? null : result.optJSONArray("list");
                    if (list == null) { if (page == 1) err = "목록이 없는 답"; break; }
                    for (int k = 0; k < list.length(); k++) articles.put(list.get(k));
                    if (!"Y".equals(result.optString("moreDataYn"))) break;
                }
            } catch (Exception e) {
                err = String.valueOf(e.getMessage());
            }
            long t = System.currentTimeMillis();
            try {
                snap.put("cx", cx);
                snap.put("t", t);
                snap.put("ok", err == null);
                snap.put("articles", err == null ? articles : new JSONArray());
                if (err != null) snap.put("err", err);
                File f = new File(dir(ctx), t + "_" + cx + ".json");
                try (FileOutputStream out = new FileOutputStream(f)) {
                    out.write(snap.toString().getBytes(StandardCharsets.UTF_8));
                }
            } catch (Exception ignored) {
                // a lost snapshot is only a skipped check
            }
            if (err == null && articles.length() > 0) {
                // which articles that were there last time are gone (the page later groups agents' copies
                // of one flat; here it is only the nudge to open the app)
                Set<String> now = new HashSet<>();
                for (int k = 0; k < articles.length(); k++) {
                    JSONObject a = articles.optJSONObject(k);
                    if (a != null) now.add(a.optString("atclNo"));
                }
                String before = prefs.getString("ids_" + cx, null);
                int gone = 0;
                if (before != null && !before.isEmpty()) {
                    for (String id : before.split(",")) if (!now.contains(id)) gone++;
                }
                prefs.edit().putString("ids_" + cx, String.join(",", now)).apply();
                if (gone > 0) {
                    goneTotal += gone;
                    if (news.length() > 0) news.append(", ");
                    news.append(job.optString("name", cx)).append(" ").append(gone).append("건");
                }
            }
        }
        prune(ctx);
        if (goneTotal > 0 && prefs.getBoolean("notify", true)) notifyGone(ctx, news.toString());
        return Result.success();
    }

    private static void prune(Context ctx) {
        File[] files = dir(ctx).listFiles();
        if (files == null || files.length <= KEEP_FILES) return;
        Arrays.sort(files, (a, b) -> a.getName().compareTo(b.getName()));
        for (int i = 0; i < files.length - KEEP_FILES; i++) //noinspection ResultOfMethodCallIgnored
            files[i].delete();
    }

    private static void notifyGone(Context ctx, String text) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "매물 변화", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("지난번에 있던 매물이 안 보일 때");
            ctx.getSystemService(NotificationManager.class).createNotificationChannel(ch);
        }
        Intent open = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName());
        PendingIntent pi = PendingIntent.getActivity(ctx, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder b = new NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_apt)
            .setColor(0xFF2F5D8A)
            .setContentTitle("안 보이는 매물이 있어요")
            .setContentText(text + " — 거래됐는지 열어서 확인해 보세요")
            .setContentIntent(pi)
            .setAutoCancel(true);
        try {
            NotificationManagerCompat.from(ctx).notify(1, b.build());
        } catch (SecurityException ignored) {
            // notifications not allowed: the page shows it on the next opening anyway
        }
    }
}
