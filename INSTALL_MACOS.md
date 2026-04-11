# macOS Installation Instructions (Unsigned Build)

Because ChordCoach Companion is currently an ad-hoc signed application, macOS Gatekeeper will prevent it from running by default. Use the following steps to install and run the application.

## 1. Bypass Gatekeeper (Quarantine)

When you download the `.dmg` and drag the `.app` to your Applications folder, macOS sets a "quarantine" flag on the file. To remove this flag and allow the app to launch:

1.  Open **Terminal** (Cmd + Space, type "Terminal").
2.  Paste the following command and press Enter:
    ```bash
    xattr -d com.apple.quarantine /Applications/ChordCoachCompanion.app
    ```

## 2. Manual Open (Alternative)

Alternatively, you can try:
1.  Locate the app in Finder.
2.  **Right-click** (or Control-click) the app icon and select **Open**.
3.  A dialog will appear asking if you are sure. Click **Open** again.

---

## 3. Logs & Troubleshooting

If the application hangs on launch (common with MIDI/Audio initialization on macOS), you can check the log file for detailed error reports.

### Log File Location:
Open Terminal and run:
```bash
tail -f "~/Library/Application Support/ChordCoach/logs/chordcoach.log"
```

Or browse to the folder in Finder:
1.  Open Finder.
2.  Press **Cmd + Shift + G**.
3.  Paste: `~/Library/Application Support/ChordCoach/logs/`
4.  Open `chordcoach.log` with TextEdit.

### Common Issues:
*   **Frozen on Start**: This usually means the app is waiting for a MIDI device or Audio driver to respond. Ensure your MIDI keyboard is plugged in or try launching the app through Terminal to see live output.
