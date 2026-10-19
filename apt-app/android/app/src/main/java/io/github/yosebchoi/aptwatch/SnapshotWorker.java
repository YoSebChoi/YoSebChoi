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
import java.net.CookieHandler;
import java.net.CookieManager;
import java.net.CookiePolicy;
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

    /** Cookies like a browser keeps them (Naver's article lists can answer nothing to a client without them). */
    static synchronized void cookies() {
        if (!(CookieHandler.getDefault() instanceof CookieManager))
            CookieHandler.setDefault(new CookieManager(null, CookiePolicy.ACCEPT_ALL));
    }

    /** One GET like the mobile site's own page makes. */
    static Response get(String url) throws Exception {
        return send(url, "GET", null, null);
    }

    /** One request like the site's own page makes (GET, or POST with a JSON body). Redirects are not followed:
     *  Naver answers a blocked client with a redirect to an error page, and the caller should see that. */
    static Response send(String url, String method, String body, JSONObject headers) throws Exception {
        cookies();
        URL u = new URL(url);
        boolean fin = u.getHost().startsWith("fin.");
        HttpURLConnection c = (HttpURLConnection) u.openConnection();
        c.setInstanceFollowRedirects(false);
        c.setConnectTimeout(15000);
        c.setReadTimeout(20000);
        c.setRequestMethod(method == null ? "GET" : method);
        c.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36");
        c.setRequestProperty("Accept", "application/json, text/javascript, */*; q=0.01");
        c.setRequestProperty("Accept-Language", "ko-KR,ko;q=0.9");
        c.setRequestProperty("Referer", fin ? "https://fin.land.naver.com/" : "https://m.land.naver.com/");
        if (fin) c.setRequestProperty("Origin", "https://fin.land.naver.com");
        else c.setRequestProperty("X-Requested-With", "XMLHttpRequest");
        if (headers != null) {
            for (java.util.Iterator<String> it = headers.keys(); it.hasNext(); ) {
                String k = it.next();
                c.setRequestProperty(k, headers.optString(k));
            }
        }
        if (body != null) {
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            try (java.io.OutputStream out = c.getOutputStream()) { out.write(body.getBytes(StandardCharsets.UTF_8)); }
        }
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

    /** A value inside a JSON answer by a dotted path ("result.list", "a.0.b"); several paths separated by "|"
     *  give the first that is there. */
    static Object path(Object o, String spec) {
        if (spec == null || spec.isEmpty()) return null;
        for (String p : spec.split("\\|")) {
            Object v = o;
            for (String k : p.split("\\.")) {
                if (v instanceof JSONObject) v = ((JSONObject) v).opt(k);
                else if (v instanceof JSONArray && k.matches("\\d+")) v = ((JSONArray) v).opt(Integer.parseInt(k));
                else { v = null; break; }
                if (v == JSONObject.NULL) v = null;
            }
            if (v != null) return v;
        }
        return null;
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
        JSONArray runLog = new JSONArray();
        prefs.edit().putLong("last_start", System.currentTimeMillis()).apply();
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
                // a page to open first, for the cookies the site's own page would have
                if (!job.optString("seed").isEmpty() && allowed(job.optString("seed"))) {
                    get(job.optString("seed"));
                    Thread.sleep(800 + (long) (Math.random() * 800));
                }
                JSONObject body = job.optJSONObject("body");
                JSONObject map = job.optJSONObject("map");
                for (int page = 1; page <= maxPages; page++) {
                    String pageUrl = url.replace("{page}", String.valueOf(page));
                    if (!allowed(pageUrl)) { err = "not land.naver.com"; break; }
                    if (page > 1 || i > 0) Thread.sleep(1500 + (long) (Math.random() * 1500));
                    Response r = send(pageUrl, job.optString("method", "GET"), body == null ? null : body.toString(), job.optJSONObject("headers"));
                    if (r.status != 200) {
                        err = "HTTP " + r.status + (r.location != null ? " → " + r.location : "");
                        break;
                    }
                    Object parsed = new org.json.JSONTokener(r.body).nextValue();
                    if (!(parsed instanceof JSONObject)) { if (page == 1) err = "목록이 없는 답: " + r.body.substring(0, Math.min(60, r.body.length())); break; }
                    JSONObject answer = (JSONObject) parsed;
                    JSONArray list;
                    boolean more;
                    if (!job.optString("listPath").isEmpty()) {
                        // a list described by the page (the new fin.land list): where the list, the next-page flag and the cursor are
                        Object l = path(answer, job.optString("listPath"));
                        list = l instanceof JSONArray ? (JSONArray) l : null;
                        more = Boolean.TRUE.equals(path(answer, job.optString("nextPath")));
                        Object cursor = path(answer, job.optString("cursorPath"));
                        if (more && cursor != null && body != null) body.put(job.optString("cursorKey", "lastInfo"), cursor);
                        else more = false;
                    } else {
                        // the complex list answers {result: {list, moreDataYn}}, the map list {body: [...], more}
                        JSONObject result = answer.optJSONObject("result");
                        list = result != null ? result.optJSONArray("list") : answer.optJSONArray("body");
                        more = result != null ? "Y".equals(result.optString("moreDataYn")) : list != null && (list.length() >= 20 || answer.optBoolean("more"));
                    }
                    if (list == null) { if (page == 1) err = "목록이 없는 답"; break; }
                    for (int k = 0; k < list.length(); k++) {
                        JSONObject a = list.optJSONObject(k);
                        if (a == null) continue;
                        if (map != null) a = convert(a, map, job.optDouble("priceDiv", 1));
                        if (mine(job, a)) articles.put(a);
                    }
                    if (!more) break;
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
            String change = null;
            if (err == null) {
                change = compare(prefs, cx, articles);
                if (change != null) {
                    if (news.length() > 0) news.append("\n");
                    news.append(job.optString("name", cx)).append(": ").append(change);
                }
            }
            try {
                runLog.put(new JSONObject().put("name", job.optString("name", cx)).put("ok", err == null)
                    .put("count", articles.length()).put("err", err == null ? "" : err).put("change", change == null ? "" : change));
            } catch (Exception ignored) {
                // the log is only for 설정
            }
        }
        prune(ctx);
        boolean want = news.length() > 0 && prefs.getBoolean("notify", true);
        String text = news.toString();
        // a test run (설정 → 백그라운드 확인부터 알림까지 시험) always reports, even with no change or an error
        if (prefs.getBoolean("test_pending", false)) {
            prefs.edit().putBoolean("test_pending", false).apply();
            StringBuilder t = new StringBuilder("시험 결과\n");
            for (int k = 0; k < runLog.length(); k++) {
                JSONObject r = runLog.optJSONObject(k);
                if (r == null) continue;
                t.append(r.optString("name")).append(": ");
                if (!r.optBoolean("ok")) t.append("오류 ").append(r.optString("err"));
                else t.append("매물 ").append(r.optInt("count")).append("건 읽음")
                    .append(r.optString("change").isEmpty() ? " · 변화 없음(첫 확인이면 기준만 잡아요)" : " · " + r.optString("change"));
                t.append("\n");
            }
            if (jobs.length() == 0) t.append("확인할 단지가 없어요 (앱에서 단지를 연결하고 한 번 열어 주세요)");
            text = t.toString().trim();
            want = true;
        }
        boolean sent = want && notifyChanges(ctx, text);
        // what this run did, for 설정 → 백그라운드 확인 (AptNet.workerStatus)
        try {
            prefs.edit().putString("last_run", new JSONObject().put("t", System.currentTimeMillis()).put("jobs", runLog)
                .put("wanted", want).put("sent", sent).put("enabled", notificationsOn(ctx)).toString()).apply();
        } catch (Exception ignored) {
            // the log is only for 설정
        }
        return Result.success();
    }

    private static void prune(Context ctx) {
        File[] files = dir(ctx).listFiles();
        if (files == null || files.length <= KEEP_FILES) return;
        Arrays.sort(files, (a, b) -> a.getName().compareTo(b.getName()));
        for (int i = 0; i < files.length - KEEP_FILES; i++) //noinspection ResultOfMethodCallIgnored
            files[i].delete();
    }

    /** A listing in another shape → the fields the page and the comparison use (map: field → path). */
    static JSONObject convert(JSONObject item, JSONObject map, double priceDiv) throws Exception {
        JSONObject out = new JSONObject();
        for (java.util.Iterator<String> it = map.keys(); it.hasNext(); ) {
            String k = it.next();
            Object v = path(item, map.optString(k));
            if (v == null) continue;
            if (k.equals("prc") && v instanceof Number && priceDiv > 1) v = Math.round(((Number) v).doubleValue() / priceDiv);
            out.put(k, v);
        }
        if (!out.has("tradTpCd")) out.put("tradTpCd", "A1");
        return out;
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

    /** Whether this app may show notifications and the 「매물 변화」 channel is not turned off. */
    static boolean notificationsOn(Context ctx) {
        if (!NotificationManagerCompat.from(ctx).areNotificationsEnabled()) return false;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = ctx.getSystemService(NotificationManager.class).getNotificationChannel(CHANNEL);
            if (ch != null && ch.getImportance() == NotificationManager.IMPORTANCE_NONE) return false;
        }
        return true;
    }

    static boolean notifyChanges(Context ctx, String text) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "매물 변화", NotificationManager.IMPORTANCE_DEFAULT);
            ch.setDescription("매물이 사라지거나, 새로 올라오거나, 가격이 내렸을 때");
            ctx.getSystemService(NotificationManager.class).createNotificationChannel(ch);
        }
        Intent open = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName());
        PendingIntent pi = PendingIntent.getActivity(ctx, 0, open, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        boolean test = text.startsWith("시험 결과");
        String[] lines = text.split("\n");
        String first = test && lines.length > 1 ? lines[1] : lines[0];
        NotificationCompat.Builder b = new NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_apt)
            .setColor(0xFF2F5D8A)
            .setContentTitle(test ? "백그라운드 확인 시험" : "매물에 변화가 있어요")
            .setContentText(first)
            .setStyle(new NotificationCompat.BigTextStyle().bigText(test ? text : text + "\n사라진 집은 거래됐을 수 있어요. 열어서 확인해 보세요."))
            .setContentIntent(pi)
            .setAutoCancel(true);
        try {
            NotificationManagerCompat.from(ctx).notify(1, b.build());
            return notificationsOn(ctx);
        } catch (SecurityException ignored) {
            // notifications not allowed: the page shows the changes on the next opening anyway
        }
        return false;
    }
}
