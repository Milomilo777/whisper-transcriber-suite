### 1. Architecture and Module Layout
**Jetpack Compose:** Yes. The UI will be built entirely with Jetpack Compose. It reduces boilerplate and fits the single-activity architecture well.

**Module Layout:** A single `:app` module for the MVP. Multi-module setups (e.g., `:core`, `:engine`, `:app`) introduce Gradle configuration overhead that is unnecessary for a solo maintainer MVP. 
*   **UI Layer:** Compose screens and ViewModels.
*   **Service Layer:** A foreground `Service` for transcription execution.
*   **Audio Layer:** Kotlin wrappers around `MediaExtractor` and `MediaCodec`.
*   **Engine Layer:** A Kotlin-defined `interface TranscriptionEngine` and its specific implementations.
*   **Data Layer:** Room database for tracking transcription history (metadata only) and DataStore for preferences.

### 2. Engine Abstraction and Integration
A Kotlin interface will decouple the app from the underlying engine:
```kotlin
interface TranscriptionEngine {
    suspend fun initialize(modelPath: String)
    suspend fun transcribe(pcm16kMonoFile: File): Flow<TranscriptionProgress>
    fun close()
}
```
Integration and trade-offs:
*   **whisper.cpp (MIT):** Integrated via JNI. The maintainer builds a shared library (`.so`) using Android NDK. *Trade-offs:* Highest raw performance and lowest APK size overhead if stripped properly. However, JNI bridges are fragile; a C++ crash brings down the entire app. Requires manual 16kHz mono audio input.
*   **sherpa-onnx (Apache-2.0):** Integrated as an AAR dependency. *Trade-offs:* Easiest to integrate. Supports multiple model architectures (Whisper, Moonshine). Larger APK size due to the ONNX runtime. Memory overhead might be higher than a pure C++ implementation.
*   **Vosk (Apache-2.0):** Integrated as an AAR. *Trade-offs:* Very lightweight and fast. The Persian model is ~53MB. Designed for streaming, so batching long audio requires splitting. Quality may be lower than Whisper-based models for complex Persian text. 

**Critical Note:** Vosk and sherpa-onnx AARs may include networking permissions in their manifests. The build must use `tools:node="remove"` in the final AndroidManifest.xml to strip any `INTERNET` permissions injected by dependencies.

### 3. Model Management
To maintain strict privacy and prove no telemetry, the app will have **zero INTERNET permission**. 

*   **One-time download:** The app will *not* download models. It will provide a list of verified model URLs. The user downloads the model via a system browser. 
*   **Import & Integrity:** The user uses the Android File Picker (Storage Access Framework) to select the downloaded model. The app copies it to internal storage (`context.dataDir/files/models/`) and verifies a hardcoded SHA-256 checksum. If the checksum fails, the file is deleted immediately.
*   **Storage & Deletion:** Models are stored in app-internal storage. A "Delete Model" button in the UI deletes the file from disk. The app does not use MediaStore for models, preventing accidental gallery scans.

### 4. Audio Input
*   **Intent Filters:** The app will register an `intent-filter` for `ACTION_SEND` to handle `audio/*` mime types shared from messengers (Telegram, WhatsApp). It will also register for `ACTION_VIEW` with `audio/*` to act as a default audio opener.
*   **File Picker:** `ActivityResultContracts.OpenDocument()` to allow users to select files from local storage or cloud drives.
*   **Decoding without GPL:** The app will use Android's built-in `MediaExtractor` and `MediaCodec` to decode m4a, opus, ogg, and mp3. 
    *   *Pipeline:* `MediaExtractor` reads the container -> `MediaCodec` decodes to raw PCM -> Kotlin buffer resamples to 16kHz mono -> write to a temporary `.pcm` file.
    *   *Trade-off:* `MediaCodec` is asynchronous and hardware-dependent. Some OEM decoders may output different sample formats. The pipeline must handle floating-point PCM (32-bit) and signed integer PCM (16-bit) and downmix stereo to mono. *Unsure:* exact memory limits of `MediaCodec` on low-end Android 10 devices for very long audio files; a chunked approach might be needed.

### 5. Long Jobs
**Foreground Service (FGS)** is mandatory. `WorkManager` is inappropriate because it is designed for deferrable background tasks and the system may kill it; transcription is user-initiated and requires active execution.

*   **Implementation:** A `Service` runs with `startForeground()`. The UI binds to the service to observe progress and send cancellation signals.
*   **Progress & Cancellation:** The engine (e.g., whisper.cpp) must expose a callback for segment progress. If the engine does not support native cancellation, the service must check an `AtomicBoolean` flag between segments and throw an `CancellationException` if the user requests a stop.
*   **Battery and Heat:** The service will run on `Dispatchers.Default`. It will not acquire a `WakeLock` by default; if the screen turns off, the system may doze and pause the FGS. A checkbox ("Prevent device from sleeping") will allow the user to acquire a `PARTIAL_WAKE_LOCK` if they are transcribing a massive file. A warning will be displayed regarding heat.

