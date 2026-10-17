package com.ampilight.tv;

/**
 * Порядок диодов вдоль ленты по периметру экрана (если смотреть на экран спереди).
 *
 * Позиция p (0..perimeter-1) — p-й диод от начала ленты в одном витке.
 * Для каждой позиции известны сторона и номер участка на этой стороне,
 * считая слева направо для верха и низа и сверху вниз для боков.
 * Следующие витки повторяют первый: диод i берёт позицию i % perimeter.
 */
public final class LedLayout {
    public static final int BOTTOM_LEFT = 0;
    public static final int TOP_LEFT = 1;
    public static final int TOP_RIGHT = 2;
    public static final int BOTTOM_RIGHT = 3;

    public static final int SIDE_TOP = 0;
    public static final int SIDE_RIGHT = 1;
    public static final int SIDE_BOTTOM = 2;
    public static final int SIDE_LEFT = 3;

    public final int top;
    public final int right;
    public final int bottom;
    public final int left;
    public final int[] side;
    public final int[] segment;

    public LedLayout(int top, int right, int bottom, int left, int corner, boolean clockwise) {
        this.top = Math.max(0, top);
        this.right = Math.max(0, right);
        this.bottom = Math.max(0, bottom);
        this.left = Math.max(0, left);
        int total = this.top + this.right + this.bottom + this.left;
        int[] cwSide = new int[total];
        int[] cwSeg = new int[total];
        int n = 0;
        // По часовой стрелке от нижнего левого угла: вверх по левой, по верху вправо,
        // вниз по правой, по низу влево.
        for (int k = 0; k < this.left; k++, n++) {
            cwSide[n] = SIDE_LEFT;
            cwSeg[n] = this.left - 1 - k;
        }
        for (int k = 0; k < this.top; k++, n++) {
            cwSide[n] = SIDE_TOP;
            cwSeg[n] = k;
        }
        for (int k = 0; k < this.right; k++, n++) {
            cwSide[n] = SIDE_RIGHT;
            cwSeg[n] = k;
        }
        for (int k = 0; k < this.bottom; k++, n++) {
            cwSide[n] = SIDE_BOTTOM;
            cwSeg[n] = this.bottom - 1 - k;
        }
        int offset;
        switch (corner) {
            case TOP_LEFT:
                offset = this.left;
                break;
            case TOP_RIGHT:
                offset = this.left + this.top;
                break;
            case BOTTOM_RIGHT:
                offset = this.left + this.top + this.right;
                break;
            default:
                offset = 0;
        }
        side = new int[total];
        segment = new int[total];
        for (int j = 0; j < total; j++) {
            // Против часовой — тот же круг от того же угла, пройденный в обратную сторону.
            int src = clockwise ? (j + offset) % total : (offset - 1 - j + 2 * total) % total;
            side[j] = cwSide[src];
            segment[j] = cwSeg[src];
        }
    }

    public int perimeter() {
        return side.length;
    }

    public int count(int whichSide) {
        switch (whichSide) {
            case SIDE_TOP:
                return top;
            case SIDE_RIGHT:
                return right;
            case SIDE_BOTTOM:
                return bottom;
            default:
                return left;
        }
    }
}
