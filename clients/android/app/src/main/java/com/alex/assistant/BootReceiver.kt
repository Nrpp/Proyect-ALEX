package com.alex.assistant

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

/** Restarts the connection service after a reboot, only if the user opted into it in MainActivity. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = Prefs(context)
        if (prefs.isConfigured && prefs.autoStart) {
            ContextCompat.startForegroundService(context, Intent(context, AlexConnectionService::class.java))
        }
    }
}
