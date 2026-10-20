package de.smartzone.pocketclaude.ui.components

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.provider.MediaStore
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil3.compose.AsyncImage
import de.smartzone.pocketclaude.R
import de.smartzone.pocketclaude.ui.theme.PocketIcons
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

/** Was die Vollbildansicht von einem Bild-Anhang braucht. */
data class ViewerImage(val id: String, val filename: String, val mimeType: String)

/**
 * Vollbild fuer ein Bild aus Chat oder Bilder-Screen: schwarzer Hintergrund,
 * Zoomen mit zwei Fingern oder Doppeltippen, oben Schliessen, Teilen und
 * Speichern. Ein Tipp ins Bild schliesst nicht, sonst geht die Ansicht beim
 * Verschieben eines gezoomten Bildes staendig zu.
 */
@Composable
fun ImageViewerDialog(
    image: ViewerImage,
    serverBaseUrl: String,
    serverToken: String,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val url = remember(serverBaseUrl, serverToken, image.id) {
        "$serverBaseUrl/attachments/${image.id}?token=${android.net.Uri.encode(serverToken)}"
    }
    var scale by remember { mutableFloatStateOf(1f) }
    var offset by remember { mutableStateOf(Offset.Zero) }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Box(modifier = Modifier.fillMaxSize().background(Color.Black)) {
            AsyncImage(
                model = url,
                contentDescription = image.filename,
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .fillMaxSize()
                    .pointerInput(Unit) {
                        detectTapGestures(onDoubleTap = { tap ->
                            if (scale > 1f) {
                                scale = 1f
                                offset = Offset.Zero
                            } else {
                                // Auf die angetippte Stelle hineinzoomen.
                                scale = 2.5f
                                val center = Offset(size.width / 2f, size.height / 2f)
                                offset = (center - tap) * (scale - 1f)
                            }
                        })
                    }
                    .pointerInput(Unit) {
                        detectTransformGestures { _, pan, zoom, _ ->
                            scale = (scale * zoom).coerceIn(1f, 6f)
                            offset = if (scale == 1f) Offset.Zero else offset + pan * scale
                        }
                    }
                    .graphicsLayer {
                        scaleX = scale
                        scaleY = scale
                        translationX = offset.x
                        translationY = offset.y
                    },
            )
            Row(
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .fillMaxWidth()
                    .background(Color.Black.copy(alpha = 0.35f))
                    .windowInsetsPadding(WindowInsets.safeDrawing)
                    .padding(horizontal = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onDismiss) {
                    Icon(PocketIcons.Close, stringResource(R.string.action_close), tint = Color.White)
                }
                Box(Modifier.weight(1f))
                IconButton(onClick = {
                    scope.launch { shareImage(context, serverBaseUrl, serverToken, image) }
                }) {
                    Icon(PocketIcons.Share, stringResource(R.string.image_share_btn), tint = Color.White)
                }
                IconButton(onClick = {
                    scope.launch { saveImageToGallery(context, serverBaseUrl, serverToken, image) }
                }) {
                    Icon(PocketIcons.Download, stringResource(R.string.image_save_btn), tint = Color.White)
                }
            }
        }
    }
}

/**
 * Laedt das Bild, legt es in den App-Cache und teilt es per ACTION_SEND.
 * Netz und Datei auf Dispatchers.IO, Chooser und Toast auf dem Main-Thread.
 */
suspend fun shareImage(context: Context, serverBaseUrl: String, serverToken: String, img: ViewerImage) {
    try {
        val intent = withContext(Dispatchers.IO) {
            val bytes = downloadImageBytes(serverBaseUrl, serverToken, img.id)
            val dir = java.io.File(context.cacheDir, "shared-images").apply { mkdirs() }
            val safeName = img.filename.replace(Regex("[^A-Za-z0-9._-]"), "_")
            val file = java.io.File(dir, safeName).also { it.writeBytes(bytes) }
            val uri = androidx.core.content.FileProvider.getUriForFile(
                context, "${context.packageName}.fileprovider", file,
            )
            Intent(Intent.ACTION_SEND).apply {
                type = img.mimeType
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        }
        withContext(Dispatchers.Main) {
            context.startActivity(Intent.createChooser(intent, context.getString(R.string.image_share_chooser_title)))
        }
    } catch (e: Exception) {
        withContext(Dispatchers.Main) {
            Toast.makeText(context, context.getString(R.string.image_share_failed, e.message ?: ""), Toast.LENGTH_LONG).show()
        }
    }
}

/**
 * Speichert das Bild per MediaStore in die Galerie (Pictures/PocketClot/),
 * ohne Speicher-Berechtigung, Scoped-Storage-konform.
 */
suspend fun saveImageToGallery(context: Context, serverBaseUrl: String, serverToken: String, img: ViewerImage) {
    try {
        withContext(Dispatchers.IO) {
            val bytes = downloadImageBytes(serverBaseUrl, serverToken, img.id)
            val ts = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(java.util.Date())
            val ext = when {
                img.mimeType.contains("png") -> "png"
                img.mimeType.contains("webp") -> "webp"
                else -> "jpg"
            }
            val values = ContentValues().apply {
                put(MediaStore.Images.Media.DISPLAY_NAME, "PocketClot-$ts.$ext")
                put(MediaStore.Images.Media.MIME_TYPE, img.mimeType)
                put(MediaStore.Images.Media.RELATIVE_PATH, "Pictures/PocketClot")
            }
            val resolver = context.contentResolver
            val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                ?: throw java.io.IOException("MediaStore insert failed")
            resolver.openOutputStream(uri)?.use { it.write(bytes) }
                ?: throw java.io.IOException("OutputStream null")
        }
        withContext(Dispatchers.Main) {
            Toast.makeText(context, context.getString(R.string.image_save_success), Toast.LENGTH_SHORT).show()
        }
    } catch (e: Exception) {
        withContext(Dispatchers.Main) {
            Toast.makeText(context, context.getString(R.string.image_save_failed, e.message ?: ""), Toast.LENGTH_LONG).show()
        }
    }
}

private fun downloadImageBytes(serverBaseUrl: String, serverToken: String, attId: String): ByteArray {
    val url = java.net.URL(
        "$serverBaseUrl/attachments/$attId?token=${java.net.URLEncoder.encode(serverToken, "UTF-8")}"
    )
    return url.openStream().use { it.readBytes() }
}
