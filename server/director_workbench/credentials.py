"""Encrypt local API keys with the current Windows user's DPAPI credentials."""

import base64
import ctypes
import os
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(value: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise ValueError("网页保存密钥目前需要 Windows；其他系统请使用环境变量")
    buffer = ctypes.create_string_buffer(value)
    source = _Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = _Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError("密钥加解密失败，请使用保存密钥的 Windows 用户运行服务")
    free = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free(target.data)


def seal_key(value: str) -> str:
    return base64.b64encode(_crypt(value.encode("utf-8"), decrypt=False)).decode("ascii")


def open_key(value: str) -> str:
    return _crypt(base64.b64decode(value, validate=True), decrypt=True).decode("utf-8")
