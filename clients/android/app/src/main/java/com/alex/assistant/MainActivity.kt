package com.alex.assistant

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

/**
 * Settings + control screen: connection details, the two permissions this
 * app needs (notifications, draw-over-other-apps), and start/stop for
 * AlexConnectionService. Deliberately minimal - the actual conversation
 * happens through /console/ or the desktop client; this app's job is
 * background connectivity + notifications/overlays.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var prefs: Prefs

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* result not critical to handle here */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        prefs = Prefs(this)

        val hostInput = findViewById<EditText>(R.id.input_host)
        val portInput = findViewById<EditText>(R.id.input_port)
        val tokenInput = findViewById<EditText>(R.id.input_token)
        val autoStartSwitch = findViewById<Switch>(R.id.switch_autostart)
        val overlayPermissionBtn = findViewById<Button>(R.id.btn_overlay_permission)
        val saveBtn = findViewById<Button>(R.id.btn_save)
        val startBtn = findViewById<Button>(R.id.btn_start)
        val stopBtn = findViewById<Button>(R.id.btn_stop)
        val statusText = findViewById<TextView>(R.id.text_status)

        hostInput.setText(prefs.host)
        portInput.setText(prefs.port)
        tokenInput.setText(prefs.token)
        autoStartSwitch.isChecked = prefs.autoStart

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
        }

        overlayPermissionBtn.setOnClickListener {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
                startActivity(
                    Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                )
            } else {
                Toast.makeText(this, "Permiso ya concedido", Toast.LENGTH_SHORT).show()
            }
        }

        saveBtn.setOnClickListener {
            prefs.host = hostInput.text.toString().trim()
            prefs.port = portInput.text.toString().trim().ifBlank { "8787" }
            prefs.token = tokenInput.text.toString().trim()
            prefs.autoStart = autoStartSwitch.isChecked
            Toast.makeText(this, "Guardado", Toast.LENGTH_SHORT).show()
        }

        startBtn.setOnClickListener {
            if (!prefs.isConfigured) {
                Toast.makeText(this, "Guarda el host primero", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            ContextCompat.startForegroundService(this, Intent(this, AlexConnectionService::class.java))
            statusText.text = "Servicio iniciado - revisa la notificacion persistente para el estado"
        }

        stopBtn.setOnClickListener {
            stopService(Intent(this, AlexConnectionService::class.java))
            statusText.text = "Servicio detenido"
        }
    }
}
