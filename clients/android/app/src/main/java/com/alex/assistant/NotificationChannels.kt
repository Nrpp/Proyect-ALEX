package com.alex.assistant

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build

/**
 * One Android notification channel per ALEX priority level (0..3, see
 * clients/protocol.md), plus a silent one for the persistent foreground
 * service notification. Channel importance is fixed once created on
 * Android 8+, which is why priority maps to a channel rather than a
 * per-notification flag.
 */
object NotificationChannels {
    const val SERVICE_CHANNEL = "alex_service"
    const val INFO_CHANNEL = "alex_info"
    const val NORMAL_CHANNEL = "alex_normal"
    const val HIGH_CHANNEL = "alex_high"
    const val CRITICAL_CHANNEL = "alex_critical"

    fun create(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = context.getSystemService(NotificationManager::class.java) ?: return

        nm.createNotificationChannel(
            NotificationChannel(SERVICE_CHANNEL, "Conexion con ALEX", NotificationManager.IMPORTANCE_MIN).apply {
                description = "Notificacion persistente mientras el servicio de ALEX esta activo."
                setShowBadge(false)
            }
        )
        nm.createNotificationChannel(
            NotificationChannel(INFO_CHANNEL, "ALEX - Informativo", NotificationManager.IMPORTANCE_LOW)
        )
        nm.createNotificationChannel(
            NotificationChannel(NORMAL_CHANNEL, "ALEX - Normal", NotificationManager.IMPORTANCE_DEFAULT)
        )
        nm.createNotificationChannel(
            NotificationChannel(HIGH_CHANNEL, "ALEX - Importante", NotificationManager.IMPORTANCE_HIGH)
        )
        nm.createNotificationChannel(
            NotificationChannel(CRITICAL_CHANNEL, "ALEX - Critico", NotificationManager.IMPORTANCE_HIGH).apply {
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 400, 200, 400)
            }
        )
    }

    fun channelFor(priority: Int): String = when (priority) {
        0 -> INFO_CHANNEL
        1 -> NORMAL_CHANNEL
        2 -> HIGH_CHANNEL
        else -> CRITICAL_CHANNEL
    }
}
