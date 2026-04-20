# GIMO Mesh ProGuard rules

# Keep serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt

-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class kotlinx.serialization.json.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# Keep data models
-keep class com.gredinlabs.gimomesh.data.model.** { *; }

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }

# Chaquopy — the Python runtime reflects into these classes via JNI.
# The plugin ships its own consumer rules but we make them explicit here
# as defence-in-depth against future minification tuning.
-keep class com.chaquo.python.** { *; }
-dontwarn com.chaquo.python.**
