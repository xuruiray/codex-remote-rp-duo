package com.xurui.duocodex;

import android.os.Handler;
import android.os.Looper;
import android.view.InputDevice;
import android.view.KeyEvent;
import android.view.MotionEvent;

/** Routes handheld controller input to the reading panel on the Android main thread. */
final class ControllerScroll {
    private static final float DEAD_ZONE = 0.20f;
    private static final int REPEAT_MS = 42;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable tick = this::scroll;
    private BridgePanel reader;
    private boolean up;
    private boolean down;
    private float hat;
    private float stick;
    private boolean repeating;

    void bind(BridgePanel panel) {
        if (reader == panel) return;
        reset();
        reader = panel;
    }

    void unbind(BridgePanel panel) {
        if (reader != panel) return;
        reset();
        reader = null;
    }

    boolean key(KeyEvent event) {
        if (reader == null || !isControllerKey(event)) return false;
        int code = event.getKeyCode();
        if (code != KeyEvent.KEYCODE_DPAD_UP && code != KeyEvent.KEYCODE_DPAD_DOWN) return false;
        int action = event.getAction();
        if (action != KeyEvent.ACTION_DOWN && action != KeyEvent.ACTION_UP) return false;
        if (code == KeyEvent.KEYCODE_DPAD_UP) up = action == KeyEvent.ACTION_DOWN;
        else down = action == KeyEvent.ACTION_DOWN;
        updateRepeat();
        return true;
    }

    private static boolean isControllerKey(KeyEvent event) {
        InputDevice device = event.getDevice();
        return event.isFromSource(InputDevice.SOURCE_DPAD) || event.isFromSource(InputDevice.SOURCE_GAMEPAD)
            || (device != null && device.supportsSource(InputDevice.SOURCE_GAMEPAD));
    }

    boolean motion(MotionEvent event) {
        if (reader == null || !event.isFromSource(InputDevice.SOURCE_JOYSTICK)) return false;
        if (event.getActionMasked() != MotionEvent.ACTION_MOVE) return false;
        hat = event.getAxisValue(MotionEvent.AXIS_HAT_Y);
        stick = strongest(axis(event, MotionEvent.AXIS_Y),
            strongest(axis(event, MotionEvent.AXIS_RZ), axis(event, MotionEvent.AXIS_RY)));
        updateRepeat();
        return true;
    }

    private static float axis(MotionEvent event, int axis) {
        InputDevice device = event.getDevice();
        InputDevice.MotionRange range = device == null ? null : device.getMotionRange(axis, event.getSource());
        float flat = range == null ? DEAD_ZONE : Math.max(DEAD_ZONE, range.getFlat());
        float value = event.getAxisValue(axis);
        return Math.abs(value) > flat ? value : 0;
    }

    private static float strongest(float first, float second) {
        return Math.abs(first) >= Math.abs(second) ? first : second;
    }

    private float direction() {
        if (up != down) return down ? 1 : -1;
        return hat != 0 ? hat : stick;
    }

    private void updateRepeat() {
        if (direction() == 0) {
            handler.removeCallbacks(tick);
            repeating = false;
        } else if (!repeating) {
            repeating = true;
            scroll();
        }
    }

    private void scroll() {
        if (reader == null || !repeating) return;
        float value = direction();
        int distance = Math.round(16 + 44 * Math.min(1, Math.abs(value)));
        reader.scrollReading(value < 0 ? -distance : distance);
        handler.postDelayed(tick, REPEAT_MS);
    }

    void reset() {
        handler.removeCallbacks(tick);
        up = false;
        down = false;
        hat = 0;
        stick = 0;
        repeating = false;
    }
}
