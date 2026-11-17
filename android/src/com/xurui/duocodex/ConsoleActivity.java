package com.xurui.duocodex;

import android.content.Intent;
import android.hardware.display.DisplayManager;
import android.os.Bundle;
import android.view.Display;

public final class ConsoleActivity extends PanelActivity implements DisplayManager.DisplayListener {
    static final String EXTRA_DISPLAY = "console_display";

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (checkDisplay()) showPanel(Panel.BOTTOM);
    }

    @Override
    protected void onStart() {
        super.onStart();
        getSystemService(DisplayManager.class).registerDisplayListener(this, null);
        checkDisplay();
    }

    @Override
    protected void onResume() {
        super.onResume();
        checkDisplay();
    }

    @Override
    protected void onStop() {
        getSystemService(DisplayManager.class).unregisterDisplayListener(this);
        super.onStop();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (checkDisplay()) showPanel(Panel.BOTTOM);
    }

    @Override
    public void onDisplayAdded(int displayId) {}

    @Override
    public void onDisplayChanged(int displayId) {
        checkDisplay();
    }

    @Override
    public void onDisplayRemoved(int displayId) {
        if (displayId == expectedDisplay()) finishAndRemoveTask();
    }

    private int expectedDisplay() {
        return getIntent().getIntExtra(EXTRA_DISPLAY, Display.INVALID_DISPLAY);
    }

    private boolean checkDisplay() {
        // WindowManager's display follows this Activity on Android 10 as well as newer releases.
        int actual = getWindowManager().getDefaultDisplay().getDisplayId();
        if (actual == Display.DEFAULT_DISPLAY || actual != expectedDisplay()) {
            finishAndRemoveTask();
            return false;
        }
        return true;
    }
}
