import re

target_file = 'src/logic/services/chord_trainer.py'
with open(target_file, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. ADD ENUM
enum_def = """class LessonState(Enum):
    IDLE = auto()
    LOADING = auto()
    AWAITING_EXERCISE = auto()
    AI_SPEAKING = auto()
    USER_PLAYING = auto()

"""
text = text.replace('class ChordTrainerService(QObject):', enum_def + 'class ChordTrainerService(QObject):')

# Add to imports
text = text.replace('from datetime import datetime', 'from datetime import datetime\nfrom enum import Enum, auto')

# 2. Add self._state = LessonState.IDLE
text = re.sub(r'self._is_active = False\s*self._current_track = ""', 
              'self._state = LessonState.IDLE\n        self._current_track = ""', text)

# Remove all those self._x booleans in init
text = re.sub(r'\s*self._is_lesson_mode = False\s*self._lesson_playlist = \[\]', 
              '\n        self._is_lesson_mode = False\n        self._lesson_playlist = []', text)
text = re.sub(r'\s*self._is_lesson_complete = False\s*self._is_waiting_to_begin = False\s*self._is_loading = False\s*self._loading_status_text = ""\s*self._is_paused_for_speech = False\s*self._require_key_release_before_eval = False\s*self._waiting_for_ai = False\s*self._is_requesting_exercise = False',
              '\n        self._is_lesson_complete = False\n        self._loading_status_text = ""\n        self._require_key_release_before_eval = False', text)

# 3. Add transition helper
helper_func = """
    def change_state(self, new_state: LessonState):
        if hasattr(self, '_state') and getattr(self, '_state') == new_state:
            return
            
        old_active = self.isActive() if hasattr(self, '_state') else False
        old_loading = self.isLoading() if hasattr(self, '_state') else False
        
        self._state = new_state
        print(f"ChordTrainer: Transitioned to {new_state}")
        
        if old_active != self.isActive():
            self.activeChanged.emit(self.isActive())
        self.lessonStateChanged.emit()
        if old_loading != self.isLoading():
            self.loadingStatusChanged.emit()
            
"""
text = re.sub(r'    def __init__\(self.*?\n(    @Property)', helper_func + r'\1', text, flags=re.DOTALL|re.MULTILINE)

# 4. Update Properties
text = re.sub(r'        return self\._is_active', '        return getattr(self, "_state", LessonState.IDLE) != LessonState.IDLE', text)
text = re.sub(r'        return self\._is_paused_for_speech', '        return getattr(self, "_state", LessonState.IDLE) == LessonState.AI_SPEAKING', text)
text = re.sub(r'        return self\._is_loading', '        return getattr(self, "_state", LessonState.IDLE) == LessonState.LOADING', text)
text = re.sub(r'        return self\._waiting_for_ai', '        return getattr(self, "_state", LessonState.IDLE) == LessonState.AWAITING_EXERCISE', text)
text = re.sub(r'        return self\._is_waiting_to_begin', '        return False  # Deprecated in favor of state', text) 

# Write back
with open(target_file, 'w', encoding='utf-8') as f:
    f.write(text)

print("Refactored basic state definitions.")
