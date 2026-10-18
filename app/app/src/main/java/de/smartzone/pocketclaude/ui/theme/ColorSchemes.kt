package de.smartzone.pocketclaude.ui.theme

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.ui.graphics.Color

/**
 * Verfuegbare Farbschemata fuer die Anwendung.
 */
enum class PocketPalette(val id: String, val displayName: String) {
    MIDNIGHT_ATELIER("midnight_atelier", "Midnight Atelier"),
    NORDIC_BLUE("nordic_blue", "Nordic Blue"),
    FOREST_SAGE("forest_sage", "Forest Sage"),
    PLUM_DUSK("plum_dusk", "Plum Dusk"),
    GRAPHITE_MONO("graphite_mono", "Graphite Mono");

    companion object {
        /** Unbekannte oder fehlende IDs fallen auf die Standardpalette zurueck.
         *  Der Rueckfall ist angebbar, weil hell und dunkel unterschiedliche
         *  Vorgaben haben: hell Nordic Blue, dunkel Midnight Atelier. */
        fun fromId(value: String?, fallback: PocketPalette = MIDNIGHT_ATELIER): PocketPalette =
            entries.firstOrNull { it.id == value } ?: fallback
    }
}

/**
 * Farbspezifikation fuer ein Schema mit Hell- und Dunkelvariante.
 */
data class PaletteSpec(
    val darkScheme: ColorScheme,
    val lightScheme: ColorScheme,
    val darkPocket: PocketColors,
    val lightPocket: PocketColors,
)

/**
 * Liefert die Farbspezifikation fuer die gewaehlte Palette.
 */
fun specFor(palette: PocketPalette): PaletteSpec = when (palette) {
    PocketPalette.MIDNIGHT_ATELIER -> MidnightAtelierSpec
    PocketPalette.NORDIC_BLUE -> NordicBlueSpec
    PocketPalette.FOREST_SAGE -> ForestSageSpec
    PocketPalette.PLUM_DUSK -> PlumDuskSpec
    PocketPalette.GRAPHITE_MONO -> GraphiteMonoSpec
}

// ---------------------------------------------------------------------------
// 1) Midnight Atelier (Standard-Schema, 1:1 aus Color.kt und Theme.kt)
// ---------------------------------------------------------------------------

private val MidnightAtelierDarkColors = darkColorScheme(
    primary = AtelierCoral,
    onPrimary = Color(0xFF29130D),
    primaryContainer = Color(0xFF633020),
    onPrimaryContainer = Color(0xFFFFDBCF),
    secondary = AtelierIce,
    onSecondary = Color(0xFF092A31),
    secondaryContainer = Color(0xFF214A54),
    onSecondaryContainer = Color(0xFFBDEAF3),
    tertiary = AtelierGold,
    onTertiary = Color(0xFF3C2A0E),
    tertiaryContainer = Color(0xFF564019),
    onTertiaryContainer = Color(0xFFFFDFA8),
    background = DarkBackground,
    onBackground = DarkOnBackground,
    surface = DarkSurface,
    onSurface = DarkOnSurface,
    surfaceVariant = DarkSurfaceVariant,
    onSurfaceVariant = DarkOnSurfaceVariant,
    surfaceContainerLowest = DarkSurfaceLow,
    surfaceContainerLow = DarkSurface,
    surfaceContainer = DarkSurfaceElevated,
    surfaceContainerHigh = Color(0xFF352F3B),
    surfaceContainerHighest = Color(0xFF3D3644),
    outline = DarkOutline,
    outlineVariant = DarkOutlineSoft,
    error = DarkError,
    onError = Color(0xFF690005),
)

private val MidnightAtelierLightColors = lightColorScheme(
    primary = AtelierCoralDeep,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFFFDBCF),
    onPrimaryContainer = Color(0xFF3B0B00),
    secondary = AtelierIceDeep,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFCFE7EC),
    onSecondaryContainer = Color(0xFF092A31),
    tertiary = Color(0xFF7A5730),
    onTertiary = Color.White,
    tertiaryContainer = Color(0xFFFFDDB0),
    onTertiaryContainer = Color(0xFF2A1700),
    background = LightBackground,
    onBackground = LightOnBackground,
    surface = LightSurface,
    onSurface = LightOnSurface,
    surfaceVariant = LightSurfaceVariant,
    onSurfaceVariant = LightOnSurfaceVariant,
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = LightSurface,
    surfaceContainer = LightSurfaceElevated,
    surfaceContainerHigh = Color(0xFFF0E8E1),
    surfaceContainerHighest = Color(0xFFE9DFD8),
    outline = LightOutline,
    outlineVariant = LightOutlineSoft,
    error = ErrorRed,
    onError = Color.White,
)

private val MidnightAtelierDarkPocket = PocketColors(
    bubbleUser = DarkBubbleUser,
    bubbleAssistant = DarkBubbleAssistant,
    onBubbleUser = Color(0xFF26130D),
    onBubbleAssistant = DarkOnSurface,
    accent = AtelierIce,
    success = SuccessGreen,
    ambientPrimary = AtelierCoral,
    ambientSecondary = AtelierIce,
    surfaceLow = DarkSurfaceLow,
    outlineSoft = DarkOutlineSoft,
)

