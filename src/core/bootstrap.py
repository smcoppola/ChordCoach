"""
Core Bootstrapping module for ChordCoach Companion.
Handles environment variables, native paths, and PyInstaller resolution 
before Qt and other heavy libraries are initialized.
"""
import sys
import os
import io
from pathlib import Path
from datetime import datetime


class _TeeStream:
    """Writes to both a file and the original stream (e.g. console).
    Ensures that all print() output is captured to a log file even when
    the application is running as a frozen macOS .app bundle with no terminal.
    """
    def __init__(self, file_stream, original_stream):
        self._file = file_stream
        self._original = original_stream

    def write(self, data):
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:
            pass
        try:
            if self._original and not self._original.closed:
                self._original.write(data)
        except Exception:
            pass

    def flush(self):
        try:
            self._file.flush()
        except Exception:
            pass
        try:
            if self._original and not self._original.closed:
                self._original.flush()
        except Exception:
            pass

    # Some libraries check for encoding / fileno
    @property
    def encoding(self):
        return getattr(self._original, 'encoding', 'utf-8')

    def fileno(self):
        return self._file.fileno()

    def isatty(self):
        return False


def setup_logging(user_data_path: Path):
    """Redirect stdout and stderr to a persistent log file.
    
    The log file is written to ``<user_data_path>/logs/chordcoach.log``.
    Previous log contents are preserved with a session separator so
    multiple launches can be reviewed in a single file.  The file is
    capped at ~2 MB by truncating old content on startup.
    """
    log_dir = user_data_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "chordcoach.log"

    # Cap the log file at ~2 MB to prevent unbounded growth
    try:
        if log_file.exists() and log_file.stat().st_size > 2 * 1024 * 1024:
            # Keep only the last ~500 KB
            content = log_file.read_text(encoding="utf-8", errors="replace")
            log_file.write_text(content[-500_000:], encoding="utf-8")
    except Exception:
        pass

    try:
        fh = open(log_file, "a", encoding="utf-8", errors="replace")
        fh.write(f"\n{'='*60}\n")
        fh.write(f"  ChordCoach Session — {datetime.now().isoformat()}\n")
        fh.write(f"  Platform: {sys.platform}  Frozen: {getattr(sys, 'frozen', False)}\n")
        fh.write(f"  Python: {sys.version}\n")
        fh.write(f"{'='*60}\n\n")

        sys.stdout = _TeeStream(fh, sys.stdout)  # type: ignore[assignment]
        sys.stderr = _TeeStream(fh, sys.stderr)  # type: ignore[assignment]
        print(f"Logging initialised → {log_file}")
    except Exception as e:
        # If we can't open the log, at least don't crash
        print(f"Warning: Could not set up file logging: {e}")

def _native_lib_name(base: str) -> str:
    """Return the platform-specific shared library filename."""
    if sys.platform == "win32":
        return f"{base}.dll"
    elif sys.platform == "darwin":
        return f"lib{base}.dylib"
    else:  # Linux / other POSIX
        return f"lib{base}.so"

def _build_subdir() -> str:
    """CMake multi-config generators (MSVC) put binaries in Release/; single-config (Make/Ninja) don't."""
    return "Release" if sys.platform == "win32" else ""

def get_user_data_dir() -> Path:
    """Return a platform-specific writable directory for application data."""
    if sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~\\AppData\\Local"))) / "ChordCoach"
    elif sys.platform == "darwin":
        path = Path(os.path.expanduser("~/Library/Application Support/ChordCoach"))
    else:  # Linux / other POSIX
        path = Path(os.path.expanduser("~/.local/share/chordcoach"))
    
    path.mkdir(parents=True, exist_ok=True)
    return path

