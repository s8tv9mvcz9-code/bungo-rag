# kotlinx.serialization が生成する serializer を保持
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class com.bungo.rag.data.** {
    *** Companion;
}
-keepclasseswithmembers class com.bungo.rag.data.** {
    kotlinx.serialization.KSerializer serializer(...);
}
