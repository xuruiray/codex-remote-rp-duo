package com.xurui.duocodex;

import android.content.Context;
import android.content.SharedPreferences;
import android.net.InetAddresses;
import android.net.Uri;

import java.net.Inet4Address;

final class Pairing {
    private static final int USB_PORT = 38457;
    private static final int WIFI_PORT = USB_PORT + 1;
    private static final String USB_HOST = "127.0.0.1";
    private final String token;
    private final String wifiHost;

    private Pairing(String token, String wifiHost) {
        this.token = token != null && token.matches("[A-Za-z0-9_-]{32,192}") ? token : "";
        this.wifiHost = isIpv4(wifiHost) ? wifiHost : "";
    }

    static Pairing read(Context context) {
        SharedPreferences preferences = preferences(context);
        return new Pairing(preferences.getString("token", ""), preferences.getString("lan_host", ""));
    }

    static boolean save(Context context, String token, String wifiHost) {
        Pairing pairing = new Pairing(token, wifiHost);
        if (!pairing.isConfigured()) return false;
        preferences(context).edit()
            .putString("token", pairing.token)
            .putString("lan_host", pairing.wifiHost)
            .apply();
        return true;
    }

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences("connection", Context.MODE_PRIVATE);
    }

    private static boolean isIpv4(String host) {
        if (host == null || host.isEmpty()) return false;
        try {
            return InetAddresses.parseNumericAddress(host) instanceof Inet4Address;
        } catch (IllegalArgumentException error) {
            return false;
        }
    }

    boolean isConfigured() {
        return !token.isEmpty();
    }

    boolean hasWifi() {
        return !wifiHost.isEmpty();
    }

    boolean matches(Pairing other) {
        return token.equals(other.token) && wifiHost.equals(other.wifiHost);
    }

    String origin(boolean wifi) {
        return "https://" + (wifi ? wifiHost + ":" + WIFI_PORT : USB_HOST + ":" + USB_PORT);
    }

    boolean allows(Uri uri, boolean wifi) {
        return "https".equals(uri.getScheme())
            && (wifi ? wifiHost : USB_HOST).equals(uri.getHost())
            && uri.getPort() == (wifi ? WIFI_PORT : USB_PORT)
            && uri.getUserInfo() == null && "/".equals(uri.getPath());
    }

    String panelUrl(Panel panel, boolean wifi, long navigation) {
        return Uri.parse(origin(wifi) + "/").buildUpon()
            .appendQueryParameter("panel", panel.wireName)
            .appendQueryParameter("navigation", Long.toString(navigation))
            .encodedFragment("panel=" + panel.wireName + "&token=" + Uri.encode(token))
            .build().toString();
    }
}
