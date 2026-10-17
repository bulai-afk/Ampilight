package com.ampilight.tv;

import android.app.Activity;
import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;

/**
 * Красный квадрат бежит по краю экрана по часовой стрелке от нижнего левого угла.
 * Подсветка захватывает экран, поэтому лента должна повторять квадрат.
 * OK — пауза, влево/вправо — медленнее/быстрее, Назад — выход.
 */
public class ScreenTestActivity extends Activity {
    private static final float[] SPEEDS = {16f, 10f, 6f, 3.5f};

    private SquareView view;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        view = new SquareView(this);
        setContentView(view);
        view.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
                | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
                view.togglePause();
                return true;
            case KeyEvent.KEYCODE_DPAD_LEFT:
                view.changeSpeed(-1);
                return true;
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                view.changeSpeed(1);
                return true;
            default:
                return super.onKeyDown(keyCode, event);
        }
    }

    private static final class SquareView extends View {
        private final Paint square = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint hint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint muted = new Paint(Paint.ANTI_ALIAS_FLAG);
        private float progress;
        private long lastAt;
        private boolean paused;
        private int speed = 1;

        SquareView(Context context) {
            super(context);
            float d = getResources().getDisplayMetrics().density;
            setBackgroundColor(Color.BLACK);
            square.setColor(Color.RED);
            hint.setColor(Color.parseColor("#F1F5F9"));
            hint.setTextAlign(Paint.Align.CENTER);
            hint.setTextSize(22 * d);
            muted.setColor(Color.parseColor("#64748B"));
            muted.setTextAlign(Paint.Align.CENTER);
            muted.setTextSize(16 * d);
        }

        void togglePause() {
            paused = !paused;
            lastAt = 0;
            invalidate();
        }

        void changeSpeed(int delta) {
            speed = Math.max(0, Math.min(SPEEDS.length - 1, speed + delta));
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            long now = SystemClock.uptimeMillis();
            if (lastAt != 0 && !paused) {
                progress = (progress + (now - lastAt) / 1000f / SPEEDS[speed]) % 1f;
            }
            lastAt = now;

            float w = getWidth();
            float h = getHeight();
            float size = Math.min(w, h) * 0.12f;
            float spanX = w - size;
            float spanY = h - size;
            float perimeter = 2 * (spanX + spanY);
            float s = progress * perimeter;
            float x;
            float y;
            // По часовой от нижнего левого угла, как идёт лента.
            if (s < spanY) {
                x = 0;
                y = spanY - s;
            } else if (s < spanY + spanX) {
                x = s - spanY;
                y = 0;
            } else if (s < 2 * spanY + spanX) {
                x = spanX;
                y = s - spanY - spanX;
            } else {
                x = spanX - (s - 2 * spanY - spanX);
                y = spanY;
            }
            canvas.drawRect(x, y, x + size, y + size, square);

            float cy = h / 2f;
            canvas.drawText("Лента за телевизором должна бежать вместе с квадратом", w / 2f, cy - 10 * density(), hint);
            String state = paused ? "Пауза" : "Круг за " + (int) SPEEDS[speed] + " с";
            canvas.drawText(state + " · OK — пауза · ‹ › — скорость · Назад — выход",
                    w / 2f, cy + 24 * density(), muted);
            if (!paused) postInvalidateOnAnimation();
        }

        private float density() {
            return getResources().getDisplayMetrics().density;
        }
    }
}
