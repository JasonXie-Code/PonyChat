package top.ponychat.companion.ipc;

/** Minimal, versioned capability handshake between PonyChat and the system runtime. */
interface ICompanionRuntime {
    int getProtocolVersion();
    String getRuntimeVersion();
    boolean isDeviceProvisioned();
    void configureSession(String apiBase, String username, String authToken, String characterId, String personalityStyle);
    void setOverlayVisible(boolean visible);
    String getDiagnosticSnapshot();
    String repairSystemProvisioning();
}