private val MidnightAtelierLightPocket = PocketColors(
    bubbleUser = LightBubbleUser,
    bubbleAssistant = LightBubbleAssistant,
    onBubbleUser = Color.White,
    onBubbleAssistant = LightOnSurface,
    accent = AtelierIceDeep,
    success = LightSuccessGreen,
    ambientPrimary = AtelierCoral,
    ambientSecondary = AtelierIce,
    surfaceLow = LightSurfaceLow,
    outlineSoft = LightOutlineSoft,
)

private val MidnightAtelierSpec = PaletteSpec(
    darkScheme = MidnightAtelierDarkColors,
    lightScheme = MidnightAtelierLightColors,
    darkPocket = MidnightAtelierDarkPocket,
    lightPocket = MidnightAtelierLightPocket,
)

// ---------------------------------------------------------------------------
// 2) Nordic Blue (Klares, kuehles Nordmeer-Blau)
// ---------------------------------------------------------------------------

private val NordicDarkBg = Color(0xFF0E141B)
private val NordicDarkSurf = Color(0xFF151C24)
private val NordicDarkSurfVar = Color(0xFF212B36)
private val NordicDarkSurfElev = Color(0xFF1C242E)
private val NordicDarkSurfLow = Color(0xFF0A0F14)
private val NordicDarkSurfHigh = Color(0xFF242E3B)
private val NordicDarkSurfHighest = Color(0xFF2D3947)
private val NordicDarkOnBg = Color(0xFFE6EDF5)
private val NordicDarkOnSurf = Color(0xFFDEE6EF)
private val NordicDarkOnSurfVar = Color(0xFFA6B4C4)
private val NordicDarkOutline = Color(0xFF3F4E5F)
private val NordicDarkOutlineSoft = Color(0xFF2B3744)
private val NordicDarkPrimary = Color(0xFF7CB8EB)
private val NordicDarkOnPrimary = Color(0xFF003258)
private val NordicDarkPrimaryCont = Color(0xFF1E486D)
private val NordicDarkOnPrimaryCont = Color(0xFFCEE5FF)
private val NordicDarkSecondary = Color(0xFF86D2D9)
private val NordicDarkOnSecondary = Color(0xFF00363C)
private val NordicDarkSecondaryCont = Color(0xFF1F4E54)
private val NordicDarkOnSecondaryCont = Color(0xFFA6EEF6)
private val NordicDarkTertiary = Color(0xFF98CAD6)
private val NordicDarkOnTertiary = Color(0xFF00353F)
private val NordicDarkTertiaryCont = Color(0xFF254B54)
private val NordicDarkOnTertiaryCont = Color(0xFFB4E7F3)
private val NordicDarkBubbleUser = Color(0xFF4C93D6)
private val NordicDarkBubbleAsst = Color(0xFF17202B)
private val NordicDarkOnBubbleUser = Color(0xFF002240)
private val NordicDarkAccent = Color(0xFF86D2D9)
private val NordicDarkSuccess = Color(0xFF53D4A4)
private val NordicDarkError = Color(0xFFFFB4AB)
private val NordicDarkOnError = Color(0xFF690005)

private val NordicLightBg = Color(0xFFF3F7FB)
private val NordicLightSurf = Color(0xFFF9FBFE)
private val NordicLightSurfVar = Color(0xFFE2EAF2)
private val NordicLightSurfElev = Color(0xFFFFFFFF)
private val NordicLightSurfLow = Color(0xFFEDF3FA)
private val NordicLightSurfHigh = Color(0xFFDEE6EE)
private val NordicLightSurfHighest = Color(0xFFD4DEE7)
private val NordicLightOnBg = Color(0xFF121B24)
private val NordicLightOnSurf = Color(0xFF16202B)
private val NordicLightOnSurfVar = Color(0xFF4B5A6A)
private val NordicLightOutline = Color(0xFFB5C3D2)
private val NordicLightOutlineSoft = Color(0xFFD2DEEA)
private val NordicLightPrimary = Color(0xFF1B649E)
private val NordicLightOnPrimary = Color.White
private val NordicLightPrimaryCont = Color(0xFFCEE5FF)
private val NordicLightOnPrimaryCont = Color(0xFF001D36)
private val NordicLightSecondary = Color(0xFF1B6870)
private val NordicLightOnSecondary = Color.White
// Gedaempft: das fruehere 0xFFA6EEF6 war als Auswahlflaeche (Drawer, Chips)
// ein greller Tuerkis-Block neben dem ruhigen Blau.
private val NordicLightSecondaryCont = Color(0xFFCBE6EC)
private val NordicLightOnSecondaryCont = Color(0xFF002024)
private val NordicLightTertiary = Color(0xFF2F636E)
private val NordicLightOnTertiary = Color.White
private val NordicLightTertiaryCont = Color(0xFFB4E7F3)
private val NordicLightOnTertiaryCont = Color(0xFF001F25)
private val NordicLightBubbleUser = Color(0xFF1B649E)
private val NordicLightBubbleAsst = Color(0xFFF9FBFE)
private val NordicLightOnBubbleUser = Color.White
private val NordicLightAccent = Color(0xFF1B6870)
private val NordicLightSuccess = Color(0xFF187A54)
private val NordicLightError = Color(0xFFBA1A1A)
private val NordicLightOnError = Color.White

