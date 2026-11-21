# PonyChat release signing

> 文档状态：2026-08-09 已复核。易变的版本、部署和服务状态在使用前仍需现场验证。

Release APKs must be signed with the same key on every build machine so users can install updates without uninstalling the existing app.

One-time setup:

```powershell
cd P:\PonyChat\Android-App\signing
keytool -genkeypair -v -keystore ponychat-release.jks -alias ponychat -keyalg RSA -keysize 2048 -validity 10000
Copy-Item keystore.properties.example keystore.properties
```

Then edit `keystore.properties` with the password used when generating the key.

On other computers, copy the same `ponychat-release.jks` and `keystore.properties` into `Android-App/signing/`.

These files are intentionally ignored by Git:

- `ponychat-release.jks`
- `keystore.properties`

The public certificate and its pinned SHA-256 fingerprint are tracked at
`../../product-signing/ponychat-product-cert.pem` and `../../product-signing/README.md`.
Companion automatically reuses this local signing configuration so both release APKs have
the same signature identity.

