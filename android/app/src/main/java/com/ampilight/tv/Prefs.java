package com.ampilight.tv;

import android.content.Context;
import android.content.SharedPreferences;

/** Все настройки приложения. Хранятся между запусками. */
public final class Prefs {
    public static final String FILE = "ampilight";

    public int top;
    public int right;
    public int bottom;
    public int left;
    public int loops;
    public int brightness;
    public int corner;
    public boolean clockwise;
    public int depth;
    public int smooth;
    public String host;
    public int boardLeds;
    public String manualIp;
    /** Сколько выдаёт блок питания ленты, А. 0 — без ограничения. */
    public int supplyAmps;
    /** Индекс в CAPTURE_PAUSE_MS: как часто подключаться к экрану. */
    public int captureMode;

    public static final String[] CAPTURE_NAMES = {"Непрерывно", "20 раз в сек", "12 раз в сек", "6 раз в сек",
            "2 раза в сек", "1 раз в сек", "Импульс 10 в сек", "Импульс 4 в сек", "Импульс 2 в сек"};
    public static final long[] CAPTURE_PAUSE_MS = {0, 35, 70, 150, 480, 980, 80, 230, 480};
    /** С этого индекса зеркало экрана удаляется между снимками целиком. */
    public static final int CAPTURE_PULSE_FROM = 6;

    public static SharedPreferences store(Context context) {
        return context.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public static Prefs load(Context context) {
        SharedPreferences sp = store(context);
        Prefs p = new Prefs();
        p.top = sp.getInt("top", 28);
        p.right = sp.getInt("right", 17);
        p.bottom = sp.getInt("bottom", 28);
        p.left = sp.getInt("left", 17);
        p.loops = sp.getInt("loops", 1);
        p.brightness = sp.getInt("brightness", 60);
        p.corner = sp.getInt("corner", LedLayout.BOTTOM_LEFT);
        p.clockwise = sp.getBoolean("clockwise", true);
        p.depth = sp.getInt("depth", 15);
        p.smooth = sp.getInt("smooth", 50);
        p.host = sp.getString("host", "");
        p.boardLeds = sp.getInt("boardLeds", 0);
        p.manualIp = sp.getString("manualIp", "");
        p.supplyAmps = sp.getInt("supplyAmps", 3);
        p.captureMode = Math.max(0, Math.min(CAPTURE_PAUSE_MS.length - 1, sp.getInt("captureMode", 3)));
        return p;
    }

    public void save(Context context) {
        store(context).edit()
                .putInt("top", top)
                .putInt("right", right)
                .putInt("bottom", bottom)
                .putInt("left", left)
                .putInt("loops", loops)
                .putInt("brightness", brightness)
                .putInt("corner", corner)
                .putBoolean("clockwise", clockwise)
                .putInt("depth", depth)
                .putInt("smooth", smooth)
                .putString("host", host)
                .putInt("boardLeds", boardLeds)
                .putString("manualIp", manualIp)
                .putInt("supplyAmps", supplyAmps)
                .putInt("captureMode", captureMode)
                .apply();
    }

    /** Предел тока для ленты, мА; 10% запаса от блока питания. */
    public int maxMilliamps() {
        return supplyAmps <= 0 ? 0 : supplyAmps * 900;
    }

    public LedLayout layout() {
        return new LedLayout(top, right, bottom, left, corner, clockwise);
    }

    /** Куда слать цвета: адрес, заданный вручную, иначе найденный поиском. */
    public String target() {
        return manualIp != null && !manualIp.trim().isEmpty() ? manualIp.trim() : host;
    }

    /** Сколько диодов в пакете: столько, на сколько прошита плата, иначе по раскладке. */
    public int outputLeds() {
        if (boardLeds > 0) return boardLeds;
        return layout().perimeter() * Math.max(1, loops);
    }
}
