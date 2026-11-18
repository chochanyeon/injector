"""Ask the desktop running Injector for a project directory."""
from pathlib import Path
import subprocess
import sys

from .registry import RegistryError


MACOS_SCRIPT = """
on run argv
    try
        set initialFolder to (POSIX file (item 1 of argv)) as alias
        set selectedFolder to choose folder with prompt "Injector에서 사용할 폴더를 선택하세요." default location initialFolder
        return POSIX path of selectedFolder
    on error messageText number errorNumber
        if errorNumber is -128 then return ""
        error messageText number errorNumber
    end try
end run
"""


def choose_project_folder(initial):
    try:
        start = Path(initial).resolve()
        if not start.is_dir():
            start = Path.home()
    except (OSError, ValueError, RuntimeError):
        start = Path.home()

    options = {"capture_output": True, "stdin": subprocess.DEVNULL, "timeout": 300}
    if sys.platform == "win32":
        command = [sys.executable, "-I", str(Path(__file__).with_name("_windows_folder_picker.py")), str(start)]
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    elif sys.platform == "darwin":
        command = ["/usr/bin/osascript", "-e", MACOS_SCRIPT, str(start)]
    else:
        raise RegistryError("폴더 선택은 Windows와 macOS에서 지원합니다. 프로젝트 경로를 직접 입력하세요.")

    try:
        result = subprocess.run(command, **options)
        if result.returncode:
            raise RegistryError("Injector가 실행 중인 컴퓨터에서 폴더 선택 창을 열 수 없습니다. 경로를 직접 입력하세요.")
        return result.stdout.decode("utf-8").removesuffix("\r\n").removesuffix("\n") or None
    except subprocess.TimeoutExpired as error:
        raise RegistryError("폴더 선택 시간이 초과되었습니다. 다시 선택하거나 경로를 직접 입력하세요.") from error
    except (OSError, UnicodeError) as error:
        raise RegistryError("폴더를 선택할 수 없습니다. 프로젝트 경로를 직접 입력하세요.") from error
