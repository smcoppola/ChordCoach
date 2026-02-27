import os
from pathlib import Path
from PySide6.QtCore import QObject, Property, Slot, Signal # type: ignore

class SettingsService(QObject):
    apiKeyChanged = Signal()
    skillMatrixSummaryChanged = Signal()
    statsChanged = Signal()
    coachSettingsChanged = Signal()

    def __init__(self, db_manager, project_root):
        super().__init__()
        self.db = db_manager
        self.env_file = project_root / ".env"

    # ── Generic .env helpers ──────────────────────────────────────────

    def _get_env(self, key: str, default: str = "") -> str:
        return os.environ.get(key, default)

    def _set_env(self, key: str, val: str):
        if os.environ.get(key) == val:
            return
        os.environ[key] = val
        try:
            lines = []
            if self.env_file.exists():
                try:
                    with open(self.env_file, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                except UnicodeDecodeError:
                    with open(self.env_file, "r", encoding="utf-16") as f:
                        lines = f.readlines()
            
            new_lines = []
            found = False
            for line in lines:
                if line.strip().startswith(f"{key}="):
                    new_lines.append(f"{key}={val}\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"{key}={val}\n")
                
            with open(self.env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception as e:
            print(f"Failed to write {key} to .env: {e}")

    # ── API Key ───────────────────────────────────────────────────────

    @Property(str, notify=apiKeyChanged)
    def apiKey(self):
        return os.environ.get("GOOGLE_API_KEY", "")

    @apiKey.setter
    def apiKey(self, val):
        if os.environ.get("GOOGLE_API_KEY") != val:
            self._set_env("GOOGLE_API_KEY", val)
            self.apiKeyChanged.emit()

    # ── Coach Voice ───────────────────────────────────────────────────

    @Property(str, notify=coachSettingsChanged)
    def coachVoice(self) -> str:
        return self._get_env("COACH_VOICE", "Puck")

    @coachVoice.setter # type: ignore
    def coachVoice(self, val: str):
        self._set_env("COACH_VOICE", val)
        self.coachSettingsChanged.emit()

    # ── Coach Brevity ─────────────────────────────────────────────────

    @Property(str, notify=coachSettingsChanged)
    def coachBrevity(self) -> str:
        return self._get_env("COACH_BREVITY", "Normal")

    @coachBrevity.setter # type: ignore
    def coachBrevity(self, val: str):
        self._set_env("COACH_BREVITY", val)
        self.coachSettingsChanged.emit()

    # ── Coach Personality ─────────────────────────────────────────────

    @Property(str, notify=coachSettingsChanged)
    def coachPersonality(self) -> str:
        return self._get_env("COACH_PERSONALITY", "Encouraging")

    @coachPersonality.setter # type: ignore
    def coachPersonality(self, val: str):
        self._set_env("COACH_PERSONALITY", val)
        self.coachSettingsChanged.emit()

    # ── Skill Matrix & Stats ──────────────────────────────────────────

    @Property(str, notify=skillMatrixSummaryChanged)
    def skillMatrixSummary(self):
        return self.db.get_coach_context()

    @Property("QVariantList", notify=statsChanged)
    def chordStats(self):
        return self.db.get_all_chord_stats()

    @Property("QVariantList", notify=statsChanged)
    def songStats(self):
        return self.db.get_all_song_stats()

    @Slot()
    def resetSkillMatrix(self):
        self.db.reset_all_stats()
        self.skillMatrixSummaryChanged.emit()
        self.statsChanged.emit()

    @Property(bool, notify=statsChanged)
    def hasCompletedOnboarding(self) -> bool:
        return self.db.has_completed_onboarding()