private val NordicBlueDarkColors = darkColorScheme(
    primary = NordicDarkPrimary,
    onPrimary = NordicDarkOnPrimary,
    primaryContainer = NordicDarkPrimaryCont,
    onPrimaryContainer = NordicDarkOnPrimaryCont,
    secondary = NordicDarkSecondary,
    onSecondary = NordicDarkOnSecondary,
    secondaryContainer = NordicDarkSecondaryCont,
    onSecondaryContainer = NordicDarkOnSecondaryCont,
    tertiary = NordicDarkTertiary,
    onTertiary = NordicDarkOnTertiary,
    tertiaryContainer = NordicDarkTertiaryCont,
    onTertiaryContainer = NordicDarkOnTertiaryCont,
    background = NordicDarkBg,
    onBackground = NordicDarkOnBg,
    surface = NordicDarkSurf,
    onSurface = NordicDarkOnSurf,
    surfaceVariant = NordicDarkSurfVar,
    onSurfaceVariant = NordicDarkOnSurfVar,
    surfaceContainerLowest = NordicDarkSurfLow,
    surfaceContainerLow = NordicDarkSurf,
    surfaceContainer = NordicDarkSurfElev,
    surfaceContainerHigh = NordicDarkSurfHigh,
    surfaceContainerHighest = NordicDarkSurfHighest,
    outline = NordicDarkOutline,
    outlineVariant = NordicDarkOutlineSoft,
    error = NordicDarkError,
    onError = NordicDarkOnError,
)

private val NordicBlueLightColors = lightColorScheme(
    primary = NordicLightPrimary,
    onPrimary = NordicLightOnPrimary,
    primaryContainer = NordicLightPrimaryCont,
    onPrimaryContainer = NordicLightOnPrimaryCont,
    secondary = NordicLightSecondary,
    onSecondary = NordicLightOnSecondary,
    secondaryContainer = NordicLightSecondaryCont,
    onSecondaryContainer = NordicLightOnSecondaryCont,
    tertiary = NordicLightTertiary,
    onTertiary = NordicLightOnTertiary,
    tertiaryContainer = NordicLightTertiaryCont,
    onTertiaryContainer = NordicLightOnTertiaryCont,
    background = NordicLightBg,
    onBackground = NordicLightOnBg,
    surface = NordicLightSurf,
    onSurface = NordicLightOnSurf,
    surfaceVariant = NordicLightSurfVar,
    onSurfaceVariant = NordicLightOnSurfVar,
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = NordicLightSurf,
    surfaceContainer = NordicLightSurfElev,
    surfaceContainerHigh = NordicLightSurfHigh,
    surfaceContainerHighest = NordicLightSurfHighest,
    outline = NordicLightOutline,
    outlineVariant = NordicLightOutlineSoft,
    error = NordicLightError,
    onError = NordicLightOnError,
)

private val NordicBlueDarkPocket = PocketColors(
    bubbleUser = NordicDarkBubbleUser,
    bubbleAssistant = NordicDarkBubbleAsst,
    onBubbleUser = NordicDarkOnBubbleUser,
    onBubbleAssistant = NordicDarkOnSurf,
    accent = NordicDarkAccent,
    success = NordicDarkSuccess,
    ambientPrimary = NordicDarkPrimary,
    ambientSecondary = NordicDarkSecondary,
    surfaceLow = NordicDarkSurfLow,
    outlineSoft = NordicDarkOutlineSoft,
)

private val NordicBlueLightPocket = PocketColors(
    bubbleUser = NordicLightBubbleUser,
    bubbleAssistant = NordicLightBubbleAsst,
    onBubbleUser = NordicLightOnBubbleUser,
    onBubbleAssistant = NordicLightOnSurf,
    accent = NordicLightAccent,
    success = NordicLightSuccess,
    ambientPrimary = NordicLightPrimary,
    ambientSecondary = NordicDarkSecondary,
    surfaceLow = NordicLightSurfLow,
    outlineSoft = NordicLightOutlineSoft,
)

private val NordicBlueSpec = PaletteSpec(
    darkScheme = NordicBlueDarkColors,
    lightScheme = NordicBlueLightColors,
    darkPocket = NordicBlueDarkPocket,
    lightPocket = NordicBlueLightPocket,
)

// ---------------------------------------------------------------------------
// 3) Forest Sage (Beruhigendes Waldgruen und Salbeiton)
// ---------------------------------------------------------------------------

