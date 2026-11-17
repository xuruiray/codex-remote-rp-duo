package com.xurui.duocodex;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.Set;

/** Coordinates the two Activity tasks on the Android main thread. */
final class PanelExit {
    private static final long EXIT_INTERVAL_MS = 2000;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Set<Activity> panels = new LinkedHashSet<>();
    private Activity armedBy;
    private long deadline;
    private Toast hint;

    void register(Activity activity) {
        panels.add(activity);
    }

    void unregister(Activity activity) {
        cancel(activity);
        panels.remove(activity);
    }

    void cancel(Activity activity) {
        if (armedBy == activity) clear();
    }

    void backPressed(Activity activity, Runnable onTimeout) {
        long now = SystemClock.uptimeMillis();
        if (armedBy != null && now < deadline) {
            clear();
            for (Activity panel : new ArrayList<>(panels)) panel.finishAndRemoveTask();
            return;
        }
        clear();
        armedBy = activity;
        deadline = now + EXIT_INTERVAL_MS;
        hint = Toast.makeText(activity.getApplicationContext(), "再按一次返回键退出 Codex", Toast.LENGTH_SHORT);
        hint.show();
        handler.postAtTime(() -> {
            clear();
            onTimeout.run();
        }, this, deadline);
    }

    private void clear() {
        handler.removeCallbacksAndMessages(this);
        armedBy = null;
        if (hint != null) {
            hint.cancel();
            hint = null;
        }
    }
}
