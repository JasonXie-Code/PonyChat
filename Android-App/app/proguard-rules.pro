# Add project specific ProGuard rules here.

# ----- Gson 序列化保护 -----
# 保留泛型类型信息（Gson TypeToken / TypeAdapter 必需）
-keepattributes Signature
-keepattributes *Annotation*

# 保留 Gson 自身
-dontwarn sun.misc.**
-keep class com.google.gson.** { *; }
-keep class * extends com.google.gson.reflect.TypeToken
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer

# 保留带 @SerializedName 的字段（勿让 R8 改名）
-keepclassmembers,allowobfuscation class * {
    @com.google.gson.annotations.SerializedName <fields>;
}

# ----- 数据模型包：全量保留，防止 R8 把 JSON 字段名混淆为 a/b/c -----
-keep class top.ponychat.webview.data.model.** { *; }

# 本地 SharedPreferences 缓存也通过 Gson 反序列化。
# CachedConversation 位于 data.local，不在 data.model keep 范围内；release 混淆后会导致缓存读取/统计失真。
-keep class top.ponychat.webview.data.local.CachedConversation { *; }