private val SageDarkBg = Color(0xFF0F1511)
private val SageDarkSurf = Color(0xFF161E18)
private val SageDarkSurfVar = Color(0xFF222C24)
private val SageDarkSurfElev = Color(0xFF1D261F)
private val SageDarkSurfLow = Color(0xFF0B100C)
private val SageDarkSurfHigh = Color(0xFF253027)
private val SageDarkSurfHighest = Color(0xFF2D3A30)
private val SageDarkOnBg = Color(0xFFE8EFE9)
private val SageDarkOnSurf = Color(0xFFE1EAE2)
private val SageDarkOnSurfVar = Color(0xFFA8B6AA)
private val SageDarkOutline = Color(0xFF414E43)
private val SageDarkOutlineSoft = Color(0xFF2C372E)
private val SageDarkPrimary = Color(0xFF8CD8A4)
private val SageDarkOnPrimary = Color(0xFF00391A)
private val SageDarkPrimaryCont = Color(0xFF1F5131)
private val SageDarkOnPrimaryCont = Color(0xFFA7F5BF)
private val SageDarkSecondary = Color(0xFFA6D0B4)
private val SageDarkOnSecondary = Color(0xFF113723)
private val SageDarkSecondaryCont = Color(0xFF2B4D38)
private val SageDarkOnSecondaryCont = Color(0xFFC1ECD0)
private val SageDarkTertiary = Color(0xFFC5CB86)
private val SageDarkOnTertiary = Color(0xFF2E3300)
private val SageDarkTertiaryCont = Color(0xFF454B12)
private val SageDarkOnTertiaryCont = Color(0xFFE1E79F)
private val SageDarkBubbleUser = Color(0xFF2E7D4E)
private val SageDarkBubbleAsst = Color(0xFF18221B)
private val SageDarkOnBubbleUser = Color.White
private val SageDarkAccent = Color(0xFF8CD8A4)
private val SageDarkSuccess = Color(0xFF56DCA0)
private val SageDarkError = Color(0xFFFFB4AB)
private val SageDarkOnError = Color(0xFF690005)

private val SageLightBg = Color(0xFFF3F7F3)
private val SageLightSurf = Color(0xFFFAFDF9)
private val SageLightSurfVar = Color(0xFFDEE7DF)
private val SageLightSurfElev = Color(0xFFFFFFFF)
private val SageLightSurfLow = Color(0xFFEDF3EE)
private val SageLightSurfHigh = Color(0xFFDFE7E0)
private val SageLightSurfHighest = Color(0xFFD6DFD7)
private val SageLightOnBg = Color(0xFF131B15)
private val SageLightOnSurf = Color(0xFF172019)
private val SageLightOnSurfVar = Color(0xFF4B5A4E)
private val SageLightOutline = Color(0xFFB4C3B6)
private val SageLightOutlineSoft = Color(0xFFD0DED2)
private val SageLightPrimary = Color(0xFF236A3E)
private val SageLightOnPrimary = Color.White
private val SageLightPrimaryCont = Color(0xFFA7F5BF)
private val SageLightOnPrimaryCont = Color(0xFF00210D)
private val SageLightSecondary = Color(0xFF38664C)
private val SageLightOnSecondary = Color.White
private val SageLightSecondaryCont = Color(0xFFBAE8C8)
private val SageLightOnSecondaryCont = Color(0xFF002110)
private val SageLightTertiary = Color(0xFF59631E)
private val SageLightOnTertiary = Color.White
private val SageLightTertiaryCont = Color(0xFFDEE898)
private val SageLightOnTertiaryCont = Color(0xFF191E00)
private val SageLightBubbleUser = Color(0xFF236A3E)
private val SageLightBubbleAsst = Color(0xFFFAFDF9)
private val SageLightOnBubbleUser = Color.White
private val SageLightAccent = Color(0xFF38664C)
private val SageLightSuccess = Color(0xFF1B7B4F)
private val SageLightError = Color(0xFFBA1A1A)
private val SageLightOnError = Color.White

private val ForestSageDarkColors = darkColorScheme(
    primary = SageDarkPrimary,
    onPrimary = SageDarkOnPrimary,
    primaryContainer = SageDarkPrimaryCont,
    onPrimaryContainer = SageDarkOnPrimaryCont,
    secondary = SageDarkSecondary,
    onSecondary = SageDarkOnSecondary,
    secondaryContainer = SageDarkSecondaryCont,
    onSecondaryContainer = SageDarkOnSecondaryCont,
    tertiary = SageDarkTertiary,
    onTertiary = SageDarkOnTertiary,
    tertiaryContainer = SageDarkTertiaryCont,
    onTertiaryContainer = SageDarkOnTertiaryCont,
    background = SageDarkBg,
    onBackground = SageDarkOnBg,
    surface = SageDarkSurf,
    onSurface = SageDarkOnSurf,
    surfaceVariant = SageDarkSurfVar,
    onSurfaceVariant = SageDarkOnSurfVar,
    surfaceContainerLowest = SageDarkSurfLow,
    surfaceContainerLow = SageDarkSurf,
    surfaceContainer = SageDarkSurfElev,
    surfaceContainerHigh = SageDarkSurfHigh,
    surfaceContainerHighest = SageDarkSurfHighest,
    outline = SageDarkOutline,
    outlineVariant = SageDarkOutlineSoft,
    error = SageDarkError,
    onError = SageDarkOnError,
)

