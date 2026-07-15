plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.bungo.rag"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.bungo.rag"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        // API のベースURL。gradle.properties の BUNGO_BASE_URL を埋め込む。
        // 既定は本番 bungo-api（iOS の Config.swift / project.yml と同一URL）。
        // ローカル開発時は gradle.properties を上書きするか
        // -PBUNGO_BASE_URL=http://10.0.2.2:8000 を渡す（10.0.2.2 = エミュレータ→ホスト）。
        val baseUrl = (project.findProperty("BUNGO_BASE_URL") as String?)
            ?: "https://bungo-api.gentleground-ba3d7ba2.japaneast.azurecontainerapps.io"
        buildConfigField("String", "BASE_URL", "\"$baseUrl\"")
    }

    signingConfigs {
        // CI・ローカルで共通の debug 署名。ランナー毎に生成される debug.keystore だと
        // APK 更新時に署名不一致（INSTALL_FAILED_UPDATE_INCOMPATIBLE）で毎回
        // アンインストールが必要になるため、debug 専用鍵をコミットして固定する。
        // （debug 証明書はストア公開に使えないため秘匿価値は無い）
        create("sharedDebug") {
            storeFile = rootProject.file("ci-debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("sharedDebug")
        }
        release {
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
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    debugImplementation(libs.androidx.ui.tooling)

    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.ktor.client.android)
    implementation(libs.ktor.client.content.negotiation)
    implementation(libs.ktor.serialization.kotlinx.json)
}
