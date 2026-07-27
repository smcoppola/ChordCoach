# Phase 5 — Library Management UX

**Size: M. Dependencies: Phase 1 (`source_hash`, `source_copy`, `import_file`). May be executed before Phases 3/4 for earlier visible wins. Read `00-README.md` first.**

## Mission

Give the app a real library surface: a dedicated `LibraryView` screen with drag-and-drop import, rename/delete, duplicate cleanup, and per-song mastery at a glance. Today "the library" is a popup buried in a 1,397-line dashboard file.

## Current state (verified facts — grep for symbols, line numbers are hints)

**Navigation:** `src/ui/main.qml` is a fixed 3-zone layout (`LeftSidebar` + `CenterWorkspace` + settings popup). `src/ui/CenterWorkspace.qml` holds the app's only `StackView` (~:9-16) with exactly three destinations: `DashboardView` (initial), `ChordTrainerView`, `CircleOfFifthsView` (auto-routed by a circle-of-fifths mode change handler). Song selection is a **global signal relay**: `Music21Service.songRequested(songId)` → handler in `CenterWorkspace.qml` (~:45) → `chordTrainer.start_song(songId)` + `stack.replace(trainerViewComponent)`.

**DashboardView.qml (1,397 lines)** contains: 4 action cards (Daily Lesson, Quick Review, Specific Drill, Free Play); the `songPicker` Popup (~:719) — breadcrumb catalog browser over `music21Service.get_catalog_level(path)` (Difficulty → Style → Composer → Song), search via `search_catalog` (~:280 in the service), Recent Songs rail (`get_recent_songs`), IMPORT button + `FileDialog` (~:706); the `difficultyPicker` Popup (~:563) for `user::` songs (Original + Levels 4–1, hand-mode chips calling `set_user_song_hand_mode`); `requestSongWithDifficulty(songId)` (~:32) branches catalog-direct vs user-song-dialog.

**Service facts (`src/logic/services/music21_service.py`):**
- Imported songs live in `_user_songs` (scanned at startup by `_load_user_songs` ~:631 from `<user_data>/database/user_songs/*.json`), surfaced as a virtual **"My Songs"** category injected at catalog root (`get_catalog_level` ~:206, ~:243) and merged into search + recents.
- **`userSongsChanged` is emitted (~:676) but no QML listens to it** — the picker model only refreshes on popup reopen.
- No rename, no delete, no metadata editing exists anywhere.
- Phase 1 added: `source_hash` per record, source copies under `user_songs/sources/`, `import_file` slot (multi-format), `importDuplicate` signal.
- Import worker rejects concurrent imports (~:659) — queued sequential imports are the caller's job.

**Mastery data:** `songs` table in `src/logic/services/database_manager.py` (`filepath, title, last_played, play_count, mastery_score`), written by `record_song_play` — populated from Phase 4 onward (shows 0/absent before that; the UI must tolerate missing rows).