private val ForestSageLightColors = lightColorScheme(
    primary = SageLightPrimary,
    onPrimary = SageLightOnPrimary,
    primaryContainer = SageLightPrimaryCont,
    onPrimaryContainer = SageLightOnPrimaryCont,
    secondary = SageLightSecondary,
    onSecondary = SageLightOnSecondary,
    secondaryContainer = SageLightSecondaryCont,
    onSecondaryContainer = SageLightOnSecondaryCont,
    tertiary = SageLightTertiary,
    onTertiary = SageLightOnTertiary,
    tertiaryContainer = SageLightTertiaryCont,
    onTertiaryContainer = SageLightOnTertiaryCont,
    background = SageLightBg,
    onBackground = SageLightOnBg,
    surface = SageLightSurf,
    onSurface = SageLightOnSurf,
    surfaceVariant = SageLightSurfVar,
    onSurfaceVariant = SageLightOnSurfVar,
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = SageLightSurf,
    surfaceContainer = SageLightSurfElev,
    surfaceContainerHigh = SageLightSurfHigh,
    surfaceContainerHighest = SageLightSurfHighest,
    outline = SageLightOutline,
    outlineVariant = SageLightOutlineSoft,
    error = SageLightError,
    onError = SageLightOnError,
)

private val ForestSageDarkPocket = PocketColors(
    bubbleUser = SageDarkBubbleUser,
    bubbleAssistant = SageDarkBubbleAsst,
    onBubbleUser = SageDarkOnBubbleUser,
    onBubbleAssistant = SageDarkOnSurf,
    accent = SageDarkAccent,
    success = SageDarkSuccess,
    ambientPrimary = SageDarkPrimary,
    ambientSecondary = SageDarkSecondary,
    surfaceLow = SageDarkSurfLow,
    outlineSoft = SageDarkOutlineSoft,
)

private val ForestSageLightPocket = PocketColors(
    bubbleUser = SageLightBubbleUser,
    bubbleAssistant = SageLightBubbleAsst,
    onBubbleUser = SageLightOnBubbleUser,
    onBubbleAssistant = SageLightOnSurf,
    accent = SageLightAccent,
    success = SageLightSuccess,
    ambientPrimary = SageLightPrimary,
    ambientSecondary = SageDarkPrimary,
    surfaceLow = SageLightSurfLow,
    outlineSoft = SageLightOutlineSoft,
)

private val ForestSageSpec = PaletteSpec(
    darkScheme = ForestSageDarkColors,
    lightScheme = ForestSageLightColors,
    darkPocket = ForestSageDarkPocket,
    lightPocket = ForestSageLightPocket,
)

// ---------------------------------------------------------------------------
// 4) Plum Dusk (Elegantes Daemmerungs-Pflaume und sanftes Mauve)
// ---------------------------------------------------------------------------

private val PlumDarkBg = Color(0xFF140E16)
private val PlumDarkSurf = Color(0xFF1C151F)
private val PlumDarkSurfVar = Color(0xFF2A202E)
private val PlumDarkSurfElev = Color(0xFF241C28)
private val PlumDarkSurfLow = Color(0xFF0E0910)
private val PlumDarkSurfHigh = Color(0xFF2D2332)
private val PlumDarkSurfHighest = Color(0xFF372C3D)
private val PlumDarkOnBg = Color(0xFFF3EDF5)
private val PlumDarkOnSurf = Color(0xFFEBE3ED)
private val PlumDarkOnSurfVar = Color(0xFFC0B3C4)
private val PlumDarkOutline = Color(0xFF504054)
private val PlumDarkOutlineSoft = Color(0xFF372B3B)
private val PlumDarkPrimary = Color(0xFFDFB6E8)
private val PlumDarkOnPrimary = Color(0xFF40214B)
private val PlumDarkPrimaryCont = Color(0xFF583763)
private val PlumDarkOnPrimaryCont = Color(0xFFF8D8FF)
private val PlumDarkSecondary = Color(0xFFE1B8CA)
private val PlumDarkOnSecondary = Color(0xFF412333)
private val PlumDarkSecondaryCont = Color(0xFF5A394A)
private val PlumDarkOnSecondaryCont = Color(0xFFFFD8EA)
private val PlumDarkTertiary = Color(0xFFF0BD9E)
private val PlumDarkOnTertiary = Color(0xFF472714)
private val PlumDarkTertiaryCont = Color(0xFF623D27)
private val PlumDarkOnTertiaryCont = Color(0xFFFFDCC7)
private val PlumDarkBubbleUser = Color(0xFF834E96)
private val PlumDarkBubbleAsst = Color(0xFF1F1722)
private val PlumDarkOnBubbleUser = Color.White
private val PlumDarkAccent = Color(0xFFDFB6E8)
private val PlumDarkSuccess = Color(0xFF63D6A2)
private val PlumDarkError = Color(0xFFFFB4AB)
private val PlumDarkOnError = Color(0xFF690005)

