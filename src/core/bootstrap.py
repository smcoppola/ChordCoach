"""
Core Bootstrapping module for ChordCoach Companion.
Handles environment variables, native paths, and PyInstaller resolution 
before Qt and other heavy libraries are initialized.
"""
import sys
import os
from pathlib import Path

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

def _get_user_data_dir() -> Path:
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
        user_data_path = _get_user_data_dir()
        # Explicitly point to QtWebEngineProcess for some PySide6 environments
        if sys.platform == "win32":
            os.environ["QTWEBENGINEPROCESS_PATH"] = str(bundle_dir / "PySide6" / "QtWebEngineProcess.exe")
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
