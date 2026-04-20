plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.1.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.1.0" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.1.0" apply false
    // Chaquopy — embedded CPython bionic-compatible for Server Node.
    // Resolves G27 blocker: replaces python-build-standalone glibc binary
    // with Chaquopy's Maven Central builds. Since Chaquopy 12.0.1 is MIT.
    id("com.chaquo.python") version "17.0.0" apply false
}