private val PlumLightBg = Color(0xFFF8F2F7)
private val PlumLightSurf = Color(0xFFFEFAFD)
private val PlumLightSurfVar = Color(0xFFECE0EB)
private val PlumLightSurfElev = Color(0xFFFFFFFF)
private val PlumLightSurfLow = Color(0xFFF3EAF2)
private val PlumLightSurfHigh = Color(0xFFE5DCE4)
private val PlumLightSurfHighest = Color(0xFFDDD3DC)
private val PlumLightOnBg = Color(0xFF1E1420)
private val PlumLightOnSurf = Color(0xFF221825)
private val PlumLightOnSurfVar = Color(0xFF5D4F60)
private val PlumLightOutline = Color(0xFFC7B7C8)
private val PlumLightOutlineSoft = Color(0xFFE2D4E3)
private val PlumLightPrimary = Color(0xFF743F84)
private val PlumLightOnPrimary = Color.White
private val PlumLightPrimaryCont = Color(0xFFF8D8FF)
private val PlumLightOnPrimaryCont = Color(0xFF2D003C)
private val PlumLightSecondary = Color(0xFF75455E)
private val PlumLightOnSecondary = Color.White
private val PlumLightSecondaryCont = Color(0xFFFFD8EA)
private val PlumLightOnSecondaryCont = Color(0xFF2E051C)
private val PlumLightTertiary = Color(0xFF7D4E32)
private val PlumLightOnTertiary = Color.White
private val PlumLightTertiaryCont = Color(0xFFFFDCC7)
private val PlumLightOnTertiaryCont = Color(0xFF311300)
private val PlumLightBubbleUser = Color(0xFF743F84)
private val PlumLightBubbleAsst = Color(0xFFFEFAFD)
private val PlumLightOnBubbleUser = Color.White
private val PlumLightAccent = Color(0xFF75455E)
private val PlumLightSuccess = Color(0xFF1C7A54)
private val PlumLightError = Color(0xFFBA1A1A)
private val PlumLightOnError = Color.White

private val PlumDuskDarkColors = darkColorScheme(
    primary = PlumDarkPrimary,
    onPrimary = PlumDarkOnPrimary,
    primaryContainer = PlumDarkPrimaryCont,
    onPrimaryContainer = PlumDarkOnPrimaryCont,
    secondary = PlumDarkSecondary,
    onSecondary = PlumDarkOnSecondary,
    secondaryContainer = PlumDarkSecondaryCont,
    onSecondaryContainer = PlumDarkOnSecondaryCont,
    tertiary = PlumDarkTertiary,
    onTertiary = PlumDarkOnTertiary,
    tertiaryContainer = PlumDarkTertiaryCont,
    onTertiaryContainer = PlumDarkOnTertiaryCont,
    background = PlumDarkBg,
    onBackground = PlumDarkOnBg,
    surface = PlumDarkSurf,
    onSurface = PlumDarkOnSurf,
    surfaceVariant = PlumDarkSurfVar,
    onSurfaceVariant = PlumDarkOnSurfVar,
    surfaceContainerLowest = PlumDarkSurfLow,
    surfaceContainerLow = PlumDarkSurf,
    surfaceContainer = PlumDarkSurfElev,
    surfaceContainerHigh = PlumDarkSurfHigh,
    surfaceContainerHighest = PlumDarkSurfHighest,
    outline = PlumDarkOutline,
    outlineVariant = PlumDarkOutlineSoft,
    error = PlumDarkError,
    onError = PlumDarkOnError,
)

private val PlumDuskLightColors = lightColorScheme(
    primary = PlumLightPrimary,
    onPrimary = PlumLightOnPrimary,
    primaryContainer = PlumLightPrimaryCont,
    onPrimaryContainer = PlumLightOnPrimaryCont,
    secondary = PlumLightSecondary,
    onSecondary = PlumLightOnSecondary,
    secondaryContainer = PlumLightSecondaryCont,
    onSecondaryContainer = PlumLightOnSecondaryCont,
    tertiary = PlumLightTertiary,
    onTertiary = PlumLightOnTertiary,
    tertiaryContainer = PlumLightTertiaryCont,
    onTertiaryContainer = PlumLightOnTertiaryCont,
    background = PlumLightBg,
    onBackground = PlumLightOnBg,
    surface = PlumLightSurf,
    onSurface = PlumLightOnSurf,
    surfaceVariant = PlumLightSurfVar,
    onSurfaceVariant = PlumLightOnSurfVar,
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = PlumLightSurf,
    surfaceContainer = PlumLightSurfElev,
    surfaceContainerHigh = PlumLightSurfHigh,
    surfaceContainerHighest = PlumLightSurfHighest,
    outline = PlumLightOutline,
    outlineVariant = PlumLightOutlineSoft,
    error = PlumLightError,
    onError = PlumLightOnError,
)

