"""
CurriculumService — Multi-track curriculum engine for ChordCoach Companion.

Manages long-term learning progress across four tracks (technique, theory,
repertoire, ear), spaced repetition scheduling, and per-session lesson planning.
"""
import json
import time
from pathlib import Path
from PySide6.QtCore import QObject, Property, Signal, Slot  # type: ignore


class CurriculumService(QObject):
    curriculumChanged = Signal()
    sessionPlanReady = Signal()

    def __init__(self, db_manager, resources_dir: Path):
        super().__init__()
        self.db = db_manager
        self._resources_dir = resources_dir
        self._tracks_data: dict = {}
        self._session_plan: dict = {}
        self._session_start_time: float = 0.0
        self._session_tracks: list = []
        self._session_milestones: list = []
        self._session_exercises: int = 0
        self._session_successes: int = 0

        # Load track definitions and initialize DB
        self._load_tracks()
        self.db.initialize_curriculum(self._tracks_data)

    # ── Initialization ────────────────────────────────────────────────

    def _load_tracks(self):
        """Load curriculum track definitions from JSON."""
        tracks_file = self._resources_dir / "curriculum_tracks.json"
        if tracks_file.exists():
            with open(tracks_file, "r", encoding="utf-8") as f:
                self._tracks_data = json.load(f)
            print(f"CurriculumService: Loaded {sum(len(v) for v in self._tracks_data.values())} milestones across {len(self._tracks_data)} tracks")
        else:
            print(f"CurriculumService: WARNING — {tracks_file} not found, using empty curriculum")
            self._tracks_data = {}

    def _get_milestone_meta(self, track_name: str, milestone_id: str) -> dict:
        """Look up the full milestone definition from tracks_data."""
        for m in self._tracks_data.get(track_name, []):
            if m["id"] == milestone_id:
                return m
        return {}

    # ── Session Planning ──────────────────────────────────────────────

    def plan_session(self, available_minutes: int = 10) -> dict:
        """
        Build a session plan by selecting from active milestones
        across 2-3 tracks + spaced repetition review items.

        Returns a SessionPlan dict with:
        - blocks: list of curriculum blocks to generate exercises for
        - review_items: spaced repetition items due today
        - total_estimated_steps: rough step count for the session
        """
        active_milestones = self.db.get_active_milestones()
        due_reviews = self.db.get_due_reviews(limit=5)
        recent_sessions = self.db.get_recent_sessions(limit=3)

        # Build blocks from active milestones (pick up to 3 tracks)
        blocks = []
        tracks_used = set()
        for ms in active_milestones:
            if len(tracks_used) >= 3:
                break
            track = ms["track_name"]
            if track in tracks_used:
                continue

            meta = self._get_milestone_meta(track, ms["milestone_id"])
            if not meta:
                continue

            # Calculate how many steps this block should have
            # Technique gets more steps than theory or ear
            if track == "technique":
                step_count = min(40, max(20, available_minutes * 4))
            elif track == "theory":
                step_count = min(20, max(8, available_minutes * 2))
            else:
                step_count = min(15, max(5, available_minutes))

            blocks.append({
                "track": track,
                "milestone_id": ms["milestone_id"],
                "milestone_title": meta.get("title", ms["milestone_id"]),
                "milestone_description": meta.get("description", ""),
                "exercise_types": meta.get("exercise_types", ["chord"]),
                "target_keys": meta.get("target_keys", ["C"]),
                "target_chords": meta.get("target_chords", []),
                "step_count": step_count,
                "attempts_so_far": ms.get("attempts", 0),
                "successes_so_far": ms.get("successes", 0),
            })
            tracks_used.add(track)

        # If no active milestones, create a default beginner block
        if not blocks:
            blocks.append({
                "track": "technique",
                "milestone_id": "rh_pentascale_c",
                "milestone_title": "Right Hand C Pentascale",
                "milestone_description": "Play C-D-E-F-G ascending and descending with the right hand.",
                "exercise_types": ["pentascale"],
                "target_keys": ["C"],
                "target_chords": [],
                "step_count": 30,
                "attempts_so_far": 0,
                "successes_so_far": 0,
            })

        # Format review items
        review_items = []
        for r in due_reviews:
            review_items.append({
                "item_type": r["item_type"],
                "item_id": r["item_id"],
                "review_count": r.get("review_count", 0),
            })

        total_steps = sum(b["step_count"] for b in blocks) + len(review_items) * 3

        self._session_plan = {
            "blocks": blocks,
            "review_items": review_items,
            "total_estimated_steps": total_steps,
            "tracks": list(tracks_used) if tracks_used else ["technique"],
        }

        # Track session metadata
        self._session_start_time = time.time()
        self._session_tracks = self._session_plan["tracks"]
        self._session_milestones = [b["milestone_id"] for b in blocks]
        self._session_exercises = 0
        self._session_successes = 0

        self.sessionPlanReady.emit()
        print(f"CurriculumService: Planned session with {len(blocks)} blocks across {list(tracks_used)}, ~{total_steps} steps")
        return self._session_plan

    # ── Curriculum Context for Gemini ─────────────────────────────────

    def get_curriculum_context(self) -> str:
        """
        Generate the curriculum-aware context string that enriches
        the Gemini prompt with milestone state, recent sessions, and
        review queue information.
        """
        # Start with the existing skill matrix data
        context = self.db.get_coach_context()

        # Add curriculum state
        active = self.db.get_active_milestones()
        if active:
            context += "\nCurriculum — Active Milestones:\n"
            for ms in active:
                meta = self._get_milestone_meta(ms["track_name"], ms["milestone_id"])
                title = meta.get("title", ms["milestone_id"]) if meta else ms["milestone_id"]
                acc = f"{ms['successes']}/{ms['attempts']}" if ms["attempts"] > 0 else "not started"
                context += f"- [{ms['track_name'].capitalize()}] {title} ({acc})\n"

        # Add recent session history
        recent = self.db.get_recent_sessions(limit=3)
        if recent:
            context += "\nRecent Sessions:\n"
            for s in recent:
                tracks = s.get("tracks_covered", "[]")
                acc = f"{s['overall_accuracy']:.0%}" if s.get("overall_accuracy") else "N/A"
                context += f"- {s['session_date'][:10]}: {tracks}, accuracy {acc}, {s['exercises_completed']} exercises\n"

        # Add review queue
        due = self.db.get_due_reviews(limit=5)
        if due:
            context += "\nItems Due for Review:\n"
            for r in due:
                context += f"- {r['item_type']}: {r['item_id']} (reviewed {r['review_count']}x)\n"

        return context

    # ── Exercise Completion Tracking ──────────────────────────────────

    def complete_exercise(self, chord_name: str, success: bool,
                          track: str = "", milestone_id: str = ""):
        """
        Called after each exercise completes. Updates:
        - Milestone attempt/success counts
        - Spaced repetition schedule for the chord
        - Checks if milestone should advance
        """
        self._session_exercises += 1
        if success:
            self._session_successes += 1

        # Update milestone progress if we know which one
        if track and milestone_id:
            self.db.record_milestone_attempt(track, milestone_id, success)

            # Check if milestone should advance
            meta = self._get_milestone_meta(track, milestone_id)
            if meta:
                ms_state = None
                for m in self.db.get_curriculum_state(track):
                    if m["milestone_id"] == milestone_id:
                        ms_state = m
                        break

                if ms_state and ms_state["status"] == "active":
                    min_att = meta.get("min_attempts_to_advance", 5)
                    min_acc = meta.get("min_accuracy_to_advance", 0.80)
                    attempts = ms_state["attempts"]
                    accuracy = ms_state["successes"] / attempts if attempts > 0 else 0

                    if attempts >= min_att and accuracy >= min_acc:
                        self.db.advance_milestone(track, milestone_id)
                        print(f"CurriculumService: 🎉 Milestone advanced! {track}/{milestone_id} "
                              f"({attempts} attempts, {accuracy:.0%} accuracy)")
            
            # Notify UI that progress (attempts/accuracy) has changed, even if milestone didn't advance
            self.curriculumChanged.emit()

        # Schedule spaced repetition for this chord
        if chord_name:
            quality = 5 if success else 1  # Simple mapping for now
            self.db.schedule_review("chord", chord_name, quality)

    def finish_session(self):
        """Record the completed session in history."""
        if self._session_start_time > 0:
            elapsed = int(time.time() - self._session_start_time)
            accuracy = (self._session_successes / self._session_exercises
                       if self._session_exercises > 0 else 0.0)
            self.db.record_session(
                self._session_tracks,
                self._session_milestones,
                self._session_exercises,
                elapsed,
                accuracy
            )
            print(f"CurriculumService: Session recorded — {self._session_exercises} exercises, "
                  f"{accuracy:.0%} accuracy, {elapsed}s")
            self._session_start_time = 0.0

    # ── QML Properties ────────────────────────────────────────────────

    # Must explicitly type as QVariantList for QML Repeater to work correctly
    @Property("QVariantList", notify=curriculumChanged)
    def activeMilestones(self) -> list:
        """Active milestones with metadata for QML display."""
        active = self.db.get_active_milestones()
        result = []
        for ms in active:
            meta = self._get_milestone_meta(ms["track_name"], ms["milestone_id"])
            attempts = int(ms.get("attempts", 0) or 0)
            successes = int(ms.get("successes", 0) or 0)
            
            # Calculate a normalized progress percentage (0.0 to 1.0)
            progress = 0.0
            if meta:
                min_att = int(meta.get("min_attempts_to_advance", 5))
                min_acc = float(meta.get("min_accuracy_to_advance", 0.80))
                
                # Progress is a mix of doing enough attempts and hitting the accuracy mark
                att_progress = min(1.0, attempts / min_att) if min_att > 0 else 1.0
                acc_progress = 0.0
                if attempts > 0:
                    current_acc = successes / attempts
                    acc_progress = min(1.0, current_acc / min_acc) if min_acc > 0 else 1.0
                
                # Combine them, weighting completion more if accuracy is lagging
                progress = float((att_progress * 0.4) + (acc_progress * 0.6))
            
            result.append({
                "track": ms["track_name"],
                "milestoneId": ms["milestone_id"],
                "title": meta.get("title", ms["milestone_id"]) if meta else ms["milestone_id"],
                "attempts": attempts,
                "successes": successes,
                "progress": progress,
                "status": ms["status"],
            })
        return result

    @Property(int, notify=curriculumChanged)
    def reviewQueueCount(self) -> int:
        return len(self.db.get_due_reviews(limit=100))

    @Property("QVariantList", notify=curriculumChanged)
    def recentSessions(self) -> list:
        return self.db.get_recent_sessions(limit=5)

    @Property("QVariantMap", notify=sessionPlanReady)
    def currentSessionPlan(self) -> dict:
        return self._session_plan

    @Slot()
    def refreshCurriculum(self):
        """Force a refresh of curriculum state (e.g. after settings reset)."""
        self.db.initialize_curriculum(self._tracks_data)
        self.curriculumChanged.emit()
