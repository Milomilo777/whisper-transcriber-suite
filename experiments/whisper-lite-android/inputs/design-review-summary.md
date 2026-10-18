## Design review result (Argon High + ChatGPT Work Sol Max, 4 pieces each, 21:20; raw: review-*.raw.txt)
Both reviewers agree on these changes (claims, Android facts to verify on developer.android.com before coding):
1. Order: CI guardrails (no INTERNET via apkanalyzer, 16 KB ELF alignment) + the 3-engine spike on a real ARM64
   phone FIRST; model import UI only after the engine (and its multi-file model format) is chosen.
2. Audio: bounded streaming URI -> decoder -> stateful anti-alias resampler -> engine (no full temp PCM); stage
   shared (ACTION_SEND) URIs at once (grants expire); non-seekable provider streams copied to bounded staging.
3. Android 14-16: foreground-service type (mediaProcessing on 35+, dataSync on 34) + onTimeout() + 6 h/24 h limit;
   native .so 16 KB aligned (NDK r28+); bounded PARTIAL_WAKE_LOCK + WAKE_LOCK permission; notification permission
   optional.
4. Native safety: engine in its own process (android:process=":engine"), whisper.cpp abort_callback for
   cancellation, mutex-guarded native lifetime, C++ exceptions caught at the JNI boundary, capped thread count.
5. Privacy: "no INTERNET" is not "never uploads" (Android Auto Backup): models/audio/results in noBackupFilesDir or
   excluded; describe it as "local transcription, no network permission".
6. Model install: transactional (hash while copying, atomic activate), archives with zip-slip checks; option of an
   APK flavour that bundles the Persian model (no download step at all).
7. Output: SAF CreateDocument / MediaStore.Downloads, long shares via FileProvider, words grouped into readable SRT
   cues, RTL-aware list, one-tap copy; Persian character normalisation (Arabic kaf/yeh) optional.
8. Build: Gradle caching is not reproducibility; F-Droid builds native code from source; pin toolchains; CI must run
   instrumented tests; real-device tests on Android 14-16.
Open point: Argon prefers WorkManager CoroutineWorker + setForeground; ChatGPT warns Android 16 job quotas make that
not automatically better -> decide with a measured prototype.
Both checked the DeepSeek-style resampler concern independently: a Kotlin windowed-sinc resampler is acceptable only
with tests for anti-aliasing and continuity (the mutation run above shows those tests are still missing).

## Jules
