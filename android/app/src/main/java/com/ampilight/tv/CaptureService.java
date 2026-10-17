package com.ampilight.tv;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.SystemClock;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.nio.ByteBuffer;

/** Фоновый захват экрана: края кадра → цвета диодов → UDP на плату. */
public class CaptureService extends Service {
    public static final String ACTION_START = "com.ampilight.tv.START";
    public static final String ACTION_STOP = "com.ampilight.tv.STOP";
    public static final String EXTRA_CODE = "code";
    public static final String EXTRA_DATA = "data";

    private static final String CHANNEL = "ampilight";
    private static final int NOTIFY_ID = 1;
    private static final int CAPTURE_WIDTH = 128;
    private int captureWidth;
    private int captureHeight;
    private int framesSinceCreate;
    private static final long FRAME_MS = 33;
    private static final long RESEND_MS = 400;

    public static volatile boolean running;
    public static volatile int[] liveColors;
    public static volatile long lastColorAt;
    public static volatile long lastSentAt;
    public static volatile String status = "";
    public static volatile int fps;
    /** Ответила ли плата на последнюю проверку. */
    public static volatile boolean boardOnline = true;

    private static final long WATCH_MS = 6000;
    private HandlerThread watchThread;
    private Handler watchHandler;

    /** Раз в несколько секунд: плата на месте? Если сменила адрес — переключаемся на новый. */
    private final Runnable watch = new Runnable() {
        @Override
        public void run() {
            Prefs p = Prefs.load(CaptureService.this);
            String host = p.target();
            boolean ok = host != null && !host.isEmpty() && Board.alive(host, 900);
            if (!ok && (p.manualIp == null || p.manualIp.isEmpty())) {
                java.util.List<Board.Found> found = Board.discover(1500);
                if (!found.isEmpty()) {
                    Board.Found f = found.get(0);
                    p.host = f.ip;
                    if (f.leds > 0) p.boardLeds = f.leds;
                    p.save(CaptureService.this);
                    ok = true;
                }
            }
            boardOnline = ok;
            watchHandler.postDelayed(this, WATCH_MS);
        }
    };

    private HandlerThread thread;
    private Handler handler;
    private MediaProjection projection;
    private VirtualDisplay display;
    private ImageReader reader;
    private DatagramSocket socket;
    private InetAddress target;
    private final EdgeSampler sampler = new EdgeSampler();
    private Prefs prefs;
    private LedLayout layout;
    private volatile boolean dirty = true;
    private float[] smoothed;
    private byte[] frameBytes;
    private byte[] lastPacket;
    private long lastFrameAt;
    private long fpsWindowAt;
    private int fpsFrames;

    private final SharedPreferences.OnSharedPreferenceChangeListener prefsListener =
            (sp, key) -> dirty = true;

    private static int clampEven(int value, int min, int max) {
        int v = Math.max(min, Math.min(max, value));
        return v + (v & 1);
    }

    private final Runnable reattach = () -> {
        if (display == null) createDisplay();
        else if (reader != null) display.setSurface(reader.getSurface());
    };

    private final Runnable recreate = () -> {
        if (display == null) createDisplay();
    };

    private void createDisplay() {
        if (projection == null || reader == null) return;
        framesSinceCreate = 0;
        display = projection.createVirtualDisplay("ampilight", captureWidth, captureHeight, 120,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, handler);
    }

