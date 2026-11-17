package com.xurui.duocodex;

import android.app.Activity;
import android.os.Build;
import android.view.WindowInsets;
import android.view.inputmethod.InputMethodManager;

/** Owns the lower display's input focus and Retroid's IME inset workaround. */
final class ConsoleKeyboard {
    private final Activity activity;
    private final BridgePanel panel;
    private final Runnable syncInsets = this::readInsets;
    private boolean started;
    private boolean requested;

    ConsoleKeyboard(Activity activity, BridgePanel panel) {
        this.activity = activity;
        this.panel = panel;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) activity.getWindow().setDecorFitsSystemWindows(false);
    }

    void start() {
        started = true;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) panel.post(syncInsets);
        focus();
    }

    void stop() {
        started = false;
        requested = false;
        panel.removeCallbacks(syncInsets);
    }

    void restore() {
        requested = false;
        focus();
    }

    void focus() {
        if (!started || requested || !activity.hasWindowFocus()) return;
        panel.focusComposer(view -> {
            if (!started || requested || !activity.hasWindowFocus()) return;
            requested = true;
            activity.getSystemService(InputMethodManager.class).showSoftInput(view, InputMethodManager.SHOW_IMPLICIT);
        });
    }

    private void readInsets() {
        if (!started) return;
        // On the Duo, WindowMetrics includes IME insets that the lower view can omit.
        var insets = activity.getWindowManager().getCurrentWindowMetrics().getWindowInsets();
        int bottom = insets.getInsets(WindowInsets.Type.ime() | WindowInsets.Type.navigationBars()).bottom;
        if (bottom != panel.getPaddingBottom()) panel.setPadding(0, 0, 0, bottom);
        panel.postDelayed(syncInsets, 400);
    }
}
