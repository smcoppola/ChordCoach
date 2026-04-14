import os
from pathlib import Path
from PySide6.QtCore import QObject, Property, Slot, Signal, QSettings # type: ignore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database_manager import DatabaseManager

class SettingsService(QObject):
    apiKeyChanged = Signal()
    skillMatrixSummaryChanged = Signal()
    statsChanged = Signal()
    coachSettingsChanged = Signal()
    midiOutChanged = Signal()
    notationStyleChanged = Signal()
    notationColorModeChanged = Signal()

    def __init__(self, db_manager, user_data_path):
        super().__init__()
        self.db = db_manager
        
        # Initializes QSettings natively (Registry/Plist/INI) avoiding raw file I/O.
        self.qsettings = QSettings("ChordCoach", "Companion")
        
        # Legacy .env migration 
        self._migrate_legacy_env(Path(user_data_path) / ".env")

        # Caches for DB properties to prevent synchronous DB reads on QML render
        self._cached_matrix = self.db.get_coach_context()
        self._cached_chord_stats = self.db.get_all_chord_stats()
        self._cached_song_stats = self.db.get_all_song_stats()

    def _migrate_legacy_env(self, env_file: Path):
        """One-time migration from .env to QSettings."""
        if not env_file.exists() or self.qsettings.contains("GOOGLE_API_KEY"):
            return
            
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        key, val = line.strip().split("=", 1)
                        self.qsettings.setValue(key, val)
        except Exception as e:
            print(f"SettingsService: .env migration failed: {e}")

    # --- Generic QSettings Helpers ---

    def _get_setting(self, key: str, default: str) -> str:
        return str(self.qsettings.value(key, default))

    def _set_setting(self, key: str, val: str, signal: Signal):
        if str(self.qsettings.value(key, "")) != val:
            self.qsettings.setValue(key, val)
            signal.emit()

    # --- API Key ---

    @Property(str, notify=apiKeyChanged)
    def apiKey(self):
        return self._get_setting("GOOGLE_API_KEY", "")

    @apiKey.setter
    def apiKey(self, val):
        self._set_setting("GOOGLE_API_KEY", val, self.apiKeyChanged)

    # --- Coach Settings ---

    @Property(str, notify=coachSettingsChanged)
    def coachVoice(self) -> str:
        return self._get_setting("COACH_VOICE", "Kore")

    @coachVoice.setter
    def coachVoice(self, val: str):
        self._set_setting("COACH_VOICE", val, self.coachSettingsChanged)

    @Property(str, notify=coachSettingsChanged)
    def coachBrevity(self) -> str:
        return self._get_setting("COACH_BREVITY", "Normal")

    @coachBrevity.setter
    def coachBrevity(self, val: str):
        self._set_setting("COACH_BREVITY", val, self.coachSettingsChanged)

    @Property(str, notify=coachSettingsChanged)
    def coachPersonality(self) -> str:
        return self._get_setting("COACH_PERSONALITY", "Encouraging")

    @coachPersonality.setter
    def coachPersonality(self, val: str):
        self._set_setting("COACH_PERSONALITY", val, self.coachSettingsChanged)

    # --- MIDI Output ---

    @Property(bool, notify=midiOutChanged)
    def midiOutEnabled(self) -> bool:
        val = self.qsettings.value("MIDI_OUT_ENABLED", True)
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes")
        return bool(val)

    @midiOutEnabled.setter
    def midiOutEnabled(self, val: bool):
        if self.midiOutEnabled != val:
            self.qsettings.setValue("MIDI_OUT_ENABLED", val)
            self.midiOutChanged.emit()

    # --- Notation Config ---

    @Property(str, notify=notationStyleChanged)
    def notationStyle(self) -> str:
        # Lowercase sanitization
        return self._get_setting("NOTATION_STYLE", "enhanced").lower()

    @notationStyle.setter
    def notationStyle(self, val: str):
        safe_val = str(val).lower()
        if safe_val in ("enhanced", "traditional"):
            self._set_setting("NOTATION_STYLE", safe_val, self.notationStyleChanged)

    @Property(str, notify=notationColorModeChanged)
    def notationColorMode(self) -> str:
        # Lowercase sanitization
        return self._get_setting("NOTATION_COLOR_MODE", "pedagogical").lower()

    @notationColorMode.setter
    def notationColorMode(self, val: str):
        safe_val = str(val).lower()
        if safe_val in ("pedagogical", "monochrome"):
            self._set_setting("NOTATION_COLOR_MODE", safe_val, self.notationColorModeChanged)

    # ── DB Cache Implementation ──────────────────────────────────────────

    @Property(str, notify=skillMatrixSummaryChanged)
    def skillMatrixSummary(self):
        return self._cached_matrix

    @Property(list, notify=statsChanged)
    def chordStats(self):
        return self._cached_chord_stats

    @Property(list, notify=statsChanged)
    def songStats(self):
        return self._cached_song_stats

    @Slot()
    def resetSkillMatrix(self):
        self.db.reset_all_stats()
        self._refresh_caches()

    @Property(bool, notify=statsChanged)
    def hasCompletedOnboarding(self) -> bool:
        val = self.qsettings.value("ONBOARDING_COMPLETE", False)
        return str(val).lower() in ("true", "1")

    @Slot()
    def markOnboardingComplete(self):
        self.qsettings.setValue("ONBOARDING_COMPLETE", True)
        self.statsChanged.emit()

    def _refresh_caches(self):
        """Call this from AppCoordinator when a lesson or evaluation finishes."""
        self._cached_matrix = self.db.get_coach_context()
        self._cached_chord_stats = self.db.get_all_chord_stats()
        self._cached_song_stats = self.db.get_all_song_stats()
        self.skillMatrixSummaryChanged.emit()
        self.statsChanged.emit()