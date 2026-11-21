"""One fresh native file query for the complete original Windows clock.

Directory-index metadata can lag writes through another hardlink, so it must
never authorize a warm response. FileStatBasicByNameInfo reads each file's real
ChangeTime and identity directly. Unsupported paths/runtimes retain the original
stat plus FILE_BASIC_INFO path; no metadata is memoized between calls.
https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getfileinformationbyname
"""
import os
import sys

_GET_INFO = None

if os.name == 'nt' and sys.version_info[:2] == (3, 12):
    import ctypes
    from ctypes import wintypes

    class _FileInfo(ctypes.Structure):
        _fields_ = [('FileId', ctypes.c_ulonglong), ('CreationTime', ctypes.c_longlong),
                    ('LastAccessTime', ctypes.c_longlong), ('LastWriteTime', ctypes.c_longlong),
                    ('ChangeTime', ctypes.c_longlong), ('AllocationSize', ctypes.c_longlong),
                    ('EndOfFile', ctypes.c_longlong), ('FileAttributes', wintypes.DWORD),
                    ('ReparseTag', wintypes.DWORD), ('NumberOfLinks', wintypes.DWORD),
                    ('DeviceType', wintypes.DWORD), ('DeviceCharacteristics', wintypes.DWORD),
                    ('Reserved', wintypes.DWORD), ('VolumeSerialNumber', ctypes.c_ulonglong),
                    ('FileId128', ctypes.c_ubyte * 16)]

    try:
        _DLL = ctypes.WinDLL('api-ms-win-core-file-l2-1-4', use_last_error=True)
        _GET_INFO = _DLL.GetFileInformationByName
        _GET_INFO.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        _GET_INFO.restype = wintypes.BOOL
    except (OSError, AttributeError):
        _GET_INFO = None


def file_record(path):
    if _GET_INFO is None or path.lower().endswith(('.exe', '.bat', '.cmd', '.com')):
        return None
    info = _FileInfo()
    if not _GET_INFO(path, 3, ctypes.byref(info), ctypes.sizeof(info)):
        return None
    # Symlink/reparse targets, directories and remote/non-disk devices use the
    # exact original path. Python 3.12's tested ordinary-file representation is
    # reproduced fully, including the 128-bit file ID and volume serial number.
    if info.FileAttributes & (0x400 | 0x10 | 0x40) or info.ReparseTag \
            or info.DeviceType != 7 or info.DeviceCharacteristics & 0x10:
        return None
    ns = lambda ticks: (ticks - 116444736000000000) * 100
    mode = 0o100444 if info.FileAttributes & 1 else 0o100666
    return (ns(info.LastWriteTime), ns(info.CreationTime), info.EndOfFile, info.ChangeTime,
            info.VolumeSerialNumber, int.from_bytes(bytes(info.FileId128), 'little'), mode)
