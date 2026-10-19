"""Atomic publication under Windows destination-handle contention."""
import ctypes
import errno
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from ctxcomp import io


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows sharing semantics')
def test_retries_real_destination_lock_without_partial_json(tmp_path, monkeypatch):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    path = tmp_path / 'progress.json'
    io.write_json(path, {'status': 'OLD'})
    # A reader permits read/write, but not deletion/replacement of its open file.
    handle = kernel.CreateFileW(str(path), 0x80000000, 0x1 | 0x2, None, 3, 0x80, None)
    assert handle != wintypes.HANDLE(-1).value, ctypes.get_last_error()
    rejected = threading.Event()
    original = io.os.replace
    errors = []

    def observe_replace(source, target):
        try:
            return original(source, target)
        except OSError as exc:
            errors.append(exc.winerror)
            rejected.set()
            raise

    monkeypatch.setattr(io.os, 'replace', observe_replace)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(io.write_json, path, {'status': 'NEW'})
        try:
            assert rejected.wait(3), 'Expected an actual Windows replacement refusal'
            assert io.read_json(path) == {'status': 'OLD'}
        finally:
            assert kernel.CloseHandle(handle)
        future.result(timeout=5)
    assert errors and set(errors) <= {5, 32, 33}
    assert io.read_json(path) == {'status': 'NEW'}
    assert not list(tmp_path.glob('.writing-*'))


def test_persistent_windows_conflict_is_bounded_and_preserves_old_file(tmp_path, monkeypatch):
    path = tmp_path / 'progress.json'
    io.write_json(path, {'status': 'OLD'})
    attempts = []

    def blocked(*args):
        attempts.append(args)
        error = PermissionError(errno.EACCES, 'Access denied')
        error.winerror = 5
        raise error

    monkeypatch.setattr(io.os, 'replace', blocked)
    with pytest.raises(PermissionError) as raised:
        io.write_json(path, {'status': 'NEW'})
    assert getattr(raised.value, 'code', None) == 'LOCAL_FILE_REPLACE_BLOCKED'
    assert 1 < len(attempts) <= 10
    assert raised.value.validation_details['attempts'] == len(attempts)
    assert raised.value.validation_details['path'] == str(path.resolve())
    assert io.read_json(path) == {'status': 'OLD'}
    assert not list(tmp_path.glob('.writing-*'))


@pytest.mark.parametrize('number', [errno.ENOSPC, errno.ENOENT, errno.EACCES])
def test_unrelated_os_errors_are_not_retried(tmp_path, monkeypatch, number):
    attempts = []
    error = OSError(number, 'Non-Windows-sharing failure')

    def fail(*args):
        attempts.append(args)
        raise error

    monkeypatch.setattr(io.os, 'replace', fail)
    with pytest.raises(OSError) as raised:
        io.write_json(tmp_path / 'progress.json', {'status': 'NEW'})
    assert raised.value is error
    assert len(attempts) == 1
    assert not list(tmp_path.glob('.writing-*'))
