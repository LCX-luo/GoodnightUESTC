plugins { id("com.android.application"); id("com.chaquo.python") }
android {
    namespace = "cn.lcx.goodnightuestc"
    compileSdk { version = release(36) { minorApiLevel = 1 } }
    defaultConfig {
        applicationId = "cn.lcx.goodnightuestc"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "0.2.1"
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
        testInstrumentationRunner = "cn.lcx.goodnightuestc.SmokeInstrumentation"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
chaquopy {
    defaultConfig {
        version = "3.13"
        val localPython = rootProject.file("../private-data/wechat-runtime/Scripts/python.exe")
        buildPython(System.getenv("CHAQUOPY_BUILD_PYTHON") ?: if (localPython.exists()) localPython.absolutePath else "python3.13")
        pip { install("cryptography==42.0.8"); install("certifi==2026.10.23") }
    }
    sourceSets { getByName("main") { srcDir("build/generated/wechatPython") } }
}
val prepareWechatPython by tasks.registering(Exec::class) {
    val localPython = rootProject.file("../private-data/wechat-runtime/Scripts/python.exe")
    commandLine(System.getenv("CHAQUOPY_BUILD_PYTHON") ?: if (localPython.exists()) localPython.absolutePath else "python3.13",
        rootProject.file("../prepare_android_wechat.py").absolutePath)
    inputs.file(rootProject.file("../prepare_android_wechat.py"))
    outputs.dir(layout.buildDirectory.dir("generated/wechatPython"))
    outputs.upToDateWhen { false } // Always verify the reviewed source commit before packaging.
}
tasks.configureEach {
    if (name.contains("Python") && name != "prepareWechatPython") dependsOn(prepareWechatPython)
}
