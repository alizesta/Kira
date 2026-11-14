package ai.kira.mobile.assistant

import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.IBinder
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.TextView
import ai.kira.mobile.MainActivity
import ai.kira.mobile.R

class AiAssistantOverlayService : Service() {
    private var windowManager: WindowManager? = null
    private var bubble: TextView? = null
    private var bubbleParams: WindowManager.LayoutParams? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> stopSelf()
            else -> showBubbleIfAllowed()
        }
        return START_NOT_STICKY
    }

    private fun showBubbleIfAllowed() {
        if (!Settings.canDrawOverlays(this) || bubble != null) return

        val manager = getSystemService(WINDOW_SERVICE) as WindowManager
        val view = TextView(this).apply {
            text = "K"
            textSize = 21f
            setTextColor(0xFFFFFFFF.toInt())
            gravity = Gravity.CENTER
            elevation = 12f
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(0xFF7661D8.toInt())
                setStroke(2, 0xFFB9A5FF.toInt())
            }
            contentDescription = "باز کردن دستیار Kira"
        }

        val params = WindowManager.LayoutParams(
            dp(58),
            dp(58),
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dp(18)
            y = dp(220)
        }

        attachTouchBehavior(view, params, manager)
        manager.addView(view, params)
        windowManager = manager
        bubble = view
        bubbleParams = params
    }

    private fun attachTouchBehavior(
        view: View,
        params: WindowManager.LayoutParams,
        manager: WindowManager
    ) {
        var downX = 0f
        var downY = 0f
        var startX = 0
        var startY = 0

        view.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX
                    downY = event.rawY
                    startX = params.x
                    startY = params.y
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    params.x = (startX + downX - event.rawX).toInt().coerceAtLeast(0)
                    params.y = (startY + event.rawY - downY).toInt().coerceAtLeast(0)
                    manager.updateViewLayout(view, params)
                    true
                }
                MotionEvent.ACTION_UP -> {
                    val moved = kotlin.math.hypot(
                        event.rawX - downX,
                        event.rawY - downY
                    )
                    if (moved < dp(10)) openMainActivity()
                    true
                }
                else -> true
            }
        }
    }

    private fun openMainActivity() {
        val intent = Intent(this, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        }
        startActivity(intent)
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()

    override fun onDestroy() {
        bubble?.let { view ->
            runCatching { windowManager?.removeView(view) }
        }
        bubble = null
        bubbleParams = null
        windowManager = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_START = "ai.kira.mobile.action.START_ASSISTANT_OVERLAY"
        const val ACTION_STOP = "ai.kira.mobile.action.STOP_ASSISTANT_OVERLAY"
    }
}
