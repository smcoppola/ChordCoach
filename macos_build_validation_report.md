# macOS Build Configuration Validation Report

This report summarizes findings regarding `.github/workflows/macos-build.yaml` and `chordcoach.spec` focusing on items that may cause issues when distributing or running the application on user machines.

---

## 1. Architecture Constraints (ARM64 vs Intel)
* **Status**: ⚠️ Review Required
* **Observation**: The workflow runs on `macos-latest`, which resolves to an Apple Silicon (ARM64) runner.
* **Impact**: The resulting `.app` and `.dmg` will only run on Apple Silicon Macs (M1/M2/M3). Users on older Intel Macs will not be able to execute the application unless a separate Intel builder is configured or a Universal 2 build pipeline is set up.
* **Suggested Fix**: Use `macos-13` runner if an Intel-native build is desired, or maintain separate release tags for both architectures.

---

## 2. DMG Packaging Scope Coverage
* **Status**: ⚠️ Minor Issue
* **Observation**: The creation command is packaged on the whole directory:
  ```bash
  create-dmg ... "ChordCoachCompanion-macOS.dmg" "dist/"
  ```
* **Impact**: PyInstaller writes multiple targets into `dist/` (e.g., both the `.app` bundle and the `ChordCoachCompanionPortable` raw folder directory). Running on `dist/` bundles both into the final DMG, resulting in visual clutter.
* **Suggested Fix**: Update the workspace workflow sequence to stage files first:
  ```bash
  mkdir staging_dmg
  cp -R dist/ChordCoachCompanion.app staging_dmg/
  create-dmg ... "ChordCoachCompanion-macOS.dmg" "staging_dmg/"
  ```

---

## 3. Codesigning / Notarization Blocker (Gatekeeper)
* **Status**: 🛑 Potential Blocker
* **Observation**: There are no workflow steps involving importing a Developer ID certificate or running notarization tools (e.g., via `gon` or `codesign`).
* **Impact**: 
  - PyInstaller will generate an "Ad-hoc signed" binary.
  - When users download and attempt to open the `.dmg`, Gatekeeper will flag the software as "Damaged & can't be opened" or "Malicious".
  - Users will have to manually bypass Gatekeeper (e.g., by running `xattr -d com.apple.quarantine`) which is a barrier for general user adoption.
* **Suggested Fix**: Incorporate Apple Developer certificates into GitHub secrets and add a notarization step before creating the DMG.

---

## 4. Redundant Homebrew Dependency
* **Status**: ℹ️ Informational
* **Observation**: `brew install qt6` is run.
* **Impact**: PySide6 from `pip install` bundles its full set of native libraries. System packages may be redundant unless C++ custom source code directly ties into system library variables. It does not break the build but increases build duration slightly.

---

### Summary
The actual app structure within `chordcoach.spec` is **well-configured** (entitlements linked, native binaries loaded relocatable). The primary risks are distribution-side configuration metrics: **Target CPU Architecture** and **Gatekeeper warnings (Missing Notarization)**.