private val PlumDuskDarkPocket = PocketColors(
    bubbleUser = PlumDarkBubbleUser,
    bubbleAssistant = PlumDarkBubbleAsst,
    onBubbleUser = PlumDarkOnBubbleUser,
    onBubbleAssistant = PlumDarkOnSurf,
    accent = PlumDarkAccent,
    success = PlumDarkSuccess,
    ambientPrimary = PlumDarkPrimary,
    ambientSecondary = PlumDarkSecondary,
    surfaceLow = PlumDarkSurfLow,
    outlineSoft = PlumDarkOutlineSoft,
)

private val PlumDuskLightPocket = PocketColors(
    bubbleUser = PlumLightBubbleUser,
    bubbleAssistant = PlumLightBubbleAsst,
    onBubbleUser = PlumLightOnBubbleUser,
    onBubbleAssistant = PlumLightOnSurf,
    accent = PlumLightAccent,
    success = PlumLightSuccess,
    ambientPrimary = PlumLightPrimary,
    ambientSecondary = PlumDarkPrimary,
    surfaceLow = PlumLightSurfLow,
    outlineSoft = PlumLightOutlineSoft,
)

private val PlumDuskSpec = PaletteSpec(
    darkScheme = PlumDuskDarkColors,
    lightScheme = PlumDuskLightColors,
    darkPocket = PlumDuskDarkPocket,
    lightPocket = PlumDuskLightPocket,
)

// ---------------------------------------------------------------------------
// 5) Graphite Mono (Entsaettigtes, klares Graphit-Monochrom)
// ---------------------------------------------------------------------------

private val MonoDarkBg = Color(0xFF121214)
private val MonoDarkSurf = Color(0xFF1A1A1D)
private val MonoDarkSurfVar = Color(0xFF27272C)
private val MonoDarkSurfElev = Color(0xFF222227)
private val MonoDarkSurfLow = Color(0xFF0C0C0E)
private val MonoDarkSurfHigh = Color(0xFF2B2B31)
private val MonoDarkSurfHighest = Color(0xFF35353C)
private val MonoDarkOnBg = Color(0xFFECECEF)
private val MonoDarkOnSurf = Color(0xFFE4E4E7)
private val MonoDarkOnSurfVar = Color(0xFFB5B5BE)
private val MonoDarkOutline = Color(0xFF484852)
private val MonoDarkOutlineSoft = Color(0xFF303038)
private val MonoDarkPrimary = Color(0xFFC8C8D2)
private val MonoDarkOnPrimary = Color(0xFF18181E)
private val MonoDarkPrimaryCont = Color(0xFF3E3E48)
private val MonoDarkOnPrimaryCont = Color(0xFFE6E6EE)
private val MonoDarkSecondary = Color(0xFF9EABB8)
private val MonoDarkOnSecondary = Color(0xFF14202A)
private val MonoDarkSecondaryCont = Color(0xFF323E4B)
private val MonoDarkOnSecondaryCont = Color(0xFFD2DFEC)
private val MonoDarkTertiary = Color(0xFFB4B9C2)
private val MonoDarkOnTertiary = Color(0xFF1F242C)
private val MonoDarkTertiaryCont = Color(0xFF3A404A)
private val MonoDarkOnTertiaryCont = Color(0xFFD7DCE5)
private val MonoDarkBubbleUser = Color(0xFF484852)
private val MonoDarkBubbleAsst = Color(0xFF1D1D20)
private val MonoDarkOnBubbleUser = Color(0xFFF5F5F7)
private val MonoDarkAccent = Color(0xFF9EABB8)
private val MonoDarkSuccess = Color(0xFF58D2A0)
private val MonoDarkError = Color(0xFFFFB4AB)
private val MonoDarkOnError = Color(0xFF690005)

private val MonoLightBg = Color(0xFFF5F5F7)
private val MonoLightSurf = Color(0xFFFCFCFD)
private val MonoLightSurfVar = Color(0xFFE5E5EA)
private val MonoLightSurfElev = Color(0xFFFFFFFF)
private val MonoLightSurfLow = Color(0xFFEDEDF0)
private val MonoLightSurfHigh = Color(0xFFDFDFE4)
private val MonoLightSurfHighest = Color(0xFFD7D7DC)
private val MonoLightOnBg = Color(0xFF18181B)
private val MonoLightOnSurf = Color(0xFF1C1C20)
private val MonoLightOnSurfVar = Color(0xFF565660)
private val MonoLightOutline = Color(0xFFBEBECD)
private val MonoLightOutlineSoft = Color(0xFFDCDCE5)
private val MonoLightPrimary = Color(0xFF2C2C34)
private val MonoLightOnPrimary = Color.White
private val MonoLightPrimaryCont = Color(0xFFE2E2EC)
private val MonoLightOnPrimaryCont = Color(0xFF16161C)
private val MonoLightSecondary = Color(0xFF4A5664)
private val MonoLightOnSecondary = Color.White
private val MonoLightSecondaryCont = Color(0xFFD6E2F0)
private val MonoLightOnSecondaryCont = Color(0xFF0E1924)
private val MonoLightTertiary = Color(0xFF50555E)
private val MonoLightOnTertiary = Color.White
private val MonoLightTertiaryCont = Color(0xFFDBE0EA)
private val MonoLightOnTertiaryCont = Color(0xFF10141B)
private val MonoLightBubbleUser = Color(0xFF2C2C34)
private val MonoLightBubbleAsst = Color(0xFFFCFCFD)
private val MonoLightOnBubbleUser = Color.White
private val MonoLightAccent = Color(0xFF4A5664)
private val MonoLightSuccess = Color(0xFF1E7E55)
private val MonoLightError = Color(0xFFBA1A1A)
private val MonoLightOnError = Color.White

