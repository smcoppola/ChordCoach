import re
import os

target_file = 'src/logic/services/chord_trainer.py'
with open(target_file, 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Replace remaining obvious property assignments with state
text = text.replace('self._is_loading = True\n', 'self._set_state(LessonState.LOADING)\n')
text = text.replace('self._is_active = False\n', 'self._set_state(LessonState.IDLE)\n')
text = text.replace('self._is_active = True\n', 'self._set_state(LessonState.USER_PLAYING)\n')
text = text.replace('self._waiting_for_ai = True\n', 'self._set_state(LessonState.AWAITING_EXERCISE)\n')
text = text.replace('self._is_paused_for_speech = True\n', 'self._set_state(LessonState.AI_SPEAKING)\n')
text = text.replace('self._is_paused_for_speech = False\n', 'self._set_state(LessonState.USER_PLAYING)\n')
text = text.replace('self._waiting_for_ai = False\n', '')
text = text.replace('self._is_loading = False\n', '')

# Remove redundant assignment lines that just got erased
text = re.sub(r'\n\s*\n', '\n\n', text)

# For _is_requesting_exercise, it is mostly a redundant lock since AWAITING_EXERCISE serves the same purpose
text = text.replace('self._is_requesting_exercise = False', '')
text = text.replace('self._is_requesting_exercise = True', '')
text = text.replace('self._is_waiting_to_begin = False', '')

# 2. Fix property getters. We want internal code to use the new Properties `self.isActive` instead of `self._is_active`
# Because `_is_active` doesn't exist anymore!
text = re.sub(r'self\._is_active\b', 'self.isActive', text)
text = re.sub(r'self\._is_loading\b', 'self.isLoading', text)
text = re.sub(r'self\._waiting_for_ai\b', 'self.isWaitingForAi', text)
text = re.sub(r'self\._is_paused_for_speech\b', 'self.isPausedForSpeech', text)
text = re.sub(r'self\._is_waiting_to_begin\b', 'self.isWaitingToBegin', text)
text = re.sub(r'self\._is_requesting_exercise\b', 'self.isWaitingForAi', text) # Map the lock directly to the state query

with open(target_file, 'w', encoding='utf-8') as f:
    f.write(text)

print("Refactor complete.")
