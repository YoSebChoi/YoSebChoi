package io.github.yosebchoi.aptwatch;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.OutOfQuotaPolicy;
import androidx.work.WorkManager;

import java.util.Calendar;

/**
 * The morning summary at its time. A WorkManager delay alone waits for the phone to wake up (on a
 * sleeping phone that was "when the app is opened"), so an alarm wakes it at the set time and starts
 * the check as expedited work; the alarm is set again after a restart or an update.
 */
public class DailyAlarm extends BroadcastReceiver {
    static final String ACTION = "io.github.yosebchoi.aptwatch.DAILY";

    @Override
    public void onReceive(Context ctx, Intent intent) {
        if (ACTION.equals(intent.getAction())) {
            WorkManager.getInstance(ctx).enqueueUniqueWork(SnapshotWorker.DAILY_NOW, ExistingWorkPolicy.REPLACE,
                new OneTimeWorkRequest.Builder(SnapshotWorker.class)
                    .setInputData(new Data.Builder().putBoolean("daily", true).build())
                    .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                    .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                    .build());
        }
        // the alarm fired, the phone restarted or the app was updated: set the next one
        arm(ctx);
    }

    private static PendingIntent pending(Context ctx) {
        Intent i = new Intent(ctx, DailyAlarm.class).setAction(ACTION);
        return PendingIntent.getBroadcast(ctx, 9, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    /** Whether the alarm can be exact (Android 12+ may need 「알람 및 리마인더」 allowed for the app). */
    static boolean exact(Context ctx) {
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms();
    }

    /** Sets the alarm for the next morning summary (prefs daily_on, daily_hour, daily_minute), or cancels it. */
    static void arm(Context ctx) {
        SharedPreferences prefs = ctx.getSharedPreferences(SnapshotWorker.PREFS, Context.MODE_PRIVATE);
        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pi = pending(ctx);
        if (!prefs.getBoolean("daily_on", true)) {
            am.cancel(pi);
            prefs.edit().putLong("daily_next", 0).apply();
            return;
        }
        Calendar next = Calendar.getInstance();
        next.set(Calendar.HOUR_OF_DAY, prefs.getInt("daily_hour", 9));
        next.set(Calendar.MINUTE, prefs.getInt("daily_minute", 0));
        next.set(Calendar.SECOND, 0);
        next.set(Calendar.MILLISECOND, 0);
        if (next.getTimeInMillis() <= System.currentTimeMillis() + 60_000) next.add(Calendar.DAY_OF_MONTH, 1);
        long at = next.getTimeInMillis();
        try {
            if (exact(ctx)) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
        } catch (SecurityException e) {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi);
        }
        prefs.edit().putLong("daily_next", at).putBoolean("daily_exact", exact(ctx)).apply();
    }
}
