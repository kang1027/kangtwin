"""상태 디렉터리의 JSON 파일과 프로세스 간 잠금."""
import contextlib
import fcntl
import json
import os
import tempfile
from typing import Any, Iterator

from . import config


class Busy(Exception):
    """같은 이름의 잠금을 다른 작업이 쥐고 있다."""


def _path(name: str) -> str:
    root = config.state_dir()
    root.mkdir(parents=True, exist_ok=True)
    return str(root / ("%s.json" % name))


def load(name: str, default: Any) -> Any:
    try:
        with open(_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def save(name: str, data: Any) -> None:
    path = _path(name)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".%s." % name)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@contextlib.contextmanager
def lock(name: str) -> Iterator[None]:
    locks = config.state_dir() / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    f = open(locks / ("%s.lock" % name), "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy(name) from None
        yield
    finally:
        f.close()
