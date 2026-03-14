# macOS Network Connectivity Implementation Plan

This document outlines the investigation and fixes for network connectivity issues in the macOS build of ChordCoach Companion, specifically addressing App Sandbox constraints and SSL certification resolution in frozen bundles.

## Issues Identified
1. **App Sandbox constraints**: By default, sandboxed macOS apps cannot access the network.
2. **Missing/Inaccessible SSL Certificates**: Python libraries inside the frozen PyInstaller bundle (e.g., `requests`, `websockets`) are unable to resolve certificate paths on macOS, leading to `SSLCertVerificationError` when connecting to APIs.

---

## 1. Create Entitlements (`entitlements.plist`)
Create an `entitlements.plist` file containing setup to grant appropriate network and CS capabilities without fully sandboxing to ease development if needed, while granting required capabilities.

**Status:** ✅ Complete
**File:** `entitlements.plist`
- Grants `com.apple.security.network.client` and `com.apple.security.network.server`.
- Enables JIT and unsigned executable memory features needed for Python executables with bundled frameworks.

---

## 2. Update PyInstaller Configuration (`chordcoach.spec`)
Configure PyInstaller on macOS to use the created `entitlements.plist` file for signing the executable inside the bundle setup.

**Status:** ✅ Complete
**File:** `chordcoach.spec`
- Line 144: `entitlements_file='entitlements.plist' if is_mac else None` added to the `EXE` target.

---

## 3. Global SSL Certification Handling (`src/core/bootstrap.py`)
Ensure that when the app runs in frozen mode (compiled binary), it correctly resolves SSL certificates for standard Python libraries (like `requests` and `websockets`) in case the host environment fallback is breaking.

**Status:** ✅ Complete
**File:** `src/core/bootstrap.py`
- Added the following block inside the `is_frozen` branch of `setup_env()` to automatically load bundled certs:
```python
        # Ensure SSL Certificates are loaded correctly for requests/websockets inside frozen bundle
        try:
            import certifi
            os.environ['SSL_CERT_FILE'] = certifi.where()
            os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
        except ImportError:
            pass
```

---

## Verification Strategy
1. **Local verification (Windows)**: Run PyInstaller to ensure that adding `entitlements_file` does not break the Windows executable or compilation flow.
2. **CI/CD verification (macOS)**: Push changes and wait for the macOS build action to execute. Verify the generated `.app` bundle maintains fully functioning networking (Gemini API, and any other web components).
