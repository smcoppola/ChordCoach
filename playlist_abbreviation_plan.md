# Session Playlist Abbreviation Plan

This plan outlines the strategy to aggregate consecutive, similar exercises into high-level blocks in the sidebar playlist view to prevent it from becoming overly cluttered.

## Current Behavior
The `ChordTrainerService._update_lesson_blocks()` method groups exercises into a block only if they share the **exact same `exercise_name`** (e.g., "C Major").
Since the AI generates descriptive names for every distinct drill (e.g. "C Major", "F Major", "G Major"), consecutive exercises often spawn their own individual block rows, expanding the list line-for-line.

---

## Proposed Solution

### 1. `CurriculumService`
Add an accessor function to look up a milestone's user-facing title strictly:
```python
# src/logic/services/curriculum_service.py

def get_milestone_title(self, track: str, milestone_id: str) -> str:
    """Look up a milestone title locally loaded from resources."""
    if not track or not milestone_id:
        return ""
    meta = self._get_milestone_meta(track, milestone_id)
    return meta.get("title", "")
```

### 2. `ChordTrainerService`
Update grouping logic in `_update_lesson_blocks()` to aggregate based on **Milestone Title** or **Exercise Type**, rather than exact name:

```python
# src/logic/services/chord_trainer.py

def _update_lesson_blocks(self, exercise_data: dict):
    # Determine the displayed row label
    track = exercise_data.get("track", "")
    milestone_id = exercise_data.get("milestone_id", "")
    ex_type = exercise_data.get("exercise_type", "chord")
    
    group_title = ""
    if hasattr(self, 'curriculum') and self.curriculum and track and milestone_id:
        group_title = self.curriculum.get_milestone_title(track, milestone_id)
        
    if not group_title:
        # Fallback grouping (e.g. "Theory - Pentascale")
        group_title = f"{ex_type.capitalize()} Drills"

    if self._lesson_blocks and self._lesson_blocks[-1]["name"] == group_title:
        # Extend existing block holding different consecutive chords
        self._lesson_blocks[-1]["stepCount"] += 1
        self._lesson_blocks[-1]["endStep"] = self._lesson_progress
    else:
        # Create a new high-level grouped block
        self._lesson_blocks.append({
            "track": track,
            "name": group_title,  # Unified milestone/type label
            "type": ex_type,
            "stepCount": 1,
            "startStep": self._lesson_progress,
            "endStep": self._lesson_progress,
        })
```

---

## Verification
- **Functional Check**: Start a lesson mode with the AI. Ensure that if the AI spits out multiple standard chord drills within the same Milestone tracking set to target keys, the sidebar displays **one row** mentioning the milestone (e.g., "Major Triads") with the incremental count expanding smoothly (e.g., "5 drills").
- **UI Side**: `LeftSidebar.qml` already contains step-count highlighting algorithms (`lessonProgress > endStep` vs `lessonProgress >= startStep`), so expanding individual block range indexes will inherently keep the highlight tracking synced smoothly! No visual component refactoring overhead is required.
