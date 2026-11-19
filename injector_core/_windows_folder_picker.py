"""Run the Windows Common Item Dialog."""
import ctypes
from ctypes import wintypes
import sys
from uuid import UUID


def _check(result):
    if result < 0:
        raise ctypes.WinError(result)


def _call(interface, index, result_type, argument_types, *arguments):
    vtable = ctypes.cast(interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    method = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(vtable[index])
    return method(interface, *arguments)


def choose_path(start, kind):
    # https://learn.microsoft.com/windows/win32/shell/common-file-dialog
    ole = ctypes.windll.ole32
    shell = ctypes.windll.shell32
    file_open_dialog = UUID("dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7").bytes_le
    file_dialog_interface = UUID("42f85136-db7e-439c-85f1-e4075d135fc8").bytes_le
    shell_item_interface = UUID("43826d1e-e718-42ee-bc55-a1e261c37bfe").bytes_le
    pointer = ctypes.c_void_p
    hresult = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [pointer]
    ole.CoTaskMemFree.restype = None
    dialog, initial, selected, path = (pointer() for _ in range(4))
    _check(ole.CoInitializeEx(None, 2))  # COINIT_APARTMENTTHREADED
    try:
        _check(ole.CoCreateInstance(file_open_dialog, None, 1, file_dialog_interface, ctypes.byref(dialog)))
        flags = wintypes.DWORD()
        _check(_call(dialog, 10, hresult, [ctypes.POINTER(wintypes.DWORD)], ctypes.byref(flags)))  # GetOptions
        pick_folders, force_filesystem = 0x20, 0x40
        options = flags.value | force_filesystem
        if kind == "project":
            options |= pick_folders
        _check(_call(dialog, 9, hresult, [wintypes.DWORD], options))  # SetOptions
        shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, pointer, ctypes.c_char_p,
                                                       ctypes.POINTER(pointer)]
        _check(shell.SHCreateItemFromParsingName(start, None, shell_item_interface, ctypes.byref(initial)))
        _check(_call(dialog, 12, hresult, [pointer], initial))  # SetFolder
        title = "Injector — 폴더 선택" if kind == "project" else "Injector — registry.json 선택"
        _check(_call(dialog, 17, hresult, [wintypes.LPCWSTR], title))  # SetTitle
        if kind == "registry":
            _check(_call(dialog, 15, hresult, [wintypes.LPCWSTR], "registry.json"))  # SetFileName
        result = _call(dialog, 3, hresult, [wintypes.HWND], None)  # Show
        if result & 0xFFFFFFFF == 0x800704C7:  # HRESULT_FROM_WIN32(ERROR_CANCELLED)
            return None
        _check(result)
        _check(_call(dialog, 20, hresult, [ctypes.POINTER(pointer)], ctypes.byref(selected)))  # GetResult
        _check(_call(selected, 5, hresult, [ctypes.c_uint, ctypes.POINTER(pointer)], 0x80058000,
                     ctypes.byref(path)))  # GetDisplayName(SIGDN_FILESYSPATH)
        return ctypes.wstring_at(path)
    finally:
        if path:
            ole.CoTaskMemFree(path)
        for interface in (selected, initial, dialog):
            if interface:
                _call(interface, 2, wintypes.ULONG, [])  # IUnknown::Release
        ole.CoUninitialize()


if __name__ == "__main__":
    sys.stdout.buffer.write((choose_path(sys.argv[1], sys.argv[2]) or "").encode("utf-8"))
