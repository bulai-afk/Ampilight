package com.ampilight.tv;

import android.view.View;

final class Ui {
    private Ui() {}

    /** Элемент в фокусе чуть увеличивается — с дивана так видно, где ты. */
    static void focusScale(View view) {
        view.setOnFocusChangeListener((v, hasFocus) -> {
            float scale = hasFocus ? 1.06f : 1f;
            v.animate().scaleX(scale).scaleY(scale).setDuration(120).start();
        });
    }
}
