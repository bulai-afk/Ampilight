package com.ampilight.tv;

/**
 * Средний цвет полосы у края кадра для каждого диода раскладки.
 * Смещения пикселей считаются один раз, пока не поменялись размер кадра или раскладка.
 */
public final class EdgeSampler {
    private static final int MAX_STEPS = 6;

    private int[][] offsets = new int[0][];
    private int keyWidth = -1;
    private int keyHeight = -1;
    private int keyStride = -1;
    private int keyDepth = -1;
    private LedLayout keyLayout;

    public int[] sample(byte[] rgba, int width, int height, int rowStride, LedLayout layout, int depthPercent) {
        if (width != keyWidth || height != keyHeight || rowStride != keyStride
                || depthPercent != keyDepth || layout != keyLayout) {
            offsets = build(width, height, rowStride, layout, depthPercent);
            keyWidth = width;
            keyHeight = height;
            keyStride = rowStride;
            keyDepth = depthPercent;
            keyLayout = layout;
        }
        int[] colors = new int[offsets.length];
        for (int p = 0; p < offsets.length; p++) {
            int[] list = offsets[p];
            long r = 0;
            long g = 0;
            long b = 0;
            for (int off : list) {
                r += rgba[off] & 0xFF;
                g += rgba[off + 1] & 0xFF;
                b += rgba[off + 2] & 0xFF;
            }
            int n = Math.max(1, list.length);
            colors[p] = (int) ((r / n) << 16 | (g / n) << 8 | (b / n));
        }
        return colors;
    }

    private static int[][] build(int width, int height, int rowStride, LedLayout layout, int depthPercent) {
        int total = layout.perimeter();
        int[][] result = new int[total][];
        float depth = Math.max(0.02f, Math.min(0.5f, depthPercent / 100f));
        int bandX = Math.max(1, Math.round(width * depth));
        int bandY = Math.max(1, Math.round(height * depth));
        for (int p = 0; p < total; p++) {
            int side = layout.side[p];
            int count = Math.max(1, layout.count(side));
            int seg = layout.segment[p];
            int x0;
            int x1;
            int y0;
            int y1;
            if (side == LedLayout.SIDE_TOP || side == LedLayout.SIDE_BOTTOM) {
                x0 = seg * width / count;
                x1 = Math.max(x0 + 1, (seg + 1) * width / count);
                y0 = side == LedLayout.SIDE_TOP ? 0 : height - bandY;
                y1 = y0 + bandY;
            } else {
                y0 = seg * height / count;
                y1 = Math.max(y0 + 1, (seg + 1) * height / count);
                x0 = side == LedLayout.SIDE_LEFT ? 0 : width - bandX;
                x1 = x0 + bandX;
            }
            result[p] = region(x0, x1, y0, y1, width, height, rowStride);
        }
        return result;
    }

    private static int[] region(int x0, int x1, int y0, int y1, int width, int height, int rowStride) {
        int stepsX = Math.min(MAX_STEPS, x1 - x0);
        int stepsY = Math.min(MAX_STEPS, y1 - y0);
        int[] list = new int[stepsX * stepsY];
        int n = 0;
        for (int iy = 0; iy < stepsY; iy++) {
            int y = Math.min(height - 1, y0 + (int) ((iy + 0.5f) * (y1 - y0) / stepsY));
            for (int ix = 0; ix < stepsX; ix++) {
                int x = Math.min(width - 1, x0 + (int) ((ix + 0.5f) * (x1 - x0) / stepsX));
                list[n++] = y * rowStride + x * 4;
            }
        }
        return list;
    }
}
