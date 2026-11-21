package top.ponychat.companion

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import top.ponychat.companion.agent.AgentEventListener
import top.ponychat.companion.agent.AgentRuntime
import top.ponychat.companion.agent.AgentTask
import top.ponychat.companion.agent.DemoBrainClient
import top.ponychat.companion.agent.DemoDeviceAdapter
import top.ponychat.companion.agent.DemoResultVerifier
import top.ponychat.companion.android.CompanionAccessibilityService
import top.ponychat.companion.overlay.OverlayAgentEventListener

class MainActivity : Activity() {
    private lateinit var serviceStatus: TextView
    private lateinit var logView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContent())
    }

    override fun onResume() {
        super.onResume()
        updateServiceStatus()
    }

    private fun buildContent(): ScrollView {
        val density = resources.displayMetrics.density
        fun dp(value: Int) = (value * density).toInt()

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dp(24), dp(40), dp(24), dp(32))
            setBackgroundColor(Color.rgb(247, 242, 250))
        }

        content.addView(TextView(this).apply {
            text = getString(R.string.app_name)
            textSize = 30f
            setTextColor(Color.rgb(31, 27, 36))
        }, matchWrap())

        content.addView(TextView(this).apply {
            text = getString(R.string.tagline)
            textSize = 16f
            setTextColor(Color.DKGRAY)
            setPadding(0, dp(8), 0, dp(24))
        }, matchWrap())

        serviceStatus = TextView(this).apply {
            textSize = 16f
            setPadding(dp(16), dp(16), dp(16), dp(16))
            setBackgroundColor(Color.WHITE)
        }
        content.addView(serviceStatus, matchWrap())

        content.addView(Button(this).apply {
            text = getString(R.string.open_accessibility_settings)
            setOnClickListener {
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            }
        }, matchWrap(top = dp(16)))

        content.addView(Button(this).apply {
            text = getString(R.string.run_agent_demo)
            setOnClickListener { runDemo() }
        }, matchWrap(top = dp(8)))

        content.addView(TextView(this).apply {
            text = getString(R.string.capabilities)
            textSize = 15f
            setTextColor(Color.rgb(50, 47, 55))
            setPadding(dp(16), dp(16), dp(16), dp(16))
            setBackgroundColor(Color.WHITE)
        }, matchWrap(top = dp(16)))

        logView = TextView(this).apply {
            text = getString(R.string.log_placeholder)
            textSize = 14f
            setTextColor(Color.rgb(50, 47, 55))
            setPadding(dp(16), dp(16), dp(16), dp(16))
            setBackgroundColor(Color.WHITE)
        }
        content.addView(logView, matchWrap(top = dp(16)))

        return ScrollView(this).apply { addView(content) }
    }

    private fun matchWrap(top: Int = 0) = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT,
        ViewGroup.LayoutParams.WRAP_CONTENT,
    ).apply { topMargin = top }

    private fun updateServiceStatus() {
        val enabled = CompanionAccessibilityService.instance != null
        serviceStatus.text = if (enabled) {
            getString(R.string.service_connected)
        } else {
            getString(R.string.service_disconnected)
        }
        serviceStatus.setTextColor(if (enabled) Color.rgb(30, 110, 55) else Color.rgb(150, 65, 45))
    }

    private fun runDemo() {
        logView.text = ""
        Thread {
            val lines = mutableListOf<String>()
            val runtime = AgentRuntime(
                brain = DemoBrainClient(),
                device = DemoDeviceAdapter(),
                verifier = DemoResultVerifier(),
                listener = AgentEventListener { message ->
                    lines += message
                    OverlayAgentEventListener(this).onEvent(message)
                    runOnUiThread { logView.text = lines.joinToString("\n") }
                },
            )
            val outcome = runtime.run(
                AgentTask(
                    id = "demo-${System.currentTimeMillis()}",
                    instruction = "完成 PonyChat Companion Agent 闭环演示",
                ),
            )
            lines += "结果：${outcome.status} — ${outcome.summary}"
            runOnUiThread { logView.text = lines.joinToString("\n") }
        }.start()
    }
}
