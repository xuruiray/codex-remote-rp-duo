package com.xurui.duocodex;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;

abstract class PanelActivity extends Activity {
    private static final PanelExit EXIT = new PanelExit();
    private static final ControllerScroll CONTROLLER = new ControllerScroll();
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
        content = new BridgePanel(this, this::restoreKeyboard, CONTROLLER::key);
        setContentView(content);
    }

    final void showPanel(Panel role) {
        panel = role;
        if (role == Panel.BOTTOM && keyboard == null) keyboard = new ConsoleKeyboard(this, content);
        content.show(role);
        if (started && role != Panel.BOTTOM) CONTROLLER.bind(content);
    }

    @Override
    protected void onStart() {
        super.onStart();
        started = true;
        content.start();
        if (panel != null && panel != Panel.BOTTOM) CONTROLLER.bind(content);
        if (keyboard != null) keyboard.start();
    }

    @Override
    protected void onStop() {
        started = false;
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