**Dev-mode quirk:** user data splits between `project_root/database/` and `%LOCALAPPDATA%\ChordCoach\database\` (bootstrap sets `user_data_path = project_root` in dev, but the service calls `get_user_data_dir()` directly for user songs/recents). Don't fix the split here; **do** add a startup log line stating which user-songs directory is active.

## Tasks (in order)

### 1. Python slots (`music21_service.py`)

- `@Slot(result="QVariantList") get_user_songs()` — full entries: `id, title, artist, level, key, imported_at, source_type, hand_mode, practice_mode, mastery (0 if unknown), last_played (nullable)`. Mastery joined via a new `DatabaseManager.get_song_masteries(ids: list) -> dict` (single query, `filepath IN (...)`).
- `@Slot(str, str, str) rename_user_song(song_id, title, artist)` — update the JSON record (reuse the save helper from the hand-mode path) and the in-memory `_user_songs` entry; emit `userSongsChanged`.
- `@Slot(str) delete_user_song(song_id)` — remove the JSON file; remove the `sources/` copy **only if no other record shares its `source_hash`**; drop from `_user_songs`; emit `userSongsChanged`. Refuse (return/emit an error string) if the song is currently loaded in an active practice session — check via the ChordTrainer reference AppState can provide, or expose a `currentSongId` property on ChordTrainer.
- `@Slot(result="QVariantList") find_duplicates()` — group `_user_songs` records sharing a `source_hash`; return groups for a one-time cleanup flow (per-import dedupe already blocks new ones).

### 2. New `src/ui/LibraryView.qml` — fourth StackView destination

- Route: a new "Library" entry in `LeftSidebar` and a Library tile/button on the dashboard → `stack.replace(libraryComponent)` in `CenterWorkspace.qml`, same pattern as the trainer route. Back button → dashboard.
- **Tabs:** "My Songs" (model: `get_user_songs()`, refreshed on `userSongsChanged` — finally consuming that signal) and "Corpus" (reuse `get_catalog_level`/`search_catalog` browsing; read-only).
- **Song cards (My Songs):** title, artist, grade badge (reuse the existing grade-color helper pattern from DashboardView), key, source-type badge (MIDI/XML), mastery bar (0–100, hidden if no data), last played. Actions: **Play** (emit through the existing `requestSongWithDifficulty`/`songRequested` flow — do not invent a new route), **difficulty** (existing `::L<n>` mechanism / difficultyPicker), **hand mode** (existing slots), **Rename** (inline dialog → `rename_user_song`), **Delete** (confirm dialog → `delete_user_song`).
- **Drag-and-drop:** full-view `DropArea` overlay ("Drop MIDI or MusicXML files") accepting file URLs; on drop, iterate URLs → `import_file(url)` sequentially (wait for `importSucceeded`/`importFailed`/`importDuplicate` between files — the worker is single-flight). Show a queued-import strip: filename, spinner, ✓/✗/duplicate result per file.
- **Duplicates cleanup:** a toolbar action visible when `find_duplicates()` is non-empty → list groups → user picks which copies to delete.
- **Search box** over My Songs (client-side filter) and Corpus (`search_catalog`).

### 3. Keep the quick picker

`songPicker` popup in DashboardView stays as the fast in-flow chooser. Do **not** grow DashboardView.qml further; the only dashboard change is the Library tile/entry. If any picker code is convenient to share (e.g. the song-row delegate), factor it into `src/ui/components/` rather than duplicating.

### 4. Startup logging

One log line at `Music21Service` init stating the resolved user-songs directory (dev-split diagnosis aid).

## Tests (write first)

Library logic is mostly Qt/QML; keep Python-side logic testable:
- `tests/test_library_ops.py` — with a temp user-songs dir: `rename_user_song` rewrites JSON + preserves other fields; `delete_user_song` removes record, keeps shared source copy while another record references the hash, removes it when last reference goes; `find_duplicates` groups correctly; `get_song_masteries` returns `{}` gracefully with no DB rows. (Instantiate the service pointing at the temp dir, or factor these into module-level functions taking the dir + records explicitly if service construction is Qt-heavy.)

## Acceptance gates

**Automated:** tests pass.

**Human (run `python src/app.py`):**
1. Library entry visible in sidebar + dashboard; opens LibraryView; Back returns to dashboard.
2. Drag two files (one `.mid`, one `.musicxml`) from Explorer onto the view → both import with progress strip; cards appear **without reopening the view** (`userSongsChanged` wiring).
3. Drop an already-imported file → strip shows "duplicate" with Open action; no new card.
4. Rename a song → card updates; song still plays; difficulty levels still work (`::L<n>` on the same id).
5. Delete a song → confirm dialog → card gone, JSON gone; a song sharing the same source (if created via re-import pre-Phase-1) keeps its source file.
6. Attempt to delete the currently-practicing song → refused with a message.
7. Play from a card → routes into the trainer exactly like the picker does (difficulty dialog for user songs).
8. Mastery bar shows values after Phase 4 completions (or hidden cleanly if Phase 4 not yet landed).

## Do NOT touch

- The song id format (`user::<slug>-<ts>` and `::L<n>` suffix) — renames change `title`, never the id.
- `songRequested` relay and `requestSongWithDifficulty` flow.
- Catalog machinery, corpus download overlay, recents.
- The import pipeline itself (consumption only).

## Regression watch

songPicker popup still fully functional (browse/search/recents/import button); difficulty + hand-mode pickers; startup scan of existing user songs; frozen-build path resolution (`get_user_data_dir`) untouched.
