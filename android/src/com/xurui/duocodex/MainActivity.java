package com.xurui.duocodex;

import android.app.ActivityOptions;
import android.content.Intent;
import android.hardware.display.DisplayManager;
import android.util.Log;
import android.view.Display;
import android.view.WindowManager;

public final class MainActivity extends PanelActivity implements DisplayManager.DisplayListener {
    private static final int NO_CONSOLE = Display.INVALID_DISPLAY;
    private int consoleDisplay = NO_CONSOLE;
    private boolean panelShown;

    @Override
    protected void onStart() {
        super.onStart();
        getSystemService(DisplayManager.class).registerDisplayListener(this, null);
        updateDisplays(false);
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
        updateDisplays(true);
    }

    @Override
    public void onDisplayAdded(int displayId) {
        updateDisplays(false);
    }

    @Override
    public void onDisplayRemoved(int displayId) {
        updateDisplays(false);
    }

    @Override
    public void onDisplayChanged(int displayId) {
        updateDisplays(false);
    }

    private void updateDisplays(boolean reopen) {
        if (isFinishing()) return;
        int target = findConsoleDisplay();
        if (!reopen && panelShown && target == consoleDisplay) return;
        boolean dual = target != NO_CONSOLE && launchConsole(target);
        consoleDisplay = dual ? target : NO_CONSOLE;
        panelShown = true;
        if (dual) getWindow().addFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        showPanel(dual ? Panel.TOP : Panel.SINGLE);
    }

    private int findConsoleDisplay() {
        for (Display display : getSystemService(DisplayManager.class).getDisplays()) {
            if (display.getDisplayId() == Display.DEFAULT_DISPLAY) continue;
            Display.Mode mode = display.getMode();
            if (Math.max(mode.getPhysicalWidth(), mode.getPhysicalHeight()) == 1280
                    && Math.min(mode.getPhysicalWidth(), mode.getPhysicalHeight()) == 960) {
                return display.getDisplayId();
            }
        }
        return NO_CONSOLE;
    }

    private boolean launchConsole(int displayId) {
        ActivityOptions options = ActivityOptions.makeBasic();
        options.setLaunchDisplayId(displayId);
        Intent intent = new Intent(this, ConsoleActivity.class);
        intent.putExtra(ConsoleActivity.EXTRA_DISPLAY, displayId);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            startActivity(intent, options.toBundle());
            return true;
        } catch (RuntimeException error) {
            Log.w("DuoCodex", "Secondary display unavailable", error);
            return false;
        }
    }
}
