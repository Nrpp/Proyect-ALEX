package com.alex.assistant

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import java.net.URLEncoder

/**
 * Thin wrapper over SharedPreferences for the connection settings entered in
 * MainActivity. Nothing here is synced anywhere else - same trust model as
 * clients/desktop_minimal (token lives only on this device, entered by hand).
 */
class Prefs(context: Context) {
    private val sp: SharedPreferences =
        context.getSharedPreferences("alex_prefs", Context.MODE_PRIVATE)

    var host: String
        get() = sp.getString("host", "") ?: ""
        set(value) = sp.edit().putString("host", value).apply()

    var port: String
        get() = sp.getString("port", "8787") ?: "8787"
        set(value) = sp.edit().putString("port", value).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(value) = sp.edit().putString("token", value).apply()

    /** Notification priority (0..3) at/above which a full-screen overlay is shown, not just a normal notification. */
    var minOverlayPriority: Int
        get() = sp.getInt("min_overlay_priority", 2)
        set(value) = sp.edit().putInt("min_overlay_priority", value).apply()

    var autoStart: Boolean
        get() = sp.getBoolean("auto_start", false)
        set(value) = sp.edit().putBoolean("auto_start", value).apply()

    val isConfigured: Boolean get() = host.isNotBlank()

    private val clientId: String
        get() = "android-" + Build.MODEL.replace(Regex("[^A-Za-z0-9]"), "_")

    val wsUrl: String
        get() {
            val encodedToken = URLEncoder.encode(token, "UTF-8")
            return "ws://$host:$port/ws?token=$encodedToken&client_id=$clientId"
        }

    val apiBase: String get() = "http://$host:$port"
}
