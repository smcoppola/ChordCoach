import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta

class DatabaseManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    start_time TIMESTAMP NOT NULL,
                    duration_sec INTEGER NOT NULL,
                    notes TEXT
                )
            ''')
            
            # Songs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    last_played TIMESTAMP,
                    play_count INTEGER DEFAULT 0,
                    mastery_score REAL DEFAULT 0.0
                )
            ''')
            
            # Chords table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chords (
                    name TEXT PRIMARY KEY,
                    last_played TIMESTAMP,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    avg_latency_ms REAL DEFAULT 0.0,
                    total_wrong_notes INTEGER DEFAULT 0,
                    simultaneous_successes INTEGER DEFAULT 0
                )
            ''')
            
            # Simple Migration: Add columns if they don't exist
            try:
                cursor.execute("ALTER TABLE chords ADD COLUMN total_wrong_notes INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass # Already exists
                
            try:
                cursor.execute("ALTER TABLE chords ADD COLUMN simultaneous_successes INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass # Already exists
        
            # Generation stats table for adaptive timeout
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS generation_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    model_name TEXT NOT NULL,
                    generation_time_ms REAL NOT NULL,
                    step_count INTEGER NOT NULL,
                    success INTEGER NOT NULL DEFAULT 1
                )
            ''')
            
            # Curriculum state — milestone progression per learning track
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS curriculum_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    track_name TEXT NOT NULL,
                    milestone_id TEXT NOT NULL,
                    milestone_order INTEGER NOT NULL,
                    status TEXT DEFAULT 'locked',
                    attempts INTEGER DEFAULT 0,
                    successes INTEGER DEFAULT 0,
                    unlocked_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    UNIQUE(track_name, milestone_id)
                )
            ''')
            
            # Spaced repetition — SM-2 style review scheduling
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS spaced_repetition (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_type TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    next_review TIMESTAMP NOT NULL,
                    interval_days REAL DEFAULT 1.0,
                    ease_factor REAL DEFAULT 2.5,
                    review_count INTEGER DEFAULT 0,
                    UNIQUE(item_type, item_id)
                )
            ''')
            
            # Session history — records what each lesson session covered
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS session_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_date TIMESTAMP NOT NULL,
                    tracks_covered TEXT,
                    milestones_worked TEXT,
                    exercises_completed INTEGER DEFAULT 0,
                    time_spent_seconds INTEGER DEFAULT 0,
                    overall_accuracy REAL DEFAULT 0.0
                )
            ''')
            
            # Learned Terms — tracks technical music terms that have been explained to the user
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS learned_terms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    term TEXT UNIQUE NOT NULL,
                    explanation TEXT,
                    learned_at TIMESTAMP NOT NULL
                )
            ''')
            
            conn.commit()

    def record_song_play(self, filepath: str, title: str, mastery_gained: float):
        """Records a song play, updating play count and mastery."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if song exists
            cursor.execute('SELECT id, play_count, mastery_score FROM songs WHERE filepath = ?', (filepath,))
            row = cursor.fetchone()
            
            if row:
                song_id, play_count, current_mastery = row
                new_play_count = play_count + 1
                new_mastery = min(100.0, current_mastery + mastery_gained)  # Cap mastery at 100
                
                cursor.execute('''
                    UPDATE songs 
                    SET last_played = ?, play_count = ?, mastery_score = ?
                    WHERE id = ?
                ''', (now, new_play_count, new_mastery, song_id))
            else:
                new_mastery = min(100.0, mastery_gained)
                cursor.execute('''
                    INSERT INTO songs (filepath, title, last_played, play_count, mastery_score)
                    VALUES (?, ?, ?, 1, ?)
                ''', (filepath, title, now, new_mastery))
            
            conn.commit()

    # ── Technical Terms ──────────────────────────────────────────────
    
    def record_learned_term(self, term: str, explanation: str = ""):
        """Records that the coach has explained a technical term to the user."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO learned_terms (term, explanation, learned_at)
                VALUES (?, ?, ?)
                ON CONFLICT(term) DO UPDATE SET
                    explanation=excluded.explanation,
                    learned_at=excluded.learned_at
            ''', (term, explanation, now))
            conn.commit()

    def get_learned_terms(self) -> list:
        """Returns all previously explained technical terms."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT term, explanation, learned_at 
                FROM learned_terms 
                ORDER BY learned_at DESC
            ''')
            return [{"term": row[0], "explanation": row[1], "learned_at": row[2]} for row in cursor.fetchall()]

    def get_learned_term_names(self) -> list:
        """Returns just the names of the terms already learned, useful for prompts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT term FROM learned_terms')
            return [row[0] for row in cursor.fetchall()]

    def record_chord_attempt(self, chord_name: str, success: bool, latency_ms: float = 0.0, 
                             wrong_notes: int = 0, is_simultaneous: bool = False):
        """Records a chord attempt, updating success/fail counts and average latency."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT success_count, fail_count, avg_latency_ms, total_wrong_notes, simultaneous_successes 
                FROM chords WHERE name = ?
            ''', (chord_name,))
            row = cursor.fetchone()
            
            if row:
                s_count, f_count, avg_lat, w_notes, sim_s = row
                new_s_count = s_count + (1 if success else 0)
                new_f_count = f_count + (0 if success else 1)
                new_w_notes = w_notes + wrong_notes
                new_sim_s = sim_s + (1 if (success and is_simultaneous) else 0)
                
                # Simple moving average for latency
                total_attempts = s_count + f_count
                if total_attempts > 0:
                   new_avg_lat = ((avg_lat * total_attempts) + latency_ms) / (total_attempts + 1)
                else:
                   new_avg_lat = latency_ms
    
                cursor.execute('''
                    UPDATE chords
                    SET last_played = ?, success_count = ?, fail_count = ?, 
                        avg_latency_ms = ?, total_wrong_notes = ?, simultaneous_successes = ?
                    WHERE name = ?
                ''', (now, new_s_count, new_f_count, new_avg_lat, new_w_notes, new_sim_s, chord_name))
            else:
                new_s_count = 1 if success else 0
                new_f_count = 0 if success else 1
                new_sim_s = 1 if (success and is_simultaneous) else 0
                cursor.execute('''
                    INSERT INTO chords (name, last_played, success_count, fail_count, 
                                       avg_latency_ms, total_wrong_notes, simultaneous_successes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (chord_name, now, new_s_count, new_f_count, latency_ms, wrong_notes, new_sim_s))
            
            conn.commit()

    def calculate_skill_decay(self, decay_hours: int = 48, decay_rate: float = 0.95):
        """
        Applies a decay factor to mastery scores and success counts for items 
        not played recently.
        Returns a list of decayed chords for the AI prompt.
        """
        cutoff_time = (datetime.now() - timedelta(hours=decay_hours)).isoformat()
        decayed_chords = []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Decay songs
            cursor.execute('''
                UPDATE songs
                SET mastery_score = mastery_score * ?
                WHERE last_played < ?
            ''', (decay_rate, cutoff_time))
            
            # Find chords to decay and return them for prompting
            cursor.execute('''
                SELECT name, success_count, last_played 
                FROM chords 
                WHERE last_played < ? AND success_count > 0
            ''', (cutoff_time,))
            
            stale_chords = cursor.fetchall()
            for name, s_count, last_played in stale_chords:
                 # Apply decay to success count (must remain integer)
                 new_s_count = int(s_count * decay_rate)
                 cursor.execute('''
                     UPDATE chords
                     SET success_count = ?
                     WHERE name = ?
                 ''', (new_s_count, name))
                 
                 decayed_chords.append({
                     "name": name,
                     "last_played": last_played,
                     "old_success_count": s_count,
                     "new_success_count": new_s_count
                 })
                 
            conn.commit()
            
        return decayed_chords

    def reset_all_stats(self):
        """Clear all chord statistics and curriculum state."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM chords;')
            cursor.execute('DELETE FROM curriculum_state;')
            cursor.execute('DELETE FROM spaced_repetition;')
            cursor.execute('DELETE FROM session_history;')
            conn.commit()

    def has_completed_onboarding(self) -> bool:
        """Returns True if the user has any chord attempt history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM chords")
            row = cursor.fetchone()
            return row[0] > 0

    def get_all_chord_stats(self):
        """Returns all chord statistics as a list of dictionaries for UI display."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM chords ORDER BY name ASC')
            return [dict(row) for row in cursor.fetchall()]

    def get_all_song_stats(self):
        """Returns all song statistics as a list of dictionaries for UI display."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM songs ORDER BY mastery_score DESC')
            return [dict(row) for row in cursor.fetchall()]

    def record_generation_stat(self, model_name: str, generation_time_ms: float, step_count: int, success: bool = True):
        """Records a lesson plan generation attempt with timing data."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO generation_stats (timestamp, model_name, generation_time_ms, step_count, success)
                VALUES (?, ?, ?, ?, ?)
            ''', (now, model_name, generation_time_ms, step_count, 1 if success else 0))
            conn.commit()

    def get_avg_generation_time(self, last_n: int = 10) -> float:
        """Returns the average generation time in ms for the last N successful generations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT AVG(generation_time_ms) FROM (
                    SELECT generation_time_ms FROM generation_stats 
                    WHERE success = 1 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                )
            ''', (last_n,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0.0

    def get_median_generation_time(self, last_n: int = 5) -> float:
        """Returns the median generation time in ms for the last N successful generations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT generation_time_ms FROM generation_stats 
                WHERE success = 1 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (last_n,))
            results = [row[0] for row in cursor.fetchall()]
            
            if not results:
                return 0.0
                
            sorted_times = sorted(results)
            n = len(sorted_times)
            mid = n // 2
            
            if n % 2 == 0:
                return (sorted_times[mid - 1] + sorted_times[mid]) / 2.0
            else:
                return sorted_times[mid]


    def get_coach_context(self):
        """Retrieves relevant data formatted for the Gemini AI system prompt."""
        context = "User Practice Context:\n"
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get top struggling chords
            cursor.execute('''
                SELECT name, success_count, fail_count 
                FROM chords 
                WHERE fail_count > 0
                ORDER BY (CAST(fail_count AS FLOAT) / (success_count + fail_count)) DESC
                LIMIT 5
            ''')
            struggling = cursor.fetchall()
            if struggling:
                context += "Struggling Chords:\n"
                for name, s, f in struggling:
                    context += f"- {name} (Success: {s}, Fail: {f})\n"
            
            # Get recently decayed chords
            decayed = self.calculate_skill_decay(decay_hours=48, decay_rate=0.90)
            if decayed:
                context += "\nDecayed Chords (Not practiced in 48+ hours):\n"
                for item in decayed:
                    context += f"- {item['name']} (Last played: {item['last_played']})\n"
                    
            # Calculate global success/failure ratio
            cursor.execute('SELECT SUM(success_count), SUM(fail_count) FROM chords')
            global_stats = cursor.fetchone()
            total_successes = global_stats[0] if global_stats[0] else 0
            total_failures = global_stats[1] if global_stats[1] else 0
            total_attempts = total_successes + total_failures
            
            if total_attempts > 0:
                ratio = total_successes / total_attempts
                context += f"\nGlobal Session Progress:\n- Total Lifetime Attempts: {total_attempts}\n- Overall Success Ratio: {ratio:.2f}\n"
            else:
                context += "\nGlobal Session Progress:\n- The user is a brand new beginner with 0 chord attempts. Start with the absolute basics.\n"
                    
        return context

    # ── Curriculum Engine Methods ────────────────────────────────────

    def initialize_curriculum(self, tracks_data: dict):
        """Populate curriculum_state from tracks JSON data. Idempotent — skips existing rows."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for track_name, milestones in tracks_data.items():
                for milestone in milestones:
                    mid = milestone["id"]
                    order = milestone["order"]
                    # First milestone in each track starts as 'active'
                    status = 'active' if order == 1 else 'locked'
                    try:
                        cursor.execute('''
                            INSERT INTO curriculum_state (track_name, milestone_id, milestone_order, status, unlocked_at)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (track_name, mid, order, status, now if status == 'active' else None))
                    except sqlite3.IntegrityError:
                        pass  # Already exists
            conn.commit()

    def get_curriculum_state(self, track_name: str | None = None) -> list:
        """Returns milestone states, optionally filtered by track."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if track_name:
                cursor.execute('''
                    SELECT * FROM curriculum_state
                    WHERE track_name = ?
                    ORDER BY milestone_order ASC
                ''', (track_name,))
            else:
                cursor.execute('SELECT * FROM curriculum_state ORDER BY track_name, milestone_order ASC')
            return [dict(row) for row in cursor.fetchall()]

    def get_active_milestones(self) -> list:
        """Returns all milestones with status 'active' across all tracks."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM curriculum_state
                WHERE status = 'active'
                ORDER BY track_name, milestone_order ASC
            ''')
            return [dict(row) for row in cursor.fetchall()]

    def record_milestone_attempt(self, track_name: str, milestone_id: str, success: bool):
        """Record an attempt on a milestone and update its counts."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE curriculum_state
                SET attempts = attempts + 1, successes = successes + ?
                WHERE track_name = ? AND milestone_id = ?
            ''', (1 if success else 0, track_name, milestone_id))
            conn.commit()

    def advance_milestone(self, track_name: str, milestone_id: str):
        """Mark a milestone as completed and unlock the next one in the same track."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Get the order of this milestone
            cursor.execute('''
                SELECT milestone_order FROM curriculum_state
                WHERE track_name = ? AND milestone_id = ?
            ''', (track_name, milestone_id))
            row = cursor.fetchone()
            if not row:
                return
            current_order = row[0]

            # Mark current as completed
            cursor.execute('''
                UPDATE curriculum_state
                SET status = 'completed', completed_at = ?
                WHERE track_name = ? AND milestone_id = ?
            ''', (now, track_name, milestone_id))

            # Unlock next milestone in the same track
            cursor.execute('''
                UPDATE curriculum_state
                SET status = 'active', unlocked_at = ?
                WHERE track_name = ? AND milestone_order = ? AND status = 'locked'
            ''', (now, track_name, current_order + 1))

            conn.commit()

    def schedule_review(self, item_type: str, item_id: str, quality: int):
        """
        SM-2 spaced repetition update.
        quality: 0-5 (0-2 = fail/repeat, 3 = hard, 4 = good, 5 = easy)
        """
        now = datetime.now()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT interval_days, ease_factor, review_count
                FROM spaced_repetition
                WHERE item_type = ? AND item_id = ?
            ''', (item_type, item_id))
            row = cursor.fetchone()

            if row:
                interval, ef, count = row
            else:
                interval, ef, count = 1.0, 2.5, 0

            # SM-2 algorithm
            if quality < 3:
                # Failed — reset interval
                interval = 1.0
            else:
                if count == 0:
                    interval = 1.0
                elif count == 1:
                    interval = 3.0
                else:
                    interval = interval * ef

                # Update ease factor
                ef = max(1.3, ef + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))

            # Cap the interval to prevent OverflowError in SQLite/Python dates (~10 years)
            interval = min(interval, 3650.0)
            
            next_review = (now + timedelta(days=interval)).isoformat()
            count += 1

            cursor.execute('''
                INSERT INTO spaced_repetition (item_type, item_id, next_review, interval_days, ease_factor, review_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_type, item_id) DO UPDATE SET
                    next_review = ?, interval_days = ?, ease_factor = ?, review_count = ?
            ''', (item_type, item_id, next_review, interval, ef, count,
                  next_review, interval, ef, count))
            conn.commit()

    def get_due_reviews(self, limit: int = 10) -> list:
        """Returns items due for spaced repetition review."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM spaced_repetition
                WHERE next_review <= ?
                ORDER BY next_review ASC
                LIMIT ?
            ''', (now, limit))
            return [dict(row) for row in cursor.fetchall()]

    def record_session(self, tracks: list, milestones: list,
                       exercises: int, time_sec: int, accuracy: float):
        """Record a completed lesson session."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO session_history
                (session_date, tracks_covered, milestones_worked, exercises_completed, time_spent_seconds, overall_accuracy)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (now, json.dumps(tracks), json.dumps(milestones), exercises, time_sec, accuracy))
            conn.commit()

    def get_recent_sessions(self, limit: int = 5) -> list:
        """Returns the most recent session history entries."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM session_history ORDER BY session_date DESC LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
