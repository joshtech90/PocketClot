package de.smartzone.pocketclaude.service

import android.app.PendingIntent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import de.smartzone.pocketclaude.VoiceLaunch

/** Schnellkachel "Sprach-Chat": oeffnet einen neuen Chat mit laufendem Diktat. */
class VoiceChatTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        qsTile?.apply {
            state = Tile.STATE_INACTIVE
            updateTile()
        }
    }

    override fun onClick() {
        super.onClick()
        // Auf dem Sperrbildschirm erst entsperren lassen: der Chat zeigt
        // sich nicht ueber der Sperre, und ohne sichtbare App bekommt das
        // Mikrofon nichts.
        if (isLocked) unlockAndRun { openVoiceChat() } else openVoiceChat()
    }

    private fun openVoiceChat() {
        val intent = VoiceLaunch.mainIntent(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(
                PendingIntent.getActivity(
                    this, 0, intent,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
            )
        } else {
            // Android 12/13 kennen nur diese Form; die neue ab 14 steht oben.
            startActivityAndCollapseLegacy(intent)
        }
    }

    @Suppress("DEPRECATION")
    @android.annotation.SuppressLint("StartActivityAndCollapseDeprecated")
    private fun startActivityAndCollapseLegacy(intent: android.content.Intent) {
        startActivityAndCollapse(intent)
    }
}
