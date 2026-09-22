# PonyChat 产品 APK 证书

`ponychat-product-cert.pem` 是 PonyChat App 与 Companion Runtime 共用签名身份的公开证书，
可以明文提交、分发和用于验签。它不包含私钥，不能用于签署 APK。

- 证书 SHA-256：`A9:1F:D0:63:7A:C9:48:ED:0A:6E:F8:6E:3E:5F:DB:78:68:BB:B9:D0:11:49:8E:F7:C0:14:5A:41:C3:DE:4E:B1`
- 证书主题：`CN=PonyChat, OU=PonyChat, O=PonyChat, L=Shanghai, ST=Shanghai, C=CN`
- 有效期：2026-05-16 至 2053-10-01

私钥位于本地忽略文件 `Android-App/signing/ponychat-release.jks`，密码位于
`Android-App/signing/keystore.properties`。两者不得提交到 Git；正式发布还应在仓库外保留
至少两份加密备份，并限制签名权限。

两个工程执行 `assembleRelease` 时会使用同一份本地配置。也可在受控 CI 中通过
`PONYCHAT_RELEASE_STORE_FILE`、`PONYCHAT_RELEASE_STORE_PASSWORD`、
`PONYCHAT_RELEASE_KEY_ALIAS` 和 `PONYCHAT_RELEASE_KEY_PASSWORD` 注入签名材料。
