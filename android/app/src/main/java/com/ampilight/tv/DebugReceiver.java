package com.ampilight.tv;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** adb shell am broadcast -a com.ampilight.tv.SET -n com.ampilight.tv/.DebugReceiver --ei captureMode 2 */
public class DebugReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        Prefs prefs = Prefs.load(context);
        if (intent.hasExtra("captureMode")) {
            prefs.captureMode = Math.max(0, Math.min(Prefs.CAPTURE_PAUSE_MS.length - 1,
                    intent.getIntExtra("captureMode", prefs.captureMode)));
        }
        if (intent.hasExtra("smooth")) prefs.smooth = intent.getIntExtra("smooth", prefs.smooth);
        prefs.save(context);
        long now = android.os.SystemClock.uptimeMillis();
        int max = 0;
        long sum = 0;
        int[] colors = CaptureService.liveColors;
        if (colors != null) {
            for (int c : colors) {
                int v = Math.max((c >> 16) & 0xFF, Math.max((c >> 8) & 0xFF, c & 0xFF));
                max = Math.max(max, v);
                sum += v;
            }
        }
        setResultData("captureMode=" + prefs.captureMode + " smooth=" + prefs.smooth
                + " fps=" + CaptureService.fps + " running=" + CaptureService.running
                + " frameAgo=" + (now - CaptureService.lastColorAt) + "ms sentAgo=" + (now - CaptureService.lastSentAt)
                + "ms max=" + max + " avg=" + (colors == null || colors.length == 0 ? 0 : sum / colors.length)
                + " bright=" + prefs.brightness + " target=" + prefs.target()
                + " status=" + CaptureService.status);
    }
}
