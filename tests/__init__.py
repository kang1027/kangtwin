"""테스트가 진짜 Obsidian 볼트나 상태 폴더를 건드리지 않게 임시 경로로 돌린다.

`python3 -m unittest discover -s tests -t .`로 실행해야 이 파일이 먼저 실행된다.
"""
import os
import tempfile

_ROOT = tempfile.mkdtemp(prefix="kangtwin-test-")
os.environ["KANGTWIN_CONFIG"] = os.path.join(_ROOT, "no-config.json")
os.environ["KANGTWIN_VAULT"] = os.path.join(_ROOT, "vault")
os.environ.setdefault("KANGTWIN_STATE", os.path.join(_ROOT, "state"))
os.environ["KANGTWIN_TOKEN_FILE"] = os.path.join(_ROOT, "no-token")
os.environ["KANGTWIN_DATAGOKR_KEY_FILE"] = os.path.join(_ROOT, "no-datagokr-key")
