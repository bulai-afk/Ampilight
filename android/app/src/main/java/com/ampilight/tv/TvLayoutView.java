package com.ampilight.tv;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.view.View;

/** Схема: экран, вокруг него диоды по раскладке, метка начала ленты. */
public class TvLayoutView extends View {
    private static final int[] SIDE_COLORS = {
            Color.parseColor("#FFA040"),
            Color.parseColor("#B26BFF"),
            Color.parseColor("#3D7BFF"),
            Color.parseColor("#1DE9B6"),
    };

    private final Paint screenPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint framePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dotPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint mutedPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint warnPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint markPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint ringPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private LedLayout layout = new LedLayout(28, 17, 28, 17, LedLayout.BOTTOM_LEFT, true);
    private int loops = 1;
    private int boardLeds;
    private boolean clockwise = true;
    private int[] colors;
    private int highlight = -1;

    public TvLayoutView(Context context) {
        super(context);
        float d = getResources().getDisplayMetrics().density;
        screenPaint.setColor(Color.parseColor("#07080B"));
        framePaint.setStyle(Paint.Style.STROKE);
        framePaint.setStrokeWidth(2 * d);
        framePaint.setColor(Color.parseColor("#C8D0DC"));
        textPaint.setColor(Color.parseColor("#F1F5F9"));
        textPaint.setTextSize(18 * d);
        textPaint.setTextAlign(Paint.Align.CENTER);
        mutedPaint.setColor(Color.parseColor("#64748B"));
        mutedPaint.setTextSize(15 * d);
        mutedPaint.setTextAlign(Paint.Align.CENTER);
        warnPaint.setColor(Color.parseColor("#FFB74D"));
        warnPaint.setTextSize(15 * d);
        warnPaint.setTextAlign(Paint.Align.CENTER);
        markPaint.setColor(Color.WHITE);
        markPaint.setStrokeWidth(2 * d);
        markPaint.setStyle(Paint.Style.STROKE);
        markPaint.setTextSize(14 * d);
        ringPaint.setColor(Color.parseColor("#3A4252"));
    }

    public void setLayout(LedLayout layout, int loops, int boardLeds, boolean clockwise) {
        this.layout = layout;
        this.loops = Math.max(1, loops);
        this.boardLeds = boardLeds;
        this.clockwise = clockwise;
        invalidate();
    }

