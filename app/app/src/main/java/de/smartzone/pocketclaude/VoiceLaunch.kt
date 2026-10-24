package de.smartzone.pocketclaude

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat

/**
 * "Neuer Sprach-Chat": ein frischer Chat, in dem das Diktat sofort laeuft.
 *
 * Drei Wege fuehren hierher, weil nicht jedes Handy die Power-Taste an
 * Dritt-Apps weitergibt:
 * - Assistenten-Taste/-Geste (ACTION_ASSIST an [VoiceChatActivity]), sobald
 *   PocketClot als Standard-Assistent gewaehlt ist. Auf Pixel und Samsung
 *   haengt das lange Druecken der Power-Taste daran; manche Hersteller
 *   (berichtet fuer vivo mit OriginOS 6) leiten sie fest an den eigenen
 *   Assistenten.
 * - Schnellkachel ([de.smartzone.pocketclaude.service.VoiceChatTileService]).
 * - App-Verknuepfung beim langen Druecken des App-Symbols.
 */
object VoiceLaunch {
    const val ACTION_NEW_VOICE_CHAT = "de.smartzone.pocketclaude.action.NEW_VOICE_CHAT"
    private const val SHORTCUT_ID = "new_voice_chat"

    /** Startet MainActivity so, dass eine laufende Instanz das Intent per
     *  onNewIntent bekommt, statt nur nach vorn geholt zu werden (das waere
     *  bei FLAG_ACTIVITY_NEW_TASK allein der Fall, und der Wunsch ginge verloren). */
    fun mainIntent(context: Context): Intent =
        Intent(context, MainActivity::class.java)
            .setAction(ACTION_NEW_VOICE_CHAT)
            .addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or
                    Intent.FLAG_ACTIVITY_CLEAR_TOP or
                    Intent.FLAG_ACTIVITY_SINGLE_TOP
            )

    /** True, wenn MainActivity einen neuen Sprach-Chat oeffnen soll. Ein Start
     *  aus der Liste der letzten Apps wiederholt das alte Intent; das ist kein
     *  neuer Wunsch und oeffnet deshalb keinen weiteren Chat. */
    fun isRequest(intent: Intent?): Boolean =
        intent?.action == ACTION_NEW_VOICE_CHAT &&
            (intent.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) == 0

    /** Verknuepfung im Menue des App-Symbols. Dynamisch statt in shortcuts.xml,
     *  weil die XML die Paket-Kennung fest verlangt und es mit -PlegacyAppId
     *  zwei davon gibt. */
    fun publishShortcut(context: Context) {
        val shortcut = ShortcutInfoCompat.Builder(context, SHORTCUT_ID)
            .setShortLabel(context.getString(R.string.voice_chat_short))
            .setLongLabel(context.getString(R.string.voice_chat_long))
            .setIcon(IconCompat.createWithResource(context, R.drawable.ic_shortcut_voice_chat))
            .setIntent(
                Intent(context, VoiceChatActivity::class.java)
                    .setAction(ACTION_NEW_VOICE_CHAT)
            )
            .build()
        runCatching { ShortcutManagerCompat.setDynamicShortcuts(context, listOf(shortcut)) }
    }
}

/**
 * Unsichtbares Sprungbrett fuer Assistenten-Taste und App-Verknuepfung. Wer
 * hier startet, bestimmt die Intent-Flags selbst (System, Launcher, Hersteller);
 * MainActivity bekommt dagegen immer [VoiceLaunch.mainIntent].
 */
class VoiceChatActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        startActivity(VoiceLaunch.mainIntent(this))
        finish()
    }
}
