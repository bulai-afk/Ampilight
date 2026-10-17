package com.ampilight.tv;

import android.app.Activity;
import android.app.Dialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.media.projection.MediaProjectionManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Spannable;
import android.text.SpannableString;
import android.text.style.ForegroundColorSpan;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final int REQUEST_CAPTURE = 7;
    private static final long TICK_MS = 100;
    private static final int[] TEST_COLORS = {0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF};
    private static final String[] CORNERS = {"Нижний левый", "Верхний левый", "Верхний правый", "Нижний правый"};
    private static final String[] DIRECTIONS = {"По часовой", "Против часовой"};

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService net = Executors.newSingleThreadExecutor();
    private Prefs prefs;

    private TextView statusView;
    private TvLayoutView tvView;
    private Stepper topStepper;
    private Stepper rightStepper;
    private Stepper bottomStepper;
    private Stepper leftStepper;
    private Stepper loopsStepper;
    private Stepper brightnessStepper;
    private TextView startButton;
    private TextView testButton;
    private TextView squareButton;
    private boolean squareAfterStart;

    private boolean searching;
    private String searchNote = "";
    private boolean boardOnline = true;
    private boolean checking;
    private long checkedAt;
    private boolean testing;
    private int testTick;
    private DatagramSocket testSocket;

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            onTick();
            ui.postDelayed(this, TICK_MS);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = Prefs.load(this);
        setContentView(buildScreen());
        refreshLayout();
        onTick();
        startButton.setFocusedByDefault(true);
        startButton.post(startButton::requestFocus);
        discover();
    }

    @Override
    protected void onResume() {
        super.onResume();
        ui.post(tick);
    }

    @Override
    protected void onPause() {
        super.onPause();
        ui.removeCallbacks(tick);
        stopTest();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        net.shutdown();
    }

    private View buildScreen() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0C0E12"));
        root.setPadding(dp(44), dp(26), dp(44), dp(26));

        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        root.addView(column, new FrameLayout.LayoutParams(-1, -1));
        // Элемент в фокусе увеличивается — не обрезать его краями контейнеров.
        root.setClipChildren(false);
        root.setClipToPadding(false);
        column.setClipChildren(false);

        LinearLayout topBar = new LinearLayout(this);
        topBar.setClipChildren(false);
        topBar.setOrientation(LinearLayout.HORIZONTAL);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        statusView = flatButton("");
        statusView.setOnClickListener(v -> discover());
        topBar.addView(statusView, new LinearLayout.LayoutParams(-2, -2));
        topBar.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1f));
        TextView settingsButton = flatButton("⚙  Настройки");
        settingsButton.setOnClickListener(v -> openSettings());
        topBar.addView(settingsButton, new LinearLayout.LayoutParams(-2, -2));
        column.addView(topBar, new LinearLayout.LayoutParams(-1, -2));

        topStepper = sideStepper("Сверху");
        rightStepper = sideStepper("Справа");
        bottomStepper = sideStepper("Снизу");
        leftStepper = sideStepper("Слева");
        topStepper.setValue(prefs.top);
        rightStepper.setValue(prefs.right);
        bottomStepper.setValue(prefs.bottom);
        leftStepper.setValue(prefs.left);

        LinearLayout center = new LinearLayout(this);
        center.setOrientation(LinearLayout.VERTICAL);
        center.setGravity(Gravity.CENTER_HORIZONTAL);
        center.addView(topStepper, wrap(0, dp(6), 0, 0));
        LinearLayout middle = new LinearLayout(this);
        middle.setOrientation(LinearLayout.HORIZONTAL);
        middle.setGravity(Gravity.CENTER_VERTICAL);
        middle.addView(leftStepper, wrap(0, 0, 0, 0));
        tvView = new TvLayoutView(this);
        middle.addView(tvView, new LinearLayout.LayoutParams(0, -1, 1f));
        middle.addView(rightStepper, wrap(0, 0, 0, 0));
        center.addView(middle, new LinearLayout.LayoutParams(-1, 0, 1f));
        center.addView(bottomStepper, wrap(0, 0, 0, 0));
        column.addView(center, new LinearLayout.LayoutParams(-1, 0, 1f));

        loopsStepper = new Stepper(this, "Витки", 1, 6, 1, "");
        loopsStepper.setValue(prefs.loops);
        loopsStepper.setListener((s, value) -> {
            prefs.loops = value;
            saveAndRefresh();
        });
        brightnessStepper = new Stepper(this, "Яркость", 5, 100, 5, "%");
        brightnessStepper.setValue(prefs.brightness);
        brightnessStepper.setListener((s, value) -> {
            prefs.brightness = value;
            prefs.save(this);
        });
        LinearLayout options = new LinearLayout(this);
        options.setOrientation(LinearLayout.HORIZONTAL);
        options.setGravity(Gravity.CENTER);
        options.addView(loopsStepper, wrap(0, 0, dp(16), 0));
        options.addView(brightnessStepper, wrap(0, 0, 0, 0));
        column.addView(options, wrap(0, dp(14), 0, 0));

        startButton = new TextView(this);
        startButton.setFocusable(true);
        startButton.setClickable(true);
        startButton.setGravity(Gravity.CENTER);
        startButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        startButton.setTypeface(Typeface.DEFAULT_BOLD);
        startButton.setTextColor(Color.parseColor("#F1F5F9"));
        startButton.setBackgroundResource(R.drawable.bg_primary);
        startButton.setPadding(dp(48), dp(14), dp(48), dp(14));
        startButton.setOnClickListener(v -> toggleCapture());
        Ui.focusScale(startButton);
        testButton = flatButton("Тест сторон");
        testButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 19);
        testButton.setPadding(dp(26), dp(14), dp(26), dp(14));
        testButton.setOnClickListener(v -> toggleTest());
        squareButton = flatButton("Тест квадратом");
        squareButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 19);
        squareButton.setPadding(dp(26), dp(14), dp(26), dp(14));
        squareButton.setOnClickListener(v -> openSquareTest());
        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.CENTER);
        actions.addView(startButton, new LinearLayout.LayoutParams(dp(340), -2));
        actions.addView(testButton, wrap(dp(18), 0, 0, 0));
        actions.addView(squareButton, wrap(dp(14), 0, 0, 0));
        column.addView(actions, wrap(0, dp(14), 0, dp(4)));

        // Пульт: вверх/вниз идут по цепочке, влево/вправо меняют числа.
        View[] chain = {statusView, topStepper, leftStepper, rightStepper, bottomStepper,
                loopsStepper, brightnessStepper, startButton};
        for (View v : chain) v.setId(View.generateViewId());
        settingsButton.setId(View.generateViewId());
        testButton.setId(View.generateViewId());
        squareButton.setId(View.generateViewId());
        for (int i = 0; i < chain.length; i++) {
            if (i > 0) chain[i].setNextFocusUpId(chain[i - 1].getId());
            if (i < chain.length - 1) chain[i].setNextFocusDownId(chain[i + 1].getId());
        }
        statusView.setNextFocusRightId(settingsButton.getId());
        settingsButton.setNextFocusLeftId(statusView.getId());
        settingsButton.setNextFocusDownId(topStepper.getId());
        startButton.setNextFocusRightId(testButton.getId());
        testButton.setNextFocusLeftId(startButton.getId());
        testButton.setNextFocusUpId(brightnessStepper.getId());
        testButton.setNextFocusRightId(squareButton.getId());
        squareButton.setNextFocusLeftId(testButton.getId());
        squareButton.setNextFocusUpId(brightnessStepper.getId());
        return root;
    }

    private Stepper sideStepper(String label) {
        Stepper stepper = new Stepper(this, label, 0, 300, 1, "");
        stepper.setListener((s, value) -> {
            if (s == topStepper) prefs.top = value;
            if (s == rightStepper) prefs.right = value;
            if (s == bottomStepper) prefs.bottom = value;
            if (s == leftStepper) prefs.left = value;
            saveAndRefresh();
        });
        return stepper;
    }

    private TextView flatButton(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setFocusable(true);
        view.setClickable(true);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
        view.setTextColor(Color.parseColor("#F1F5F9"));
        view.setBackgroundResource(R.drawable.bg_secondary);
        view.setPadding(dp(16), dp(8), dp(16), dp(8));
        Ui.focusScale(view);
        return view;
    }

    private void saveAndRefresh() {
        prefs.save(this);
        refreshLayout();
    }

    private void refreshLayout() {
        tvView.setLayout(prefs.layout(), prefs.loops, prefs.boardLeds, prefs.clockwise);
    }

    private void onTick() {
        boolean running = CaptureService.running;
        startButton.setText(running ? "СТОП ПОДСВЕТКИ" : "СТАРТ ПОДСВЕТКИ");
        startButton.setTextColor(Color.parseColor(running ? "#00E676" : "#F1F5F9"));
        testButton.setText(testing ? "Стоп теста" : "Тест сторон");
        if (testing) {
            runTestFrame();
        } else if (running) {
            tvView.setColors(CaptureService.liveColors, -1);
        } else {
            tvView.setColors(null, -1);
        }
        if (!running && !testing) checkBoard();
        renderStatus(running);
    }

    /** Пока подсветка выключена, раз в 5 секунд проверяем, отвечает ли плата. */
    private void checkBoard() {
        String target = prefs.target();
        long now = System.currentTimeMillis();
        if (checking || searching || target == null || target.isEmpty() || now - checkedAt < 5000) return;
        checking = true;
        checkedAt = now;
        net.execute(() -> {
            boolean ok = Board.alive(target, 900);
            ui.post(() -> {
                checking = false;
                boardOnline = ok;
            });
        });
    }

    private void renderStatus(boolean running) {
        String target = prefs.target();
        String line;
        int dotColor;
        if (searching) {
            line = "●  Ищу плату в сети…";
            dotColor = Color.parseColor("#64748B");
        } else if (target == null || target.isEmpty()) {
            line = "●  Плата не найдена — нажми OK, чтобы искать" + searchNote;
            dotColor = Color.parseColor("#FF5252");
        } else if (!(running ? CaptureService.boardOnline : boardOnline)) {
            line = "●  ESP32 · " + target + " не отвечает — проверь питание платы";
            dotColor = Color.parseColor("#FF5252");
        } else {
            line = "●  ESP32 · " + target + (prefs.boardLeds > 0 ? " · " + prefs.boardLeds + " диодов" : "");
            if (running) line += " · " + CaptureService.fps + " кадр/с";
            line += searchNote;
            dotColor = Color.parseColor("#00E676");
        }
        if (running && CaptureService.status.startsWith("Ошибка")) line += " · " + CaptureService.status;
        SpannableString text = new SpannableString(line);
        text.setSpan(new ForegroundColorSpan(dotColor), 0, 1, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
        statusView.setText(text);
    }

    private void discover() {
        if (searching) return;
        searching = true;
        searchNote = "";
        net.execute(() -> {
            List<Board.Found> found = Board.discover(2500);
            ui.post(() -> {
                searching = false;
                if (found.isEmpty()) {
                    boardOnline = false;
                    return;
                }
                boardOnline = true;
                Board.Found pick = found.get(0);
                for (Board.Found f : found) {
                    if (f.ip.equals(prefs.host)) pick = f;
                }
                prefs.host = pick.ip;
                prefs.boardLeds = pick.leds;
                if (found.size() > 1) searchNote = " (плат в сети: " + found.size() + ")";
                saveAndRefresh();
            });
        });
    }

    private void toggleCapture() {
        if (CaptureService.running) {
            startService(new Intent(this, CaptureService.class).setAction(CaptureService.ACTION_STOP));
            return;
        }
        String target = prefs.target();
        if (target == null || target.isEmpty()) {
            squareAfterStart = false;
            toast("Сначала найди плату: строка вверху слева");
            discover();
            return;
        }
        stopTest();
        MediaProjectionManager manager = (MediaProjectionManager) getSystemService(MEDIA_PROJECTION_SERVICE);
        Intent consent = android.os.Build.VERSION.SDK_INT >= 34
                ? manager.createScreenCaptureIntent(android.media.projection.MediaProjectionConfig.createConfigForDefaultDisplay())
                : manager.createScreenCaptureIntent();
        try {
            startActivityForResult(consent, REQUEST_CAPTURE);
        } catch (ActivityNotFoundException e) {
            squareAfterStart = false;
            toast("На этом телевизоре нет системного захвата экрана");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_CAPTURE) return;
        boolean square = squareAfterStart;
        squareAfterStart = false;
        if (resultCode != RESULT_OK || data == null) {
            toast("Без разрешения на захват экрана подсветка не работает");
            return;
        }
        Intent service = new Intent(this, CaptureService.class)
                .setAction(CaptureService.ACTION_START)
                .putExtra(CaptureService.EXTRA_CODE, resultCode)
                .putExtra(CaptureService.EXTRA_DATA, data);
        startForegroundService(service);
        if (square) {
            ui.postDelayed(() -> startActivity(new Intent(this, ScreenTestActivity.class)), 700);
        } else {
            toast("Подсветка запущена. Можно выходить из приложения — она продолжит работать.");
        }
    }

    /** Квадрат на экране проверяет всю цепочку: захват → раскладка → плата. */
    private void openSquareTest() {
        stopTest();
        if (CaptureService.running) {
            startActivity(new Intent(this, ScreenTestActivity.class));
            return;
        }
        squareAfterStart = true;
        toggleCapture();
    }

    private void toggleTest() {
        if (testing) {
            stopTest();
            return;
        }
        if (CaptureService.running) {
            toast("Сначала останови подсветку");
            return;
        }
        String target = prefs.target();
        if (target == null || target.isEmpty()) {
            toast("Сначала найди плату");
            discover();
            return;
        }
        testing = true;
        testTick = 0;
    }

    private void stopTest() {
        if (!testing) return;
        testing = false;
        send(Board.black(prefs.outputLeds()));
    }

    /** Верх красный, право зелёное, низ синий, лево белое; первый диод мигает жёлтым. */
    private void runTestFrame() {
        LedLayout layout = prefs.layout();
        int total = layout.perimeter();
        if (total == 0) return;
        int[] colors = new int[total];
        for (int p = 0; p < total; p++) colors[p] = TEST_COLORS[layout.side[p]];
        boolean blinkOn = (testTick++ / 4) % 2 == 0;
        colors[0] = blinkOn ? 0xFFD000 : 0x000000;
        tvView.setColors(colors, 0);
        send(Board.packet(colors, prefs.outputLeds(), prefs.brightness / 100f, prefs.maxMilliamps()));
    }

    private void send(byte[] packet) {
        String target = prefs.target();
        if (target == null || target.isEmpty()) return;
        net.execute(() -> {
            try {
                if (testSocket == null) testSocket = new DatagramSocket();
                InetAddress address = InetAddress.getByName(target);
                testSocket.send(new DatagramPacket(packet, packet.length, address, Board.PORT));
            } catch (Exception ignored) {
            }
        });
    }

    private void openSettings() {
        Dialog dialog = new Dialog(this, R.style.SettingsDialog);
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(32), dp(26), dp(32), dp(26));

        TextView title = new TextView(this);
        title.setText("Настройки");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 24);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setTextColor(Color.parseColor("#F1F5F9"));
        panel.addView(title, wrap(0, 0, 0, dp(16)));

        Stepper corner = new Stepper(this, "Начало ленты", CORNERS);
        corner.setValue(prefs.corner);
        corner.setListener((s, v) -> {
            prefs.corner = v;
            saveAndRefresh();
        });
        Stepper direction = new Stepper(this, "Направление", DIRECTIONS);
        direction.setValue(prefs.clockwise ? 0 : 1);
        direction.setListener((s, v) -> {
            prefs.clockwise = v == 0;
            saveAndRefresh();
        });
        Stepper depth = new Stepper(this, "Глубина захвата", 5, 40, 5, "%");
        depth.setValue(prefs.depth);
        depth.setListener((s, v) -> {
            prefs.depth = v;
            prefs.save(this);
        });
        Stepper smooth = new Stepper(this, "Плавность", 0, 90, 10, "%");
        smooth.setValue(prefs.smooth);
        smooth.setListener((s, v) -> {
            prefs.smooth = v;
            prefs.save(this);
        });
        String[] supplies = new String[11];
        supplies[0] = "без ограничения";
        for (int a = 1; a < supplies.length; a++) supplies[a] = a + " А";
        Stepper supply = new Stepper(this, "Блок питания 5 В", supplies);
        supply.setValue(prefs.supplyAmps);
        supply.setListener((s, v) -> {
            prefs.supplyAmps = v;
            prefs.save(this);
        });
        Stepper capture = new Stepper(this, "Захват экрана", Prefs.CAPTURE_NAMES);
        capture.setValue(prefs.captureMode);
        capture.setListener((s, v) -> {
            prefs.captureMode = v;
            prefs.save(this);
        });
        for (View v : new View[] {corner, direction, depth, smooth, supply, capture}) {
            panel.addView(v, fill(0, 0, 0, dp(10)));
        }

        TextView hint = new TextView(this);
        hint.setText("Углы — как смотришь на экран спереди. IP пустой — плата ищется сама.");
        hint.setTextColor(Color.parseColor("#64748B"));
        hint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        panel.addView(hint, fill(0, dp(4), 0, dp(10)));

        EditText ip = new EditText(this);
        ip.setSingleLine(true);
        ip.setHint("IP платы вручную");
        ip.setText(prefs.manualIp);
        ip.setTextColor(Color.parseColor("#F1F5F9"));
        ip.setHintTextColor(Color.parseColor("#64748B"));
        ip.setBackgroundResource(R.drawable.bg_secondary);
        ip.setPadding(dp(18), dp(10), dp(18), dp(10));
        ip.setImeOptions(EditorInfo.IME_ACTION_DONE);
        ip.setInputType(android.text.InputType.TYPE_CLASS_TEXT);
        panel.addView(ip, fill(0, 0, 0, dp(14)));

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        TextView search = flatButton("Найти плату заново");
        search.setOnClickListener(v -> {
            prefs.manualIp = ip.getText().toString().trim();
            prefs.save(this);
            discover();
            dialog.dismiss();
        });
        TextView done = flatButton("Готово");
        done.setOnClickListener(v -> dialog.dismiss());
        buttons.addView(search, wrap(0, 0, dp(14), 0));
        buttons.addView(done, wrap(0, 0, 0, 0));
        panel.addView(buttons, wrap(0, 0, 0, 0));

        dialog.setOnDismissListener(d -> {
            prefs.manualIp = ip.getText().toString().trim();
            saveAndRefresh();
        });
        dialog.setContentView(panel, new android.view.ViewGroup.LayoutParams(dp(560), -2));
        dialog.show();
        corner.requestFocus();
    }

    private LinearLayout.LayoutParams wrap(int l, int t, int r, int b) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.setMargins(l, t, r, b);
        lp.gravity = Gravity.CENTER;
        return lp;
    }

    private LinearLayout.LayoutParams fill(int l, int t, int r, int b) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(l, t, r, b);
        return lp;
    }

    private void toast(String text) {
        Toast.makeText(this, text, Toast.LENGTH_LONG).show();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