def setup_env() -> tuple[Path, Path, Path, bool]:
    """
    Initializes the environment. Must be called before Qt imports.
    Returns:
        tuple: (project_root_path, hw_bin_path, user_data_path, is_frozen)
    """
    is_frozen = getattr(sys, 'frozen', False)
    
    # --- Frozen vs Dev Environment ---
    if is_frozen:
        bundle_dir = Path(sys._MEIPASS) # type: ignore
        project_root = bundle_dir
        hw_bin_path = bundle_dir
        native_lib_dir = bundle_dir
        user_data_path = get_user_data_dir()
        
        # Ensure SSL Certificates are loaded correctly for requests/websockets inside frozen bundle
        try:
            import certifi
            os.environ['SSL_CERT_FILE'] = certifi.where()
            os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
        except ImportError:
            pass
        # Explicitly point to QtWebEngineProcess for some PySide6 environments
        if sys.platform == "win32":
            os.environ["QTWEBENGINEPROCESS_PATH"] = str(bundle_dir / "PySide6" / "QtWebEngineProcess.exe")
            
        # Monkey-patch music21 to find its internal paths correctly in frozen _internal structure
        try:
            import music21.common.pathTools
            from pathlib import Path
            def getSourceFilePath_fixed():
                # sys._MEIPASS is the root or _internal dir in PyInstaller 6+ 
                return Path(sys._MEIPASS) / "music21"
            music21.common.pathTools.getSourceFilePath = getSourceFilePath_fixed
            print(f"bootstrap: Applied music21.common.pathTools monkey-patch for {Path(sys._MEIPASS) / 'music21'}")
        except Exception as e:
            print(f"bootstrap: Failed to patch music21: {e}")
        elif sys.platform == "darwin":
            # PyInstaller heavily modifies the structure of a macOS .app BUNDLE
            meipass_path = Path(getattr(sys, '_MEIPASS', bundle_dir))
            
            # Try typical PyInstaller fallback locations for macOS
            possible_paths = [
                meipass_path / "PySide6" / "Qt" / "lib" / "QtWebEngineCore.framework" / "Helpers" / "QtWebEngineProcess.app" / "Contents" / "MacOS" / "QtWebEngineProcess",
                meipass_path / "PySide6" / "QtWebEngineProcess",
                meipass_path.parent / "Frameworks" / "QtWebEngineCore.framework" / "Helpers" / "QtWebEngineProcess.app" / "Contents" / "MacOS" / "QtWebEngineProcess"
            ]
            
            webengine = next((p for p in possible_paths if p.exists()), possible_paths[0])
            if webengine.exists():
                os.environ["QTWEBENGINEPROCESS_PATH"] = str(webengine)
    else:
        # We are running from source (src/core/bootstrap.py -> parent -> parent)
        project_root = Path(__file__).parent.parent.parent
        hw_bin_path = project_root / "build" / "src" / "hardware" / _build_subdir()
        native_lib_dir = None
        user_data_path = project_root

    # Load env vars manually for local testing
    # In frozen mode, we look for .env in the user_data_path first
    env_file = user_data_path / ".env"
    if not env_file.exists() and is_frozen:
        # Fallback to bundle root for initial defaults if user hasn't set anything
        env_file = project_root / ".env"

    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(env_file, "r", encoding="utf-16") as f:
                lines = f.readlines()
                
        for line in lines:
            if line.strip().startswith("GOOGLE_API_KEY="):
                os.environ["GOOGLE_API_KEY"] = line.strip().split("=", 1)[1]

    # Add local paths for imports so we can 'import chordcoach_hw' and 'import logic.services...'
    sys.path.append(str(hw_bin_path))
    sys.path.append(str(project_root / "src"))

    # Add native library search paths (platform-specific)
    if sys.platform == "win32":
        if native_lib_dir:
            os.add_dll_directory(str(native_lib_dir))
        else:
            dll_paths = [
                project_root / "build" / "_deps" / "rtmidi-build" / _build_subdir(),
                project_root / "build" / "_deps" / "portaudio-build" / _build_subdir()
            ]
            for p in dll_paths:
                if p.exists():
                    os.add_dll_directory(str(p))
    else:
        # macOS / Linux: add library paths to environment so the dynamic linker can find them
        env_var = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
        if native_lib_dir:
            extra_paths = [str(native_lib_dir)]
        else:
            extra_paths = [
                str(project_root / "build" / "_deps" / "rtmidi-build" / _build_subdir()),
                str(project_root / "build" / "_deps" / "portaudio-build" / _build_subdir())
            ]
        existing = os.environ.get(env_var, "")
        os.environ[env_var] = os.pathsep.join(extra_paths + ([existing] if existing else []))

    # Use the Basic style to allow full customization of UI components (removes native warnings)
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"

    return project_root, hw_bin_path, user_data_path, is_frozen
