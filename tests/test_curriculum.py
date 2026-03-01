import unittest
import json
import sqlite3
import shutil
import tempfile
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# 1. Mock PySide6 BEFORE importing CurriculumService
class MockSignal:
    def __init__(self, *args, **kwargs): pass
    def emit(self, *args, **kwargs): pass
    def connect(self, slot): pass

def MockProperty(type_hint, notify=None):
    def decorator(func):
        # We need to preserve the function for the test to call it
        func._is_property = True
        return property(func)
    return decorator

def MockSlot(*args, **kwargs):
    def decorator(func): return func
    return decorator

mock_qt = MagicMock()
mock_qt.QtCore.QObject = MagicMock
mock_qt.QtCore.Signal = MockSignal
mock_qt.QtCore.Property = MockProperty
mock_qt.QtCore.Slot = MockSlot

sys.modules['PySide6'] = mock_qt
sys.modules['PySide6.QtCore'] = mock_qt.QtCore
sys.modules['PySide6.QtGui'] = mock_qt
sys.modules['PySide6.QtQml'] = mock_qt

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / "src"))

from logic.services.database_manager import DatabaseManager
from logic.services.curriculum_service import CurriculumService

class TestCurriculumService(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for tests
        self.test_dir = Path(tempfile.mkdtemp())
        self.db_path = self.test_dir / "test.db"
        
        # Initialize DatabaseManager with a real file
        self.db = DatabaseManager(self.db_path)
        
        # Create a mock curriculum_tracks.json
        self.resources_dir = self.test_dir / "resources"
        self.resources_dir.mkdir()
        self.tracks_file = self.resources_dir / "curriculum_tracks.json"
        self.sample_tracks = {
            "technique": [
                {
                    "id": "tech_1",
                    "title": "Tech 1",
                    "order": 1,
                    "exercise_types": ["chord"],
                    "target_keys": ["C"],
                    "target_chords": ["C Major"],
                    "min_attempts_to_advance": 2,
                    "min_accuracy_to_advance": 0.5
                },
                {
                    "id": "tech_2",
                    "title": "Tech 2",
                    "order": 2,
                    "exercise_types": ["chord"],
                    "target_keys": ["G"],
                    "target_chords": ["G Major"],
                    "min_attempts_to_advance": 2,
                    "min_accuracy_to_advance": 0.5
                }
            ],
            "theory": [
                {
                    "id": "theory_1",
                    "title": "Theory 1",
                    "order": 1,
                    "exercise_types": ["theory_concept"],
                    "target_keys": [],
                    "target_chords": [],
                    "min_attempts_to_advance": 1,
                    "min_accuracy_to_advance": 0.0
                }
            ]
        }
        with open(self.tracks_file, "w", encoding="utf-8") as f:
            json.dump(self.sample_tracks, f)

        # Initialize CurriculumService
        self.service = CurriculumService(self.db, self.resources_dir)

    def tearDown(self):
        # Force closure of any potential handles
        import gc
        del self.service
        del self.db
        gc.collect()
        
        # Small delay to ensure any file handles are released (Windows specific)
        import time
        time.sleep(0.1)
        # Remove temporary directory
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initial_load(self):
        """Test that track data is correctly loaded into the database."""
        state = self.db.get_curriculum_state()
        # Should have tech_1, tech_2, and theory_1 (3 milestones)
        self.assertEqual(len(state), 3)
        
        # Check that first milestones are active, others locked
        active = self.db.get_active_milestones()
        ids = [m["milestone_id"] for m in active]
        self.assertIn("tech_1", ids)
        self.assertIn("theory_1", ids)
        self.assertNotIn("tech_2", ids)

    def test_session_planning(self):
        """Test that a session plan is correctly generated."""
        plan = self.service.plan_session(available_minutes=10)
        
        self.assertIn("blocks", plan)
        self.assertTrue(len(plan["blocks"]) >= 2)
        
        # Verify block content
        block_ids = [b["milestone_id"] for b in plan["blocks"]]
        self.assertIn("tech_1", block_ids)
        self.assertIn("theory_1", block_ids)

    def test_milestone_advancement(self):
        """Test that a user can advance to the next milestone."""
        # Milestone tech_1 needs 2 attempts with 50% accuracy
        
        # 1st attempt: Failure
        self.service.complete_exercise("C Major", success=False, track="technique", milestone_id="tech_1")
        state = self.db.get_curriculum_state("technique")
        ms1 = next(m for m in state if m["milestone_id"] == "tech_1")
        self.assertEqual(ms1["status"], "active")
        self.assertEqual(ms1["attempts"], 1)

        # 2nd attempt: Success (Accuracy 50%, Attempts 2) -> Should advance
        self.service.complete_exercise("C Major", success=True, track="technique", milestone_id="tech_1")
        
        state = self.db.get_curriculum_state("technique")
        ms1 = next(m for m in state if m["milestone_id"] == "tech_1")
        ms2 = next(m for m in state if m["milestone_id"] == "tech_2")
        
        self.assertEqual(ms1["status"], "completed")
        self.assertEqual(ms2["status"], "active")

    def test_qml_properties(self):
        """Test QML-bound properties return expected data."""
        # Before planning, activeMilestones should be empty
        self.assertEqual(len(self.service.activeMilestones), 0)
        
        # Plan session
        self.service.plan_session()
        
        # Now it should show tech_1 and theory_1
        active = self.service.activeMilestones
        self.assertEqual(len(active), 2)
        
        # Check data structure
        for ms in active:
            self.assertIn("track", ms)
            self.assertIn("progress", ms)
            self.assertIn("title", ms)

    def test_empty_curriculum_default(self):
        """Test that an empty curriculum provides a fallback session plan."""
        # Create an empty curriculum file
        with open(self.tracks_file, "w", encoding="utf-8") as f:
            json.dump({}, f)
        
        # Re-init service or clear DB
        self.db.reset_all_stats()
        service = CurriculumService(self.db, self.resources_dir)
        
        plan = service.plan_session()
        self.assertEqual(len(plan["blocks"]), 1)
        self.assertEqual(plan["blocks"][0]["milestone_id"], "rh_pentascale_c")

if __name__ == "__main__":
    unittest.main()
