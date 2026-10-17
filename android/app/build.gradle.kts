plugins {
    id("com.android.application")
}

android {
    namespace = "com.ampilight.tv"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.ampilight.tv"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
