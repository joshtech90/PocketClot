import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

// Signierschluessel fuer Release-Builds. Die Datei liegt bewusst AUSSERHALB
// des Repos, weil PocketClot oeffentlich auf GitHub steht. Fehlt sie, laeuft
// alles normal weiter und der Release-Build wird schlicht nicht signiert; nur
// fuer den Play Store braucht es sie.
val keystorePropsFile = file(System.getProperty("user.home") + "/.pocketclot-signing/keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) keystorePropsFile.inputStream().use { load(it) }
}

android {
    namespace = "de.smartzone.pocketclaude"
    compileSdk = 35

    defaultConfig {
        // Die Paket-Kennung ist die dauerhafte Identitaet der App gegenueber
    // Android und Google Play und laesst sich nach der ersten
    // Veroeffentlichung nie wieder aendern. Deshalb steht hier "pocketclot"
    // und nicht mehr der alte Name. Das Kotlin-Paket unten heisst bewusst
    // weiter "pocketclaude": das sieht niemand ausser dem Code selbst, und ein
    // Umbenennen wuerde jede Datei der App anfassen.
    applicationId = "de.smartzone.pocketclot"
    // Nur fuer Geraete, auf denen noch die alte App mit der Kennung
    // "de.smartzone.pocketclaude" liegt: `./gradlew assembleDebug -PlegacyAppId`
    // baut dieselbe App unter der alten Kennung, damit sie sich ohne
    // Neuinstallation darueber aktualisiert.
    if (project.hasProperty("legacyAppId")) applicationId = "de.smartzone.pocketclaude"
        minSdk = 31
        targetSdk = 35
        versionCode = 13
        versionName = "0.6.2"

        vectorDrawables { useSupportLibrary = true }
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.findByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    // Core
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.activity:activity-compose:1.9.3")

    // Compose
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    // Symbole kommen aus ui/theme/PocketIcons.kt (Material Symbols Rounded als
    // Pfade). Die riesige material-icons-extended-Bibliothek wird nicht mehr
    // gebraucht; Material 3 bringt fuer seine eigenen Pfeile material-icons-core mit.
    implementation("androidx.compose.animation:animation")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.8.5")

    // DataStore for settings
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    // Biometric (Fingerabdruck/Gesicht) zum Entsperren gesperrter Chats.
    // Zieht androidx.fragment mit — MainActivity ist deshalb eine FragmentActivity.
    implementation("androidx.biometric:biometric:1.1.0")

    // Networking
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:okhttp-sse:4.12.0")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // JSON
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    // Coil for image loading
    implementation("io.coil-kt.coil3:coil-compose:3.0.4")
    implementation("io.coil-kt.coil3:coil-network-okhttp:3.0.4")
    // EXIF-Rotation für Bildkompression (sonst landen Hochkant-Fotos seitlich).
    implementation("androidx.exifinterface:exifinterface:1.3.7")

    // media3 (ExoPlayer + MediaSession für Background-TTS und Lock-Screen-Controls)
    implementation("androidx.media3:media3-exoplayer:1.5.0")
    implementation("androidx.media3:media3-session:1.5.0")
    implementation("androidx.media3:media3-ui:1.5.0")
    // media3-datasource-cache: HTTP-Cache für TTS-Audio (Re-Listen ohne erneute
    // Server-Anfrage). Files liegen unter cacheDir/tts_cache, LRU-evicted.
    implementation("androidx.media3:media3-datasource:1.5.0")

    // Markdown (compose-richtext from CashApp's halilibo project)
    implementation("com.halilibo.compose-richtext:richtext-commonmark:1.0.0-alpha02")
    implementation("com.halilibo.compose-richtext:richtext-ui-material3:1.0.0-alpha02")

    debugImplementation("androidx.compose.ui:ui-tooling")
}
