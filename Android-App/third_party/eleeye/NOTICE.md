EleEye / ElephantEye
====================

This app bundles Android builds of EleEye (ElephantEye), a UCCI Chinese chess
engine from the xqbase project.

Source: https://github.com/xqbase/eleeye
Commit used for this build: a9d3914e596da93a150d74af8967edecc0810ef7
Engine version reported by UCCI: ElephantEye 3.31
License file in upstream repository: LICENSE

Bundled files:

- app/src/main/jniLibs/arm64-v8a/libeleeye.so
- app/src/main/jniLibs/armeabi-v7a/libeleeye.so
- app/src/main/jniLibs/x86_64/libeleeye.so
- app/src/main/assets/eleeye/BOOK.DAT

Build notes:

- Built with Android NDK 26.3.11579264.
- The binaries are PIE executables named libeleeye.so so Android Gradle can
  package and extract them through jniLibs.
- Rebuild with tools/build_eleeye_android.ps1.
