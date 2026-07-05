import java.util.Properties
import java.io.File

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val releaseSigningProperties = Properties()
val releaseSigningPropertiesFile = rootProject.file("signing/keystore.properties")
if (releaseSigningPropertiesFile.isFile) {
    releaseSigningPropertiesFile.inputStream().use(releaseSigningProperties::load)
}

fun releaseSigningValue(propertyName: String, environmentName: String): String? =
    (System.getenv(environmentName) ?: releaseSigningProperties.getProperty(propertyName))
        ?.takeIf { it.isNotBlank() }

val releaseStoreFilePath = releaseSigningValue("storeFile", "PONYCHAT_RELEASE_STORE_FILE")
val releaseStorePassword = releaseSigningValue("storePassword", "PONYCHAT_RELEASE_STORE_PASSWORD")
val releaseKeyAlias = releaseSigningValue("keyAlias", "PONYCHAT_RELEASE_KEY_ALIAS")
val releaseKeyPassword = releaseSigningValue("keyPassword", "PONYCHAT_RELEASE_KEY_PASSWORD")
val releaseStoreFile = releaseStoreFilePath?.let {
    val file = File(it)
    if (file.isAbsolute) file else rootProject.file(it)
}
val hasReleaseSigningConfig =
    releaseStoreFile?.isFile == true &&
        releaseStorePassword != null &&
        releaseKeyAlias != null &&
        releaseKeyPassword != null

android {
    namespace = "top.ponychat.webview"
    compileSdk = 34

    defaultConfig {
        applicationId = "top.ponychat.webview"
        minSdk = 24
        targetSdk = 34
        versionCode = 353
        versionName = "5.6.13"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        ndk {
            abiFilters += listOf("armeabi-v7a", "arm64-v8a", "x86_64")
        }
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
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        jniLibs {
            useLegacyPackaging = true
        }
    }

    composeOptions {
        // 与 Kotlin 1.9.25 配套；与 Compose BOM 2024.12+ 的 Material3 对齐
        kotlinCompilerExtensionVersion = "1.5.15"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
        freeCompilerArgs += listOf(
            "-P",
            "plugin:androidx.compose.compiler.plugins.kotlin:strongSkipping=true",
        )
    }

}

tasks.matching {
    it.name in listOf("preReleaseBuild", "validateSigningRelease", "assembleRelease", "bundleRelease")
}.configureEach {
    doFirst {
        if (!hasReleaseSigningConfig) {
            throw GradleException(
                "Release signing is not configured. Create Android-App/signing/keystore.properties " +
                    "and use the same .jks on every build machine, or set PONYCHAT_RELEASE_* environment variables."
            )
        }
    }
}

dependencies {
    // Compose BOM
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("junit:junit:4.13.2")

    // Compose + Lifecycle
    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.7.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.7.0")
    // ProcessLifecycleOwner（前台/后台切换时补拉消息；需显式依赖，否则仅合并清单不足以参与编译）
    implementation("androidx.lifecycle:lifecycle-process:2.7.0")
    implementation("androidx.navigation:navigation-compose:2.7.7")

    // Core AndroidX
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.activity:activity-ktx:1.9.0")

    // Networking
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:okhttp-sse:4.12.0")
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    implementation("com.google.code.gson:gson:2.10.1")

    // Image loading
    implementation("io.coil-kt:coil-compose:2.7.0")
    implementation("io.coil-kt:coil-gif:2.7.0")

    // Baseline Profile installer — 应用安装时自动编译 baseline-prof.txt 中的热路径，消除 JIT 冷启动卡顿
    implementation("androidx.profileinstaller:profileinstaller:1.3.1")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")

    // WorkManager (for background job polling)
    implementation("androidx.work:work-runtime-ktx:2.9.1")

    // OkHttp logging
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // Markdown rendering
    implementation("io.noties.markwon:core:4.6.2")
    implementation("io.noties.markwon:ext-strikethrough:4.6.2")
    implementation("io.noties.markwon:ext-tables:4.6.2")
    implementation("io.noties.markwon:linkify:4.6.2")

    // Drag-to-reorder for LazyColumn
    implementation("sh.calvin.reorderable:reorderable:2.4.3")

    // 扫一扫：CameraX + ML Kit 条码/二维码
    val camerax = "1.3.3"
    implementation("androidx.camera:camera-core:$camerax")
    implementation("androidx.camera:camera-camera2:$camerax")
    implementation("androidx.camera:camera-lifecycle:$camerax")
    implementation("androidx.camera:camera-view:$camerax")
    implementation("com.google.mlkit:barcode-scanning:17.2.0")

    androidTestImplementation("androidx.test:runner:1.5.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
}

/**
 * 把 material-icons-extended / material-icons-core（含 -android 变体）
 * 按 Maven 标准目录结构写入 icon-packs/android/local-maven-repo/，
 * 使构建时优先命中本地仓库，不再走远程。
 *
 * 用法：./gradlew :app:refreshLocalIconRepo
 */
tasks.register("refreshLocalIconRepo") {
    group = "assets"
    description = "把 Compose 图标包的 AAR/POM/module 写入本地 Maven 仓库，以便离线优先使用。"
    doLast {
        val iconGroups = listOf(
            "material-icons-extended",
            "material-icons-extended-android",
            "material-icons-core",
            "material-icons-core-android"
        )

        val resolved = configurations.getByName("debugRuntimeClasspath")
            .resolvedConfiguration
            .resolvedArtifacts
            .filter {
                it.moduleVersion.id.group == "androidx.compose.material" &&
                    it.name in iconGroups
            }

        if (resolved.isEmpty()) {
            throw GradleException("未找到 material-icons 依赖产物，请先连网执行一次依赖解析。")
        }

        val repoRoot = rootProject.layout.projectDirectory
            .dir("../icon-packs/android/local-maven-repo").asFile

        resolved.forEach { artifact ->
            val id = artifact.moduleVersion.id
            val groupPath = id.group.replace('.', '/')
            val destDir = File(repoRoot, "$groupPath/${id.name}/${id.version}")
            if (!destDir.exists()) destDir.mkdirs()

            // 标准 Maven 文件名
            val destName = "${id.name}-${id.version}.${artifact.extension}"
            val destFile = File(destDir, destName)
            if (!destFile.exists()) {
                artifact.file.copyTo(destFile)
                logger.lifecycle("  COPIED → $groupPath/${id.name}/${id.version}/$destName")
            } else {
                logger.lifecycle("  SKIP   → $groupPath/${id.name}/${id.version}/$destName (已存在)")
            }
        }
        logger.lifecycle("✅ 本地 Maven 仓库已刷新：${repoRoot.absolutePath}")
    }
}
