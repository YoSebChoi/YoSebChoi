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

/**
 * The background listing check: reads each complex's 매매 listing pages (jobs set by the page through
 * AptNet.schedule) and saves them in files for the page to compare when it opens next. It also tells
 * the user what changed since its last check: flats gone (the moment one may have sold), new flats, price cuts.
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
                    // the complex list answers {result: {list, moreDataYn}}, the map list {body: [...], more}
                    JSONObject body = new JSONObject(r.body);
                    JSONObject result = body.optJSONObject("result");
                    JSONArray list = result != null ? result.optJSONArray("list") : body.optJSONArray("body");
                    if (list == null) { if (page == 1) err = "목록이 없는 답"; break; }
                    for (int k = 0; k < list.length(); k++) {
                        JSONObject a = list.optJSONObject(k);
                        if (a != null && mine(job, a)) articles.put(a);
                    }
                    if (result != null ? !"Y".equals(result.optString("moreDataYn")) : (list.length() < 20 && !body.optBoolean("more"))) break;
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
            if (err == null) {
                String change = compare(prefs, cx, articles);
                if (change != null) {
                    if (news.length() > 0) news.append("\n");
                    news.append(job.optString("name", cx)).append(": ").append(change);
                }
            }
        }
        prune(ctx);
        if (news.length() > 0 && prefs.getBoolean("notify", true)) notifyChanges(ctx, news.toString());
        return Result.success();
    }

    private static void prune(Context ctx) {
        File[] files = dir(ctx).listFiles();
        if (files == null || files.length <= KEEP_FILES) return;
        Arrays.sort(files, (a, b) -> a.getName().compareTo(b.getName()));
        for (int i = 0; i < files.length - KEEP_FILES; i++) //noinspection ResultOfMethodCallIgnored
            files[i].delete();
    }

    /** The map list has the neighbours' listings too: keep this complex's (job.hscpNo / job.only, its name without spaces). */
    static boolean mine(JSONObject job, JSONObject a) {
        String no = job.optString("hscpNo"), only = job.optString("only");
        if (no.isEmpty() && only.isEmpty()) return true;
        if (!no.isEmpty() && no.equals(a.optString("hscpNo"))) return true;
        return !only.isEmpty() && only.equals(a.optString("atclNm").replaceAll("\\s+", "").toLowerCase());
    }

    /** A flat: 동 + floor + 전용면적 + direction, the same grouping as the page (apt/tracker.js), so one
     *  agent re-listing a flat or a second agent adding it is not news. */
    private static String unitKey(JSONObject a) {
        String floor = a.optString("flrInfo").split("/")[0].trim();
        return a.optString("bildNm").trim() + "|" + floor + "|" + a.optString("spc2").trim() + "|" + a.optString("direction").trim();
    }

    /** Compares this check with the last background check of the complex: flats gone, new flats and price
     *  cuts, as "사라짐 1 · 새 매물 2 · 가격 내림 1", or null when nothing changed or this is the first check. */
    static String compare(SharedPreferences prefs, String cx, JSONArray articles) {
        JSONObject now = new JSONObject();
        try {
            for (int k = 0; k < articles.length(); k++) {
                JSONObject a = articles.optJSONObject(k);
                if (a == null) continue;
                String key = unitKey(a);
                long price = a.optLong("prc", 0);
                if (price > 0 && (!now.has(key) || now.getLong(key) == 0 || price < now.getLong(key))) now.put(key, price);
                else if (!now.has(key)) now.put(key, 0);
            }
            String saved = prefs.getString("units_" + cx, null);
            JSONObject before = saved == null ? null : new JSONObject(saved);
            // an empty answer where there were many flats is more likely a block than a sell-out: wait for the next one
            if (before != null && now.length() == 0 && before.length() >= 5) return null;
            prefs.edit().putString("units_" + cx, now.toString()).apply();
            if (before == null) return null;
            int gone = 0, added = 0, cut = 0;
            for (java.util.Iterator<String> it = before.keys(); it.hasNext(); ) if (!now.has(it.next())) gone++;
            for (java.util.Iterator<String> it = now.keys(); it.hasNext(); ) {
                String key = it.next();
                if (!before.has(key)) added++;
                else if (now.getLong(key) > 0 && before.getLong(key) > 0 && now.getLong(key) < before.getLong(key)) cut++;
            }
            StringBuilder b = new StringBuilder();
            if (gone > 0) b.append("사라짐 ").append(gone);
            if (added > 0) b.append(b.length() > 0 ? " · " : "").append("새 매물 ").append(added);
            if (cut > 0) b.append(b.length() > 0 ? " · " : "").append("가격 내림 ").append(cut);
            return b.length() > 0 ? b.toString() : null;
        } catch (Exception e) {
            return null;
        }
    }

    private static void notifyChanges(Context ctx, String text) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "매물 변화", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("매물이 사라지거나, 새로 올라오거나, 가격이 내렸을 때");
            ctx.getSystemService(NotificationManager.class).createNotificationChannel(ch);
        }
        Intent open = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName());
        PendingIntent pi = PendingIntent.getActivity(ctx, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        String first = text.split("\n")[0];
        NotificationCompat.Builder b = new NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_apt)
            .setColor(0xFF2F5D8A)
            .setContentTitle("매물에 변화가 있어요")
            .setContentText(first)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(text + "\n사라진 집은 거래됐을 수 있어요. 열어서 확인해 보세요."))
            .setContentIntent(pi)
            .setAutoCancel(true);
        try {
            NotificationManagerCompat.from(ctx).notify(1, b.build());
        } catch (SecurityException ignored) {
            // notifications not allowed: the page shows the changes on the next opening anyway
        }
    }
}
