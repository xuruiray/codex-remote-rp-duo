package com.xurui.duocodex;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.res.ColorStateList;
import android.view.inputmethod.InputMethodManager;
import android.text.InputFilter;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import java.util.function.Consumer;

/** Keeps sidebar text edits on the display that owns the keyboard. */
final class ConsoleTextInput {
    private Activity console;
    private Runnable restoreKeyboard;
    private AlertDialog dialog;

    void bind(Activity activity, Runnable restore) {
        console = activity;
        restoreKeyboard = restore;
    }

    void unbind(Activity activity) {
        if (console != activity) return;
        if (dialog != null) dialog.dismiss();
        console = null;
        restoreKeyboard = null;
    }

    void show(String value, Consumer<String> reply) {
        if (console == null || console.isFinishing()) {
            reply.accept(null);
            return;
        }
        if (dialog != null) dialog.dismiss();
        EditText input = new EditText(console);
        input.setSingleLine(true);
        input.setBackgroundTintList(ColorStateList.valueOf(0xFFFFDA3A));
        input.setFilters(new InputFilter[]{new InputFilter.LengthFilter(120)});
        input.setText(value);
        input.setSelectAllOnFocus(true);
        input.setImeOptions(EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_EXTRACT_UI
            | EditorInfo.IME_FLAG_NO_FULLSCREEN);
        AlertDialog editor = new AlertDialog.Builder(console)
            .setTitle("重命名会话")
            .setView(input)
            .setPositiveButton("确定", (ignored, which) -> reply.accept(input.getText().toString()))
            .setNegativeButton("取消", (ignored, which) -> reply.accept(null))
            .create();
        editor.setCanceledOnTouchOutside(false);
        editor.setOnCancelListener(ignored -> reply.accept(null));
        editor.setOnDismissListener(ignored -> {
            if (dialog == editor) dialog = null;
            if (restoreKeyboard != null) restoreKeyboard.run();
        });
        editor.setOnShowListener(ignored -> {
            input.requestFocus();
            editor.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(0xFFFFDA3A);
            editor.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(0xFFFFF4DC);
            input.postDelayed(() -> {
                if (editor.isShowing()) console.getSystemService(InputMethodManager.class)
                    .showSoftInput(input, InputMethodManager.SHOW_IMPLICIT);
            }, 160);
        });
        input.setOnEditorActionListener((view, action, event) -> {
            if (action != EditorInfo.IME_ACTION_DONE) return false;
            editor.getButton(AlertDialog.BUTTON_POSITIVE).performClick();
            return true;
        });
        dialog = editor;
        editor.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE
            | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        editor.show();
    }
}
