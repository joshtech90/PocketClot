package de.smartzone.pocketclaude

import android.app.Activity
import android.app.Application
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import androidx.core.content.ContextCompat
import de.smartzone.pocketclaude.data.AppContainer
import de.smartzone.pocketclaude.service.NotificationHelper

class PocketClaudeApp : Application() {
    lateinit var container: AppContainer
        private set

    /** True, solange mindestens eine Activity dieser App im Resumed-State ist. */
    @Volatile var isInForeground: Boolean = false
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(applicationContext)
        NotificationHelper.ensureChannels(this)
        registerActivityLifecycleCallbacks(ForegroundTracker())
        VoiceLaunch.publishShortcut(this)

        // Gesperrte Chats werden erst wieder verriegelt, wenn der Bildschirm
        // ausgeht — NICHT schon beim Wechsel in den Hintergrund (App-Switch,
        // Foto-Picker, kurzer Blick auf eine andere App). Vom User so gewünscht:
        // ein kurzer Kontextwechsel soll einen entsperrten Chat offen lassen,
        // nur das aktive Ausschalten des Displays (Sperren des Geräts) verlangt
        // erneut Fingerabdruck/PIN. ACTION_SCREEN_OFF ist ein geschützter
        // System-Broadcast → dynamische Registrierung, NOT_EXPORTED reicht.
        ContextCompat.registerReceiver(
            this,
            screenOffReceiver,
            IntentFilter(Intent.ACTION_SCREEN_OFF),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
    }

    /** Display aus → alle in dieser Sitzung entsperrten Chats neu verriegeln. */
    private val screenOffReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == Intent.ACTION_SCREEN_OFF) {
                container.chatLock.relockAll()
            }
        }
    }

    private inner class ForegroundTracker : ActivityLifecycleCallbacks {
        private var resumedCount = 0
        override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) {}
        override fun onActivityStarted(activity: Activity) {}
        override fun onActivityResumed(activity: Activity) {
            if (resumedCount == 0) {
                container.settingsSync.onForeground()
                container.drawerData.onForeground()
            }
            resumedCount++
            isInForeground = resumedCount > 0
        }
        override fun onActivityPaused(activity: Activity) {
            resumedCount = (resumedCount - 1).coerceAtLeast(0)
            isInForeground = resumedCount > 0
            if (resumedCount == 0) container.drawerData.onBackground()
        }
        override fun onActivityStopped(activity: Activity) {}
        override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) {}
        override fun onActivityDestroyed(activity: Activity) {}
    }
}
