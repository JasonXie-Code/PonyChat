# 2026-05-22 Change Log

## Android 系统底部导航栏颜色修复

- 新增统一的 `SystemNavigationBarColorEffect`，集中管理 Android 系统底部导航栏颜色、图标明暗和 Android 10+ 的导航栏对比度遮罩。
- 在页面组合、主题/颜色变化和 `ON_RESUME` 时重新下发系统导航栏颜色，避免锁屏解锁或切回前台后系统栏停留在旧颜色、黑色或被系统遮罩加深。
- 角色列表主页显式将系统底部导航栏同步为底部 Tab 区域的 `surface` 色，避免只依赖 `navigationBarsPadding()` 导致系统导航区颜色失控。
- 聊天页和聊天显示设置页改用统一 effect，分别同步到底部输入栏贴合色和设置页背景色。
- Galgame 生命体征抽屉在前台恢复时按当前抽屉位置重新同步系统导航栏颜色，抽屉关闭时恢复进入前的颜色与图标明暗。

## 验证

- `ReadLints` 未发现新增诊断错误。
- 使用 `JAVA_HOME=P:/Tools/jdk-17` 执行 `./gradlew.bat :app:compileDebugKotlin`，编译通过。

## 涉及文件

- `Android-App/app/src/main/java/top/ponychat/webview/ui/common/SystemNavigationBarColorEffect.kt`
- `Android-App/app/src/main/java/top/ponychat/webview/ui/character/CharacterListScreen.kt`
- `Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatScreenContentBody.kt`
- `Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatDisplaySettings.kt`
- `Android-App/app/src/main/java/top/ponychat/webview/ui/chat/ChatScreenGalgame.kt`
