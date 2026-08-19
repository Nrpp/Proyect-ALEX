package com.alex.assistant

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * The chat screen the README used to say this app deliberately didn't have -
 * added because iOS only gets one via the console PWA added to the home
 * screen, and that's not an option here (no equivalent "add to home screen"
 * story on this app's own UI). Opens its own short-lived WebSocket rather
 * than reusing AlexConnectionService's - the server already supports any
 * number of simultaneous clients per device (protocol.md: chat.reply is
 * broadcast to every connected client), so this stays simple and doesn't
 * risk the foreground service's reconnect/notification logic. Closed in
 * onDestroy - the background service (if running) is what keeps receiving
 * push notifications while this screen isn't open.
 */
class ChatActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs
    private lateinit var messagesContainer: LinearLayout
    private lateinit var scrollMessages: ScrollView
    private lateinit var statusText: TextView
    private lateinit var inputMessage: EditText
    private lateinit var sendBtn: Button

    private val handler = Handler(Looper.getMainLooper())
    private var httpClient: OkHttpClient? = null
    private var webSocket: WebSocket? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_chat)
        prefs = Prefs(this)

        if (!prefs.isConfigured) {
            Toast.makeText(this, getString(R.string.chat_not_configured), Toast.LENGTH_LONG).show()
            finish()
            return
        }

        messagesContainer = findViewById(R.id.messages_container)
        scrollMessages = findViewById(R.id.scroll_messages)
        statusText = findViewById(R.id.text_chat_status)
        inputMessage = findViewById(R.id.input_message)
        sendBtn = findViewById(R.id.btn_send)

        sendBtn.isEnabled = false
        sendBtn.setOnClickListener { sendCurrentInput() }

        connect()
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        webSocket?.close(1000, "chat screen closed")
        httpClient?.dispatcher?.executorService?.shutdown()
        super.onDestroy()
    }

    private fun connect() {
        statusText.text = getString(R.string.chat_connecting)
        val client = OkHttpClient.Builder()
            .pingInterval(25, TimeUnit.SECONDS)
            .build()
        httpClient = client

        val request = Request.Builder().url(prefs.wsUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                handler.post {
                    statusText.text = getString(R.string.chat_connected)
                    sendBtn.isEnabled = true
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                handler.post {
                    statusText.text = getString(R.string.chat_disconnected)
                    sendBtn.isEnabled = false
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                handler.post {
                    statusText.text = getString(R.string.chat_error)
                    sendBtn.isEnabled = false
                    addMessage("sys", getString(R.string.chat_error_detail))
                }
            }
        })
    }

    private fun handleMessage(text: String) {
        val data = try {
            JSONObject(text)
        } catch (_: Exception) {
            return
        }
        when (data.optString("type")) {
            "hello" -> handler.post {
                statusText.text = getString(R.string.chat_connected_to, data.optString("assistant_name", "ALEX"))
            }
            "chat.reply" -> {
                val reply = data.optString("reply")
                if (reply.isNotBlank()) {
                    handler.post {
                        setSending(false)
                        addMessage("alex", reply)
                    }
                }
            }
            "error" -> handler.post {
                setSending(false)
                addMessage("sys", data.optString("message", getString(R.string.chat_error_detail)))
            }
        }
    }

    private fun sendCurrentInput() {
        val text = inputMessage.text.toString().trim()
        if (text.isEmpty()) return
        val ws = webSocket ?: return
        val payload = JSONObject().put("type", "chat.message").put("text", text)
        val sent = ws.send(payload.toString())
        if (!sent) {
            addMessage("sys", getString(R.string.chat_error_detail))
            return
        }
        addMessage("user", text)
        inputMessage.setText("")
        setSending(true)
    }

    private fun setSending(sending: Boolean) {
        sendBtn.isEnabled = !sending
        statusText.text = if (sending) getString(R.string.chat_thinking) else getString(R.string.chat_connected)
    }

    /** Mirrors clients/web_console/index.html's addMessage(role, text): an "ALEX_"/"TU_"
     * meta line in the role's color, followed by the message body. */
    private fun addMessage(role: String, text: String) {
        val meta = TextView(this).apply {
            val prefix = when (role) {
                "alex" -> getString(R.string.chat_prefix_alex)
                "user" -> getString(R.string.chat_prefix_user)
                else -> ""
            }
            this.text = prefix
            setTextColor(if (role == "alex") getColorCompat(R.color.cyan) else getColorCompat(R.color.muted))
            textSize = 10f
            letterSpacing = 0.1f
        }
        val body = TextView(this).apply {
            this.text = text
            setTextColor(if (role == "sys") getColorCompat(R.color.muted) else getColorCompat(R.color.text))
            textSize = 14f
        }
        val wrap = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.START
            setPadding(0, 0, 0, 20)
            addView(meta)
            addView(body)
        }
        messagesContainer.addView(wrap)
        scrollMessages.post { scrollMessages.fullScroll(ScrollView.FOCUS_DOWN) }
    }

    private fun getColorCompat(colorRes: Int): Int = androidx.core.content.ContextCompat.getColor(this, colorRes)
}
