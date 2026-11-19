package com.xurui.duocodex;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;

abstract class PanelActivity extends Activity {
    private static final PanelExit EXIT = new PanelExit();
    private static final ControllerScroll CONTROLLER = new ControllerScroll();
    private static final ConsoleTextInput TEXT_INPUT = new ConsoleTextInput();
    private BridgePanel content;
    private ConsoleKeyboard keyboard;
    private OnBackInvokedCallback backCallback;
    private Panel panel;
    private boolean started;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        EXIT.register(this);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            backCallback = this::onBackPressed;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_OVERLAY, backCallback);
        }
        getWindow().setStatusBarColor(0xFF211B14);
        getWindow().setNavigationBarColor(0xFF17130E);
        content = new BridgePanel(this, this::restoreKeyboard, CONTROLLER::key, TEXT_INPUT);
        setContentView(content);
    }

    final void showPanel(Panel role) {
        panel = role;
        updateSystemBars();
        if (role == Panel.BOTTOM && keyboard == null) keyboard = new ConsoleKeyboard(this, content);
        if (role == Panel.BOTTOM) TEXT_INPUT.bind(this, this::restoreKeyboard);
        content.show(role);
        if (started && role != Panel.BOTTOM) CONTROLLER.bind(content);
    }

    private void updateSystemBars() {
        // Only the reading display is immersive; the console keeps its IME inset handling.
        if (panel == Panel.BOTTOM || panel == null) return;
        boolean immersive = panel == Panel.TOP;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            getWindow().setDecorFitsSystemWindows(!immersive);
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller == null) return;
            controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            if (immersive) controller.hide(WindowInsets.Type.systemBars());
            else controller.show(WindowInsets.Type.systemBars());
        } else {
            getWindow().getDecorView().setSystemUiVisibility(immersive
                ? View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                    | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                : View.SYSTEM_UI_FLAG_VISIBLE);
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        updateSystemBars();
        started = true;
        content.start();
        if (panel != null && panel != Panel.BOTTOM) CONTROLLER.bind(content);
        if (keyboard != null) {
            TEXT_INPUT.bind(this, this::restoreKeyboard);
            keyboard.start();
        }
    }

    @Override
    protected void onStop() {
        started = false;
        TEXT_INPUT.unbind(this);
        if (panel == Panel.BOTTOM) CONTROLLER.reset();
        CONTROLLER.unbind(content);
        EXIT.cancel(this);
        if (keyboard != null) keyboard.stop();
        content.stop();
        super.onStop();
    }

    @Override
    public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (focused) updateSystemBars();
        if (!focused && panel != Panel.TOP) CONTROLLER.reset();
        if (focused && keyboard != null) keyboard.focus();
    }

    @Override
    public boolean dispatchKeyEvent(KeyEvent event) {
        return CONTROLLER.key(event) || super.dispatchKeyEvent(event);
    }

    @Override
    public boolean dispatchGenericMotionEvent(MotionEvent event) {
        return CONTROLLER.motion(event) || super.dispatchGenericMotionEvent(event);
    }

    @Override
    public void onBackPressed() {
        EXIT.backPressed(this, this::restoreKeyboard);
    }

    private void restoreKeyboard() {
        if (keyboard != null) keyboard.restore();
    }

    @Override
    protected void onDestroy() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && backCallback != null) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);
        }
        EXIT.unregister(this);
        content.destroy();
        super.onDestroy();
    }
}