    private final Runnable resend = new Runnable() {
        @Override
        public void run() {
            if (lastPacket != null && SystemClock.uptimeMillis() - lastFrameAt > RESEND_MS) {
                send(lastPacket);
            }
            handler.postDelayed(this, RESEND_MS);
        }
    };

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || ACTION_STOP.equals(intent.getAction())) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (projection != null) return START_NOT_STICKY;
        startInForeground();
        int code = intent.getIntExtra(EXTRA_CODE, 0);
        Intent data = intentExtra(intent);
        MediaProjectionManager manager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        try {
            projection = manager.getMediaProjection(code, data);
        } catch (Exception e) {
            projection = null;
        }
        if (projection == null) {
            status = "Телевизор не дал доступ к экрану";
            stopSelf();
            return START_NOT_STICKY;
        }
        begin();
        return START_NOT_STICKY;
    }

    @SuppressWarnings("deprecation")
    private static Intent intentExtra(Intent intent) {
        if (Build.VERSION.SDK_INT >= 33) return intent.getParcelableExtra(EXTRA_DATA, Intent.class);
        return intent.getParcelableExtra(EXTRA_DATA);
    }

    private void startInForeground() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Подсветка", NotificationManager.IMPORTANCE_LOW));
        Intent stop = new Intent(this, CaptureService.class).setAction(ACTION_STOP);
        PendingIntent stopPending = PendingIntent.getService(this, 0, stop, PendingIntent.FLAG_IMMUTABLE);
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent openPending = PendingIntent.getActivity(this, 0, open, PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_notify)
                .setContentTitle("Ampilight")
                .setContentText("Подсветка работает")
                .setOngoing(true)
                .setContentIntent(openPending)
                .addAction(new Notification.Action.Builder(null, "Стоп", stopPending).build())
                .build();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFY_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
        } else {
            startForeground(NOTIFY_ID, notification);
        }
    }

    @SuppressWarnings("deprecation")
    private void begin() {
        thread = new HandlerThread("ampilight-capture");
        thread.start();
        handler = new Handler(thread.getLooper());
        Prefs.store(this).registerOnSharedPreferenceChangeListener(prefsListener);

        // Чем меньше кадр захвата, тем меньше работы видеокарте ТВ: по 2 точки на диод хватает.
        Prefs p = Prefs.load(this);
        int width = clampEven(Math.max(p.top, p.bottom) * 2, 16, CAPTURE_WIDTH);
        int height = clampEven(Math.max(p.left, p.right) * 2, 10, CAPTURE_WIDTH);

        projection.registerCallback(new MediaProjection.Callback() {
            @Override
            public void onStop() {
                stopSelf();
            }
        }, handler);
        reader = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 2);
        reader.setOnImageAvailableListener(this::onImage, handler);
        captureWidth = width;
        captureHeight = height;
        createDisplay();
        running = true;
        status = "Подсветка работает";
        handler.post(resend);
        boardOnline = true;
        watchThread = new HandlerThread("ampilight-watch");
        watchThread.start();
        watchHandler = new Handler(watchThread.getLooper());
        watchHandler.postDelayed(watch, 2000);
    }

    private void reload() {
        dirty = false;
        prefs = Prefs.load(this);
        layout = prefs.layout();
        smoothed = null;
        target = null;
        String host = prefs.target();
        if (host == null || host.isEmpty()) {
            status = "Плата не найдена. Нажми на строку платы, чтобы искать.";
            return;
        }
        try {
            target = InetAddress.getByName(host);
            if (socket == null) socket = new DatagramSocket();
            status = "Подсветка работает → " + host;
        } catch (Exception e) {
            status = "Нет связи с " + host;
        }
    }

    private void onImage(ImageReader r) {
        Image image;
        try {
            image = r.acquireLatestImage();
        } catch (Exception e) {
            return;
        }
        if (image == null) return;
        try {
            long now = SystemClock.uptimeMillis();
            if (dirty) reload();
            long pause = prefs != null ? Prefs.CAPTURE_PAUSE_MS[prefs.captureMode] : 0;
            if (pause > 0 && prefs.captureMode >= Prefs.CAPTURE_PULSE_FROM) {
                // Первый кадр нового зеркала бывает пустым (чёрным) — лента от него мигает.
                if (++framesSinceCreate < 2) return;
                // На MediaTek-ТВ само существование зеркала переводит видео на медленный путь,
                // поэтому между снимками зеркало удаляем целиком.
                if (display != null) {
                    display.release();
                    display = null;
                }
                handler.postDelayed(recreate, pause);
            } else if (pause > 0) {
                // Пока к экрану подключён захват, слабые ТВ-чипы собирают весь экран через GPU
                // и видео дёргается. Берём один кадр и отключаемся до следующего.
                if (display != null) display.setSurface(null);
                handler.postDelayed(reattach, pause);
            } else if (now - lastFrameAt < FRAME_MS) {
                return;
            }
            if (layout == null || layout.perimeter() == 0) return;
            Image.Plane plane = image.getPlanes()[0];
            ByteBuffer buffer = plane.getBuffer();
            int size = buffer.remaining();
            if (frameBytes == null || frameBytes.length != size) frameBytes = new byte[size];
            buffer.get(frameBytes);
            int[] colors = sampler.sample(frameBytes, image.getWidth(), image.getHeight(),
                    plane.getRowStride(), layout, prefs.depth);
            colors = smooth(colors, prefs.smooth / 100f * 0.85f);
            liveColors = colors;
            lastColorAt = now;
            lastPacket = Board.packet(colors, prefs.outputLeds(), prefs.brightness / 100f, prefs.maxMilliamps());
            send(lastPacket);
            lastFrameAt = now;
            countFps(now);
        } finally {
            image.close();
        }
    }

    private int[] smooth(int[] colors, float keep) {
        if (smoothed == null || smoothed.length != colors.length * 3) {
            smoothed = new float[colors.length * 3];
            keep = 0f;
        }
        int[] out = new int[colors.length];
        for (int i = 0; i < colors.length; i++) {
            int c = colors[i];
            float r = smoothed[i * 3] * keep + ((c >> 16) & 0xFF) * (1 - keep);
            float g = smoothed[i * 3 + 1] * keep + ((c >> 8) & 0xFF) * (1 - keep);
            float b = smoothed[i * 3 + 2] * keep + (c & 0xFF) * (1 - keep);
            smoothed[i * 3] = r;
            smoothed[i * 3 + 1] = g;
            smoothed[i * 3 + 2] = b;
            out[i] = Math.round(r) << 16 | Math.round(g) << 8 | Math.round(b);
        }
        return out;
    }

    private void countFps(long now) {
        fpsFrames++;
        if (now - fpsWindowAt >= 1000) {
            fps = fpsFrames;
            fpsFrames = 0;
            fpsWindowAt = now;
        }
    }

    private void send(byte[] packet) {
        if (socket == null || target == null) return;
        try {
            socket.send(new DatagramPacket(packet, packet.length, target, Board.PORT));
            lastSentAt = SystemClock.uptimeMillis();
        } catch (Exception e) {
            status = "Ошибка отправки: " + e.getMessage();
        }
    }

    @Override
    public void onDestroy() {
        running = false;
        liveColors = null;
        fps = 0;
        Prefs.store(this).unregisterOnSharedPreferenceChangeListener(prefsListener);
        if (watchHandler != null) {
            watchHandler.removeCallbacksAndMessages(null);
            watchThread.quitSafely();
        }
        if (handler != null) {
            Handler h = handler;
            h.removeCallbacksAndMessages(null);
            h.post(() -> {
                if (display != null) display.release();
                if (reader != null) reader.close();
                if (projection != null) projection.stop();
                if (prefs != null) send(Board.black(prefs.outputLeds()));
                if (socket != null) socket.close();
                thread.quitSafely();
            });
        } else if (projection != null) {
            projection.stop();
        }
        if (!status.startsWith("Телевизор")) status = "Подсветка остановлена";
        super.onDestroy();
    }
}
