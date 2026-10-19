"""Interruptible subprocess boundary; pause retains successful file receipts."""
import subprocess
import time
from pathlib import Path
from .common import read_json, utcnow, write_json


class PauseRequested(RuntimeError):
    pass


def run_interruptible(command, *, pause_file, stdout, cwd, process_record=None):
    from .workflow_runtime import stop_process
    pause_file = Path(pause_file)
    if pause_file.exists(): raise PauseRequested('Paused before starting a new computation')
    proc = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stdout,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process_record:
        write_json(process_record, {'pid': proc.pid, 'started_at': utcnow(), 'command': command})
    try:
        while proc.poll() is None:
            if pause_file.exists():
                stop_process(proc)
                proc.wait(timeout=20)
                raise PauseRequested('Active computation stopped; completed receipts retained')
            time.sleep(.1)
        if pause_file.exists(): raise PauseRequested('Pause requested at computation boundary')
        return proc.returncode
    except BaseException:
        if proc.poll() is None:
            stop_process(proc); proc.wait(timeout=20)
        raise


def mark_paused_attempts(folder):
    """Only after the owned DAG process tree has stopped; never overwrite a success."""
    folder = Path(folder)
    for path in (folder / 'attempts').glob('*/*/execution.json'):
        value = read_json(path)
        if value.get('status') == 'RUNNING':
            value.update(status='PAUSED', finished_at=utcnow(), resume_policy='RERUN_INCOMPLETE_BLOCK')
            write_json(path, value)
