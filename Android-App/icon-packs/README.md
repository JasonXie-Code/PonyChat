# Icon Packs（离线本地仓库）

本目录存放图标包的离线副本，确保构建和运行时**完全不依赖外网**。

---

## 目录结构

```
icon-packs/
├── web/
│   └── ionicons-8.0.13.tgz          ← Ionicons 8 完整包（npm pack）
│
└── android/
    ├── local-maven-repo/             ← Maven 标准目录结构（Gradle 直接读取）
    │   └── androidx/compose/material/
    │       ├── material-icons-extended/1.6.8/
    │       ├── material-icons-extended-android/1.6.8/  ← 34 MB AAR
    │       ├── material-icons-core/1.6.8/
    │       └── material-icons-core-android/1.6.8/      ← 0.8 MB AAR
    │
    └── material-icons-extended/      ← 旧版备份（flat），可忽略
        └── material-icons-extended-1.6.8.aar
```

---

## Web 端 Ionicons

运行时图标资源路径：`frontend/js/ionicons/`  
包含完整 SVG 图标库 + `ionicons.esm.js` 运行时，后端直接静态服务，**不走 CDN**。

重新打包（需要联网）：
```bash
cd frontend/web
npm pack ionicons --pack-destination "../../icon-packs/web"
```

---

## Android 端 Material Icons Extended

### 使用说明

`settings.gradle.kts` 已将 `icon-packs/android/local-maven-repo` 注册为**最优先**的 Maven 仓库，  
Gradle 解析 `material-icons-extended` 时会先命中本地，**离线构建也可通过**（已验证 `--offline` 成功）。

### 刷新本地仓库（需联网）

在 `app/` 目录执行：
```bash
./gradlew :app:refreshLocalIconRepo
```

该任务从 Gradle 缓存中提取 AAR/POM/module 文件，按 Maven 目录规范写入 `local-maven-repo`。

---

## 当前已收录版本

| 包 | 版本 | 大小 |
|---|---|---|
| Ionicons (Web) | 8.0.13 | ~tgz |
| material-icons-extended-android | 1.6.8 | ~34 MB |
| material-icons-core-android | 1.6.8 | ~0.8 MB |
