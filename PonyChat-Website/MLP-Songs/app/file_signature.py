"""File cache identity with the actual Windows metadata change clock.

Python st_ctime is creation time on Windows, so it cannot revoke a warm cache
after an equal-size in-place write followed by restored mtime. FILE_BASIC_INFO
ChangeTime is required there. Failure raises: callers must not use weak keys.
"""
import os
from pathlib import Path

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [('CreationTime', ctypes.c_longlong), ('LastAccessTime', ctypes.c_longlong),
                    ('LastWriteTime', ctypes.c_longlong), ('ChangeTime', ctypes.c_longlong),
                    ('FileAttributes', wintypes.DWORD)]

    _KERNEL = ctypes.WinDLL('kernel32', use_last_error=True)
    _KERNEL.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _KERNEL.CreateFileW.restype = wintypes.HANDLE
    _KERNEL.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _KERNEL.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _KERNEL.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL.CloseHandle.restype = wintypes.BOOL


def windows_change_time(path):
    handle = _KERNEL.CreateFileW(str(Path(path).absolute()), 0x80, 0x7, None, 3, 0x02000000, None)
    if handle == ctypes.c_void_p(-1).value or handle is None:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = _FileBasicInfo()
        if not _KERNEL.GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(info.ChangeTime)
    finally:
        _KERNEL.CloseHandle(handle)


def signature(path, stat_result=None):
    stat = Path(path).stat() if stat_result is None else stat_result
    result = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    return result + (windows_change_time(path),) if os.name == 'nt' else result
