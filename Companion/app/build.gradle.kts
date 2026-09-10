import java.io.File
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val releaseSigningProperties = Properties()
val releaseSigningPropertiesFile = listOf(
    rootProject.file("signing/keystore.properties"),
    rootProject.file("../Android-App/signing/keystore.properties"),
).firstOrNull(File::isFile)
releaseSigningPropertiesFile?.inputStream()?.use(releaseSigningProperties::load)

fun releaseSigningValue(propertyName: String, environmentName: String): String? =
    (System.getenv(environmentName) ?: releaseSigningProperties.getProperty(propertyName))
        ?.takeIf { it.isNotBlank() }

val releaseStoreFilePath = releaseSigningValue("storeFile", "PONYCHAT_RELEASE_STORE_FILE")
val releaseStorePassword = releaseSigningValue("storePassword", "PONYCHAT_RELEASE_STORE_PASSWORD")
val releaseKeyAlias = releaseSigningValue("keyAlias", "PONYCHAT_RELEASE_KEY_ALIAS")
val releaseKeyPassword = releaseSigningValue("keyPassword", "PONYCHAT_RELEASE_KEY_PASSWORD")
val releaseStoreFile = releaseStoreFilePath?.let { path ->
    val file = File(path)
    if (file.isAbsolute) {
        file
    } else {
        releaseSigningPropertiesFile?.parentFile?.parentFile?.resolve(path)
            ?: rootProject.file(path)
    }
}
val hasReleaseSigningConfig =
    releaseStoreFile?.isFile == true &&
        releaseStorePassword != null &&
        releaseKeyAlias != null &&
        releaseKeyPassword != null

android {
    namespace = "top.ponychat.companion"
    compileSdk = 34

    defaultConfig {
        applicationId = "top.ponychat.companion"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    signingConfigs {
        create("release") {
            if (hasReleaseSigningConfig) {
                storeFile = releaseStoreFile
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
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
        aidl = true
    }

    testOptions {
        unitTests.all {
            it.useJUnit()
        }
    }
}

tasks.matching {
    it.name in listOf("preReleaseBuild", "validateSigningRelease", "assembleRelease", "bundleRelease")
}.configureEach {
    doFirst {
        if (!hasReleaseSigningConfig) {
            throw GradleException(
                "Release signing is not configured. Keep the shared key in Android-App/signing, " +
                    "create Companion/signing/keystore.properties, or set PONYCHAT_RELEASE_* variables."
            )
        }
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
