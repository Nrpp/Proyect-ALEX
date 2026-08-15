package com.alex.assistant

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Foreground service that keeps a persistent WebSocket connection to ALEX
 * open (see clients/protocol.md) for as long as the user wants it running -
 * this is the "background access" the desktop/web clients don't have, since
 * a phone needs a foreground service (not just a background thread) to stay
 * alive reliably under Android's battery/Doze restrictions.
 *
 * On each "notification" push it always posts a normal Android notification,
 * and additionally shows a HUD overlay (OverlayManager) for anything at or
 * above the configured priority threshold - satisfying "avisame de verdad
 * cuando importa, sin no molestar el resto del tiempo".
 */
class AlexConnectionService : Service() {

    private lateinit var prefs: Prefs
    private lateinit var apiClient: ApiClient
    private lateinit var overlayManager: OverlayManager
    private val handler = Handler(Looper.getMainLooper())

    private var httpClient: OkHttpClient? = null
    private var webSocket: WebSocket? = null
    private var reconnectDelayMs = 1500L
    private val notificationId = 1

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        apiClient = ApiClient(prefs)
        overlayManager = OverlayManager(this, apiClient)
        NotificationChannels.create(this)
        startForeground(notificationId, buildServiceNotification("Conectando..."))
        connect()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        webSocket?.close(1000, "service stopping")
        httpClient?.dispatcher?.executorService?.shutdown()
        overlayManager.dismiss()
        super.onDestroy()
    }

    private fun connect() {
        if (!prefs.isConfigured) {
            updateServiceNotification("Sin configurar - abre la app")
            return
        }

        val client = OkHttpClient.Builder()
            .pingInterval(25, TimeUnit.SECONDS)
            .build()
        httpClient = client

        val request = Request.Builder().url(prefs.wsUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                reconnectDelayMs = 1500L
                handler.post { updateServiceNotification("Conectado") }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                handler.post { updateServiceNotification("Desconectado - reintentando...") }
                scheduleReconnect()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                handler.post { updateServiceNotification("Error de conexion - reintentando...") }
                scheduleReconnect()
            }
        })
    }

    private fun scheduleReconnect() {
        handler.postDelayed({ connect() }, reconnectDelayMs)
        reconnectDelayMs = (reconnectDelayMs * 1.6).toLong().coerceAtMost(30000L)
    }

    private fun handleMessage(text: String) {
        val data = try {
            JSONObject(text)
        } catch (_: Exception) {
            return
        }
        when (data.optString("type")) {
            "hello" -> handler.post {
                updateServiceNotification("Conectado a ${data.optString("assistant_name", "ALEX")}")
            }
            "notification" -> {
                val notification = data.optJSONObject("notification") ?: return
                handler.post { handleNotification(notification) }
            }
        }
    }

    private fun handleNotification(notification: JSONObject) {
        val priority = notification.optInt("priority", 1)
        postAndroidNotification(notification, priority)
        if (priority >= prefs.minOverlayPriority && overlayManager.canDrawOverlays()) {
            overlayManager.show(notification)
        }
    }

    private fun postAndroidNotification(notification: JSONObject, priority: Int) {
        val nm = getSystemService(NotificationManager::class.java) ?: return
        val androidPriority = when (priority) {
            3 -> NotificationCompat.PRIORITY_MAX
            2 -> NotificationCompat.PRIORITY_HIGH
            0 -> NotificationCompat.PRIORITY_LOW
            else -> NotificationCompat.PRIORITY_DEFAULT
        }
        val builder = NotificationCompat.Builder(this, NotificationChannels.channelFor(priority))
            .setContentTitle(notification.optString("title"))
            .setContentText(notification.optString("body"))
            .setStyle(NotificationCompat.BigTextStyle().bigText(notification.optString("body")))
            .setSmallIcon(R.drawable.ic_notification)
            .setPriority(androidPriority)
            .setAutoCancel(true)

        val id = notification.optString("id").ifBlank { System.currentTimeMillis().toString() }
        nm.notify(id.hashCode(), builder.build())
    }

    private fun buildServiceNotification(status: String): Notification {
        val contentIntent = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, NotificationChannels.SERVICE_CHANNEL)
            .setContentTitle("ALEX")
            .setContentText(status)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateServiceNotification(status: String) {
        val nm = getSystemService(NotificationManager::class.java) ?: return
        nm.notify(notificationId, buildServiceNotification(status))
    }
}