    /** Цвет каждой позиции раскладки (null — показать цвета сторон по умолчанию). */
    public void setColors(int[] colors, int highlight) {
        this.colors = colors;
        this.highlight = highlight;
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        float d = getResources().getDisplayMetrics().density;
        float rowGap = 7 * d;
        float margin = 18 * d + rowGap * (loops - 1);
        float availW = getWidth() - 2 * margin;
        float availH = getHeight() - 2 * margin;
        if (availW <= 0 || availH <= 0) return;
        float w = availW;
        float h = w * 9f / 16f;
        if (h > availH) {
            h = availH;
            w = h * 16f / 9f;
        }
        float left = (getWidth() - w) / 2f;
        float top = (getHeight() - h) / 2f;
        RectF screen = new RectF(left, top, left + w, top + h);
        canvas.drawRoundRect(screen, 8 * d, 8 * d, screenPaint);
        canvas.drawRoundRect(screen, 8 * d, 8 * d, framePaint);

        int total = layout.perimeter();
        float[] firstXY = null;
        float[] secondXY = null;
        for (int loop = loops - 1; loop >= 0; loop--) {
            float out = 10 * d + loop * rowGap;
            for (int p = 0; p < total; p++) {
                int side = layout.side[p];
                int count = Math.max(1, layout.count(side));
                float t = (layout.segment[p] + 0.5f) / count;
                float x;
                float y;
                float span;
                switch (side) {
                    case LedLayout.SIDE_TOP:
                        x = screen.left + t * w;
                        y = screen.top - out;
                        span = w / count;
                        break;
                    case LedLayout.SIDE_BOTTOM:
                        x = screen.left + t * w;
                        y = screen.bottom + out;
                        span = w / count;
                        break;
                    case LedLayout.SIDE_RIGHT:
                        x = screen.right + out;
                        y = screen.top + t * h;
                        span = h / count;
                        break;
                    default:
                        x = screen.left - out;
                        y = screen.top + t * h;
                        span = h / count;
                }
                float radius = Math.max(1.5f * d, Math.min(4.5f * d, span * 0.32f));
                int color = colors != null && p < colors.length ? (0xFF000000 | colors[p]) : SIDE_COLORS[side];
                glowPaint.setColor(color);
                glowPaint.setAlpha(70);
                canvas.drawCircle(x, y, radius * 2.1f, glowPaint);
                // Тёмный диод всё равно виден контуром, чтобы раскладка не пропадала на чёрной картинке.
                canvas.drawCircle(x, y, radius + d, ringPaint);
                dotPaint.setColor(color);
                canvas.drawCircle(x, y, radius, dotPaint);
                if (p == highlight && loop == 0) {
                    canvas.drawCircle(x, y, radius * 2.6f, markPaint);
                }
                if (loop == 0 && p == 0) firstXY = new float[] {x, y};
                if (loop == 0 && p == Math.min(2, total - 1)) secondXY = new float[] {x, y};
            }
        }

        if (firstXY != null) drawStart(canvas, screen, firstXY, secondXY, d);

        int perLoop = total;
        int planned = perLoop * loops;
        String sum = layout.top + " + " + layout.right + " + " + layout.bottom + " + " + layout.left
                + " = " + perLoop + (loops > 1 ? " × " + loops + " = " + planned : "") + " диодов";
        float maxText = w - 24 * d;
        drawFitted(canvas, sum, screen.centerX(), screen.centerY() - 4 * d, textPaint, 18 * d, maxText);
        if (boardLeds > 0 && boardLeds != planned) {
            drawFitted(canvas, "Плата прошита на " + boardLeds + ", по раскладке " + planned,
                    screen.centerX(), screen.centerY() + 22 * d, warnPaint, 15 * d, maxText);
        } else if (boardLeds > 0) {
            drawFitted(canvas, "Совпадает с платой", screen.centerX(), screen.centerY() + 22 * d,
                    mutedPaint, 15 * d, maxText);
        }
    }

    private static void drawFitted(Canvas canvas, String text, float x, float y, Paint paint, float size, float maxWidth) {
        paint.setTextSize(size);
        float width = paint.measureText(text);
        if (width > maxWidth) paint.setTextSize(size * maxWidth / width);
        canvas.drawText(text, x, y, paint);
    }

    private void drawStart(Canvas canvas, RectF screen, float[] first, float[] second, float d) {
        markPaint.setStyle(Paint.Style.STROKE);
        canvas.drawCircle(first[0], first[1], 9 * d, markPaint);
        if (second != null && (second[0] != first[0] || second[1] != first[1])) {
            float dx = second[0] - first[0];
            float dy = second[1] - first[1];
            float len = (float) Math.hypot(dx, dy);
            float ux = dx / len;
            float uy = dy / len;
            float sx = first[0] + ux * 14 * d;
            float sy = first[1] + uy * 14 * d;
            float ex = sx + ux * 26 * d;
            float ey = sy + uy * 26 * d;
            canvas.drawLine(sx, sy, ex, ey, markPaint);
            Path head = new Path();
            head.moveTo(ex, ey);
            head.lineTo(ex - ux * 8 * d - uy * 5 * d, ey - uy * 8 * d + ux * 5 * d);
            head.moveTo(ex, ey);
            head.lineTo(ex - ux * 8 * d + uy * 5 * d, ey - uy * 8 * d - ux * 5 * d);
            canvas.drawPath(head, markPaint);
        }
        markPaint.setStyle(Paint.Style.FILL);
        float tx = Math.max(screen.left + 12 * d, Math.min(screen.right - 120 * d, first[0] + 14 * d));
        float ty = first[1] > screen.centerY() ? screen.bottom - 14 * d : screen.top + 26 * d;
        canvas.drawText("Начало " + (clockwise ? "↻" : "↺"), tx, ty, markPaint);
        markPaint.setStyle(Paint.Style.STROKE);
    }
}
