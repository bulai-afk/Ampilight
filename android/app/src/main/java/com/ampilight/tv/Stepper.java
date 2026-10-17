package com.ampilight.tv;

import android.content.Context;
import android.graphics.Color;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.widget.TextView;

/** «‹ Подпись значение ›»: значение меняется кнопками пульта влево/вправо. */
public class Stepper extends TextView {
    public interface Listener {
        void onChanged(Stepper stepper, int value);
    }

    private final String label;
    private final int min;
    private final int max;
    private final int step;
    private final String[] names;
    private final String suffix;
    private int value;
    private Listener listener;

    public Stepper(Context context, String label, int min, int max, int step, String suffix) {
        this(context, label, min, max, step, suffix, null);
    }

    public Stepper(Context context, String label, String[] names) {
        this(context, label, 0, names.length - 1, 1, "", names);
    }

    private Stepper(Context context, String label, int min, int max, int step, String suffix, String[] names) {
        super(context);
        this.label = label;
        this.min = min;
        this.max = max;
        this.step = step;
        this.suffix = suffix;
        this.names = names;
        setFocusable(true);
        setFocusableInTouchMode(true);
        setClickable(true);
        setGravity(Gravity.CENTER);
        setSingleLine(true);
        setTextColor(Color.parseColor("#F1F5F9"));
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 19);
        setBackgroundResource(R.drawable.bg_pill);
        int padH = dp(22);
        int padV = dp(9);
        setPadding(padH, padV, padH, padV);
        Ui.focusScale(this);
        render();
    }

    public void setListener(Listener listener) {
        this.listener = listener;
    }

    public int value() {
        return value;
    }

    public void setValue(int newValue) {
        value = Math.max(min, Math.min(max, newValue));
        render();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_DPAD_LEFT || keyCode == KeyEvent.KEYCODE_DPAD_RIGHT) {
            int direction = keyCode == KeyEvent.KEYCODE_DPAD_RIGHT ? 1 : -1;
            int amount = event.getRepeatCount() > 6 && names == null ? step * 5 : step;
            int next = value + direction * amount;
            if (names != null) {
                next = (next - min + (max - min + 1)) % (max - min + 1) + min;
            }
            next = Math.max(min, Math.min(max, next));
            if (next != value) {
                value = next;
                render();
                if (listener != null) listener.onChanged(this, value);
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    private void render() {
        String shown = names != null ? names[value] : value + suffix;
        setText("‹   " + label + "  " + shown + "   ›");
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
