package com.alex.assistant

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONObject

/**
 * Draws a HUD-style alert on top of whatever app is in the foreground, for
 * notifications at/above the configured priority threshold - the Android
 * equivalent of clients/desktop_minimal's always-on-top Tk popup. Requires
 * the "draw over other apps" permission (SYSTEM_ALERT_WINDOW), granted by
 * the user via Settings.ACTION_MANAGE_OVERLAY_PERMISSION (see MainActivity).
 */
class OverlayManager(private val context: Context, private val apiClient: ApiClient) {

    private val windowManager = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var currentView: View? = null

    fun canDrawOverlays(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(context)

    fun show(notification: JSONObject) {
        if (!canDrawOverlays()) return
        dismiss()

        val priority = notification.optInt("priority", 1)
        val accent = when (priority) {
            0 -> Color.parseColor("#5C7A86")
            1 -> Color.parseColor("#22E8FF")
            2 -> Color.parseColor("#FFB020")
            else -> Color.parseColor("#FF3B5C")
        }

        val root = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(40, 32, 40, 32)
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#EE0A131A"))
                setStroke(3, accent)
                cornerRadius = 6f
            }
        }

        root.addView(TextView(context).apply {
            text = notification.optString("title")
            setTextColor(Color.WHITE)
            textSize = 17f
            setTypeface(typeface, Typeface.BOLD)
        })

        root.addView(TextView(context).apply {
            text = notification.optString("body")
            setTextColor(Color.parseColor("#D8FAFF"))
            textSize = 14f
            setPadding(0, 14, 0, 22)
        })

        val notifId = notification.optString("id").ifBlank { null }
        val actions = notification.optJSONArray("actions")
        val buttonRow = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL }

        if (actions != null && actions.length() > 0) {
            for (i in 0 until actions.length()) {
                val action = actions.getJSONObject(i)
                buttonRow.addView(actionButton(action.optString("label", action.optString("id"))) {
                    val actionId = action.optString("action_id").ifBlank { null }
                    val approved = action.optString("id") == "confirm"
                    if (actionId != null) apiClient.confirmAction(actionId, approved)
                    if (notifId != null) apiClient.setNotificationStatus(notifId, if (approved) "acted" else "dismissed")
                    dismiss()
                })
            }
        } else {
            buttonRow.addView(actionButton("Entendido") {
                if (notifId != null) apiClient.setNotificationStatus(notifId, "dismissed")
                dismiss()
            })
        }
        root.addView(buttonRow)

        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else
            @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP
            y = 90
        }

        windowManager.addView(root, params)
        currentView = root

        // Critical (priority 3) alerts stay until dismissed; everything else auto-dismisses.
        if (priority < 3) {
            root.postDelayed({ dismiss() }, 15000)
        }
    }

    fun dismiss() {
        currentView?.let {
            try {
                windowManager.removeView(it)
            } catch (_: IllegalArgumentException) {
                // View was already removed (e.g. dismissed twice in a race) - safe to ignore.
            }
        }
        currentView = null
    }

    private fun actionButton(label: String, onClick: () -> Unit): Button =
        Button(context).apply {
            text = label
            setOnClickListener { onClick() }
        }
}
