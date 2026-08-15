package com.alex.assistant

import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException

/**
 * REST calls used to resolve notification actions - the same two endpoints
 * clients/desktop_minimal/client.py and clients/web_console/index.html use.
 * Fire-and-forget by design: these run from a notification/overlay button
 * tap, there's no UI waiting on the result.
 */
class ApiClient(private val prefs: Prefs) {
    private val client = OkHttpClient()
    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()
    private val noopCallback = object : Callback {
        override fun onFailure(call: Call, e: IOException) { /* best-effort */ }
        override fun onResponse(call: Call, response: Response) { response.close() }
    }

    fun confirmAction(actionId: String, approved: Boolean) {
        val body = JSONObject().put("approved", approved).toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url("${prefs.apiBase}/actions/$actionId/confirm")
            .addHeader("Authorization", "Bearer ${prefs.token}")
            .post(body)
            .build()
        client.newCall(request).enqueue(noopCallback)
    }

    fun setNotificationStatus(notificationId: String, status: String) {
        val body = JSONObject().put("status", status).toString().toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url("${prefs.apiBase}/notifications/$notificationId/status")
            .addHeader("Authorization", "Bearer ${prefs.token}")
            .post(body)
            .build()
        client.newCall(request).enqueue(noopCallback)
    }
}
