package com.xurui.duocodex;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.net.Uri;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;

import java.io.IOException;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;
import java.util.function.Predicate;
import javax.net.ssl.HttpsURLConnection;

/** Owns the authenticated WebView and keeps its connection tied to the visible panel. */
final class BridgePanel extends FrameLayout {
    private static final int BACKGROUND = 0xFF17130E;
    private static final long RETRY_DELAY_MS = 2200;
    private static final long PROBE_INTERVAL_MS = 3000;

    private final Button retry;
    private final Runnable restoreKeyboard;
    private final ConsoleTextInput consoleTextInput;
    private final Predicate<KeyEvent> controllerKey;
    private final ExecutorService probes = Executors.newSingleThreadExecutor();
    private final Runnable reconnect = this::connect;
    private WebView web;
    private Pairing pairing;
    private Panel panel;
    private boolean usingWifi;
    private boolean started;
    private boolean probing;
    private long lastProbe;
    private long navigation;
    private String pendingDraft;
    private boolean pageFailed;
    private boolean ready;

    BridgePanel(Context context, Runnable restoreKeyboard, Predicate<KeyEvent> controllerKey, ConsoleTextInput consoleTextInput) {
        super(context);
        this.restoreKeyboard = restoreKeyboard;
        this.consoleTextInput = consoleTextInput;
        this.controllerKey = controllerKey;
        setBackgroundColor(BACKGROUND);
        retry = new Button(context);
        retry.setBackgroundTintList(ColorStateList.valueOf(Color.rgb(255, 218, 58)));
        retry.setTextColor(Color.rgb(40, 26, 12));
        retry.setVisibility(GONE);
        retry.setOnClickListener(view -> connect());
        addView(retry, new LayoutParams(LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        createWebView();
    }

    private void createWebView() {
        web = new WebView(getContext()) {
            @Override
            public boolean onKeyPreIme(int keyCode, KeyEvent event) {
                return controllerKey.test(event) || super.onKeyPreIme(keyCode, event);
            }
        };
        web.setBackgroundColor(BACKGROUND);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.addJavascriptInterface(new Object() {
            @JavascriptInterface
            public void checkAlternate() {
                post(BridgePanel.this::checkAlternate);
            }

            @JavascriptInterface
            public void editText(String field, String value) {
                if (!field.equals("session-name")) return;
                post(() -> {
                    if (panel != Panel.TOP || !started || !ready) return;
                    long page = navigation;
                    consoleTextInput.show(value, answer -> {
                        if (page != navigation || !started || !ready) return;
                        String result = answer == null ? "null" : org.json.JSONObject.quote(answer);
                        web.evaluateJavascript("window.DuoPanel?.acceptConsoleText("
                            + org.json.JSONObject.quote(field) + "," + result + ")", null);
                    });
                });
            }

            @JavascriptInterface
            public void consoleInputChanged() {
                post(() -> {
                    if (panel == Panel.BOTTOM && started && ready) restoreKeyboard.run();
                });
            }
        }, "DuoConnection");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return !request.isForMainFrame() || !isCurrentPage(view, request.getUrl());
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (pageFailed || !isCurrentPage(view, Uri.parse(url))) return;
                ready = true;
                view.setVisibility(VISIBLE);
                retry.setVisibility(GONE);
                if (pendingDraft != null) {
                    long page = navigation;
                    view.evaluateJavascript("window.DuoPanel?.restoreDraft(" + pendingDraft + ")", applied -> {
                        if (page == navigation && "true".equals(applied)) pendingDraft = null;
                    });
                }
                restoreKeyboard.run();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && isCurrentPage(view, request.getUrl())) handleLoadFailure();
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse error) {
                if (request.isForMainFrame() && isCurrentPage(view, request.getUrl())) handleLoadFailure();
            }

            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                if (view != web) return true;
                destroyWebView();
                createWebView();
                showRetry();
                return true;
            }
        });
        addView(web, 0, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT));
    }

    void show(Panel role) {
        Pairing configuration = Pairing.read(getContext());
        if (role == panel && pairing != null && pairing.matches(configuration)
                && (ready || (navigation > 0 && !pageFailed))) return;
        pendingDraft = null;
        panel = role;
        pairing = configuration;
        connect();
    }

    void start() {
        started = true;
        web.onResume();
        if (retry.getVisibility() == VISIBLE) scheduleReconnect();
    }

    void stop() {
        started = false;
        removeCallbacks(reconnect);
        web.onPause();
    }

    void destroy() {
        started = false;
        removeCallbacks(reconnect);
        probes.shutdownNow();
        destroyWebView();
    }

    private void destroyWebView() {
        ++navigation;
        ready = false;
        removeView(web);
        web.destroy();
        web = null;
    }

    void focusComposer(Consumer<WebView> focused) {
        if (!ready) return;
        WebView view = web;
        long page = navigation;
        view.requestFocus();
        view.evaluateJavascript("window.DuoPanel?.focusComposer()", accepted -> {
            if (page == navigation && started && "true".equals(accepted)) focused.accept(view);
        });
    }

    void scrollReading(int pixels) {
        if (ready && started) web.evaluateJavascript("window.DuoPanel?.scrollReading(" + pixels + ")", null);
    }

    private void connect() {
        removeCallbacks(reconnect);
        if (!pairing.isConfigured()) {
            retry.setText("请在 Mac 上启动 USB 连接");
            showRetry();
            return;
        }
        retry.setText("连接 Mac · 点击重试");
        usingWifi = pairing.hasWifi();
        load();
    }

    private void load() {
        ready = false;
        pageFailed = false;
        web.loadUrl(pairing.panelUrl(panel, usingWifi, ++navigation));
    }

    private boolean isCurrentPage(WebView view, Uri uri) {
        return view == web && pairing != null && pairing.allows(uri, usingWifi)
            && Long.toString(navigation).equals(uri.getQueryParameter("navigation"));
    }

    private void handleLoadFailure() {
        if (pageFailed) return;
        pageFailed = true;
        if (usingWifi) {
            usingWifi = false;
            load();
        } else {
            showRetry();
        }
    }

    private void showRetry() {
        ready = false;
        pageFailed = true;
        web.setVisibility(INVISIBLE);
        retry.setVisibility(VISIBLE);
        scheduleReconnect();
    }

    private void scheduleReconnect() {
        removeCallbacks(reconnect);
        if (started && pairing != null && pairing.isConfigured()) postDelayed(reconnect, RETRY_DELAY_MS);
    }

    private void checkAlternate() {
        long now = SystemClock.elapsedRealtime();
        if (!started || !ready || !pairing.hasWifi() || probing || now - lastProbe < PROBE_INTERVAL_MS) return;
        probing = true;
        lastProbe = now;
        long page = navigation;
        boolean alternateWifi = !usingWifi;
        String endpoint = pairing.origin(alternateWifi);
        probes.execute(() -> {
            boolean available = reachable(endpoint);
            post(() -> {
                probing = false;
                if (!started || !available || page != navigation) return;
                web.evaluateJavascript("window.DuoPanel?.captureDraft()", draft -> {
                    if (!started || page != navigation || draft == null || "null".equals(draft)) return;
                    pendingDraft = draft;
                    usingWifi = alternateWifi;
                    load();
                });
            });
        });
    }

    private static boolean reachable(String endpoint) {
        HttpsURLConnection connection = null;
        try {
            connection = (HttpsURLConnection) new URL(endpoint + "/").openConnection();
            connection.setConnectTimeout(1800);
            connection.setReadTimeout(1800);
            connection.setInstanceFollowRedirects(false);
            return connection.getResponseCode() == 200;
        } catch (IOException ignored) {
            return false;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }
}