private val GraphiteMonoDarkColors = darkColorScheme(
    primary = MonoDarkPrimary,
    onPrimary = MonoDarkOnPrimary,
    primaryContainer = MonoDarkPrimaryCont,
    onPrimaryContainer = MonoDarkOnPrimaryCont,
    secondary = MonoDarkSecondary,
    onSecondary = MonoDarkOnSecondary,
    secondaryContainer = MonoDarkSecondaryCont,
    onSecondaryContainer = MonoDarkOnSecondaryCont,
    tertiary = MonoDarkTertiary,
    onTertiary = MonoDarkOnTertiary,
    tertiaryContainer = MonoDarkTertiaryCont,
    onTertiaryContainer = MonoDarkOnTertiaryCont,
    background = MonoDarkBg,
    onBackground = MonoDarkOnBg,
    surface = MonoDarkSurf,
    onSurface = MonoDarkOnSurf,
    surfaceVariant = MonoDarkSurfVar,
    onSurfaceVariant = MonoDarkOnSurfVar,
    surfaceContainerLowest = MonoDarkSurfLow,
    surfaceContainerLow = MonoDarkSurf,
    surfaceContainer = MonoDarkSurfElev,
    surfaceContainerHigh = MonoDarkSurfHigh,
    surfaceContainerHighest = MonoDarkSurfHighest,
    outline = MonoDarkOutline,
    outlineVariant = MonoDarkOutlineSoft,
    error = MonoDarkError,
    onError = MonoDarkOnError,
)

private val GraphiteMonoLightColors = lightColorScheme(
    primary = MonoLightPrimary,
    onPrimary = MonoLightOnPrimary,
    primaryContainer = MonoLightPrimaryCont,
    onPrimaryContainer = MonoLightOnPrimaryCont,
    secondary = MonoLightSecondary,
    onSecondary = MonoLightOnSecondary,
    secondaryContainer = MonoLightSecondaryCont,
    onSecondaryContainer = MonoLightOnSecondaryCont,
    tertiary = MonoLightTertiary,
    onTertiary = MonoLightOnTertiary,
    tertiaryContainer = MonoLightTertiaryCont,
    onTertiaryContainer = MonoLightOnTertiaryCont,
    background = MonoLightBg,
    onBackground = MonoLightOnBg,
    surface = MonoLightSurf,
    onSurface = MonoLightOnSurf,
    surfaceVariant = MonoLightSurfVar,
    onSurfaceVariant = MonoLightOnSurfVar,
    surfaceContainerLowest = Color.White,
    surfaceContainerLow = MonoLightSurf,
    surfaceContainer = MonoLightSurfElev,
    surfaceContainerHigh = MonoLightSurfHigh,
    surfaceContainerHighest = MonoLightSurfHighest,
    outline = MonoLightOutline,
    outlineVariant = MonoLightOutlineSoft,
    error = MonoLightError,
    onError = MonoLightOnError,
)

private val GraphiteMonoDarkPocket = PocketColors(
    bubbleUser = MonoDarkBubbleUser,
    bubbleAssistant = MonoDarkBubbleAsst,
    onBubbleUser = MonoDarkOnBubbleUser,
    onBubbleAssistant = MonoDarkOnSurf,
    accent = MonoDarkAccent,
    success = MonoDarkSuccess,
    ambientPrimary = MonoDarkPrimary,
    ambientSecondary = MonoDarkSecondary,
    surfaceLow = MonoDarkSurfLow,
    outlineSoft = MonoDarkOutlineSoft,
)

private val GraphiteMonoLightPocket = PocketColors(
    bubbleUser = MonoLightBubbleUser,
    bubbleAssistant = MonoLightBubbleAsst,
    onBubbleUser = MonoLightOnBubbleUser,
    onBubbleAssistant = MonoLightOnSurf,
    accent = MonoLightAccent,
    success = MonoLightSuccess,
    ambientPrimary = MonoLightPrimary,
    ambientSecondary = MonoDarkSecondary,
    surfaceLow = MonoLightSurfLow,
    outlineSoft = MonoLightOutlineSoft,
)

private val GraphiteMonoSpec = PaletteSpec(
    darkScheme = GraphiteMonoDarkColors,
    lightScheme = GraphiteMonoLightColors,
    darkPocket = GraphiteMonoDarkPocket,
    lightPocket = GraphiteMonoLightPocket,
)
