pluginManagement {
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/public") }
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        // ① 本地图标包 Maven 仓库（最优先，离线时不走网络）
        maven {
            name = "LocalIconPacks"
            url = uri("${rootDir}/../icon-packs/android/local-maven-repo")
        }
        // ② 旧本地仓库（保留兼容）
        maven {
            url = uri("${rootDir}/../local-repo")
        }
        // ③ 阿里云镜像 + 原始仓库
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        maven { url = uri("https://maven.aliyun.com/repository/public") }
        google()
        mavenCentral()
        maven { url = uri("https://jitpack.io") }
    }
}

rootProject.name = "PonyChatApp"
include(":app")
