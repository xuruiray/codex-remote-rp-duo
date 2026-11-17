package com.xurui.duocodex;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

public final class PairActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        String token = getIntent().getStringExtra("pairing_token");
        String lanHost = getIntent().getStringExtra("lan_host");
        if (!Pairing.save(this, token, lanHost)) {
            finish();
            return;
        }
        Intent open = new Intent(this, MainActivity.class);
        open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(open);
        finish();
    }
}