### 6. Output
*   **Formats:** Plain Text (`.txt`) and SubRip Subtitle (`.srt`). 
*   **Segmentation:** The app must rely on the engine's timestamp outputs. whisper.cpp provides segment timestamps. Vosk provides word-level timestamps. The app will format these into the SRT standard.
*   **Share/Export:** The output text is displayed in a `Text` composable. A "Share" button uses `ACTION_SEND` to push the text to other apps. A "Save" button uses `MediaStore.Files` to write the `.txt` or `.srt` to the user's `Downloads` directory.

### 7. Permissions and Privacy
*   **Permissions:** 
    *   `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_DATA_SYNC` (for Android 14+).
    *   `POST_NOTIFICATIONS` (Android 13+).
    *   *Zero* `INTERNET` permission.
    *   *Zero* `READ_EXTERNAL_STORAGE` (using SAF instead).
    *   *Zero* `RECORD_AUDIO` (MVP only transcribes existing files).
*   **Proving no INTERNET:** The final merged `AndroidManifest.xml` will be checked via a CI script to ensure `<uses-permission android:name="android.permission.INTERNET" />` does not exist. The app will use no analytics SDKs. Users can verify this by inspecting the APK via App Inspector or using Wireshark.

### 8. Testing
*   **Unit Tests:** JUnit tests for SRT timestamp formatting, SHA-256 verification logic, and audio resampling math.
*   **Instrumented Tests:** `androidx.test` tests running on an emulator. Testing the `MediaCodec` pipeline by passing a known `.m4a` file and verifying the output temporary `.pcm` file matches expected sizes.
*   **Golden-Audio Tests:** A 10-second Persian audio file and its expected text transcription are committed to the repo. An instrumented test runs the selected engine against this file and asserts the output matches with a standard edit distance tolerance.
*   **Airplane Mode Test:** A manual acceptance test script. The tester enables Airplane Mode, clears app data, imports a model via SAF, imports an audio file via SAF, and runs a transcription. If it succeeds, the offline mandate is met.

### 9. Build and Release
*   **GitHub Actions:** A CI workflow runs on push and PR: `./gradlew test` and `./gradlew assembleDebug`.
*   **Reproducible Builds:** The Gradle config will use `org.gradle.caching=true` and `org.gradle.configuration-cache=true`. The CI will build an APK and publish it to GitHub Releases.
*   **F-Droid Friendliness:** All dependencies will be from Maven Central or JitPack (if required for sherpa-onnx snapshots). No Google proprietary dependencies (no Firebase, no ML Kit). The app will use standard AndroidX and Kotlin coroutines only.
*   **Signing:** The maintainer uses a dedicated release keystore. To support reproducible builds on F-Droid, the maintainer can provide the exact Gradle version and JDK version in the README. For MVP, standard v2 APK signing is sufficient.

### 10. Risks
*   **OEM `MediaCodec` fragmentation:** Decoding opus/m4a on specific Android skins (e.g., MIUI) might fail or output corrupted PCM.
*   **JNI Crashes:** whisper.cpp C++ exceptions or out-of-memory errors will crash the app. There is no way to catch JNI segfaults in Kotlin.
*   **Memory Pressure:** Decoding a 2-hour interview to raw 16kHz PCM creates a massive file (~230MB). Writing this to internal storage might trigger `ENOENT` (Out of space). The app must check available disk space before decoding.
*   **Persian Text Formatting:** NLP models sometimes output Persian text without proper zero-width non-joiners, resulting in disconnected letters. Post-processing might be required.

### 11. Phased Plan

**Phase 1: Engine Abstraction & Model Import**
*   *Tasks:* Create the `TranscriptionEngine` interface. Implement the Vosk or sherpa-onnx wrapper. Build the UI for SAF model import and SHA-256 validation.
*   *Done when:* App can import a model, initialize the engine, and run a hardcoded transcription on a raw `.pcm` file provided via ADB, all in Airplane Mode.

**Phase 2: Audio Decoding & Foreground Service**
*   *Tasks:* Implement `MediaCodec` decoding to 16kHz mono. Build the FGS with notification, progress, and cancellation. 
*   *Done when:* App can receive an `.m4a` via Share Sheet, decode it, transcribe it via the FGS, and display the progress percentage without crashing.

**Phase 3: UI & Output Export**
*   *Tasks:* Build the main UI (history list, transcription view). Implement `.txt` and `.srt` formatters. Add `MediaStore` export.
*   *Done when:* User can view the transcribed text, export it as an SRT file to Downloads, and share it via intent.

**Phase 4: CI, Privacy Audit & Release**
*   *Tasks:* Set up GitHub Actions. Add the AndroidManifest INTERNET permission check script. Write golden-audio tests.
*   *Done when:* CI passes on PR. Airplane mode acceptance test succeeds. APK is published to GitHub Releases.