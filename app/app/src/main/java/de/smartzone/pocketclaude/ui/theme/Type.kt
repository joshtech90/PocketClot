package de.smartzone.pocketclaude.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Eine Schriftfamilie fuer alles. Frueher waren die grossen Stufen Serif
// ("Editorial"); die tauchten nur an zwei Stellen auf und wirkten dort wie ein
// Fremdkoerper. Zeilenhoehen liegen auf dem 4-dp-Raster.
private val Sans = FontFamily.SansSerif

val PocketTypography = Typography(
    displayLarge = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Bold, fontSize = 48.sp,
        lineHeight = 56.sp, letterSpacing = (-0.5).sp,
    ),
    displayMedium = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Bold, fontSize = 36.sp,
        lineHeight = 44.sp, letterSpacing = (-0.4).sp,
    ),
    displaySmall = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Bold, fontSize = 28.sp,
        lineHeight = 36.sp, letterSpacing = (-0.3).sp,
    ),
    headlineLarge = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Bold, fontSize = 28.sp,
        lineHeight = 36.sp, letterSpacing = (-0.3).sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Bold, fontSize = 24.sp,
        lineHeight = 32.sp, letterSpacing = (-0.2).sp,
    ),
    headlineSmall = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.SemiBold, fontSize = 22.sp,
        lineHeight = 28.sp, letterSpacing = (-0.1).sp,
    ),
    // Screen-Titel
    titleLarge = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Bold, fontSize = 20.sp,
        lineHeight = 28.sp, letterSpacing = (-0.1).sp,
    ),
    // Karten-, Abschnitts- und Dialogtitel
    titleMedium = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.SemiBold, fontSize = 16.sp,
        lineHeight = 24.sp, letterSpacing = 0.sp,
    ),
    // Unterabschnitt innerhalb einer Karte
    titleSmall = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
        lineHeight = 20.sp, letterSpacing = 0.sp,
    ),
    // Chattext
    bodyLarge = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Normal, fontSize = 16.sp,
        lineHeight = 24.sp, letterSpacing = 0.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Normal, fontSize = 14.sp,
        lineHeight = 20.sp, letterSpacing = 0.sp,
    ),
    // Hilfs- und Metatext
    bodySmall = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.Normal, fontSize = 12.sp,
        lineHeight = 16.sp, letterSpacing = 0.1.sp,
    ),
    // Buttons
    labelLarge = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.SemiBold, fontSize = 14.sp,
        lineHeight = 20.sp, letterSpacing = 0.1.sp,
    ),
    // Chips
    labelMedium = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.SemiBold, fontSize = 12.sp,
        lineHeight = 16.sp, letterSpacing = 0.2.sp,
    ),
    // Overline, Badges, Status
    labelSmall = TextStyle(
        fontFamily = Sans, fontWeight = FontWeight.SemiBold, fontSize = 11.sp,
        lineHeight = 16.sp, letterSpacing = 0.4.sp,
    ),
)
