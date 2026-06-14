# JNI 네이티브 메서드 보존
-keepclasseswithmembernames class * {
    native <methods>;
}
-keep class com.calenda.LlamaBridge { *; }
