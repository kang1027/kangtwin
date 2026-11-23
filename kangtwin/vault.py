"""Me 노트에 줄 단위로만 쓰는 편집기. 덮어쓰기와 볼트 밖 쓰기를 막는다."""
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

TYPE_BY_FOLDER = {"facts": "fact", "projects": "project", "stories": "story", "claims": "claim"}
HEADING = re.compile(r"^(#{1,6})\s")


class VaultError(Exception):
    pass


def resolve(rel: str, root: Path) -> Path:
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\n" in rel or "\x00" in rel \
            or not rel.endswith(".md"):
        raise VaultError("Me 안의 .md 상대 경로만 됨: %r" % rel)
    base = root.resolve()
    target = (root / rel).resolve()
    if base not in target.parents:
        raise VaultError("Me 밖 경로: %r" % rel)
    return target


def _check_edit(edit: Dict[str, str]) -> None:
    heading, line = edit.get("heading", ""), edit.get("line", "")
    if not all(isinstance(v, str) for v in (edit.get("file"), heading, line)):
        raise VaultError("file, heading, line은 문자열이어야 함: %r" % (edit,))
    if not HEADING.match(heading) or "\n" in heading:
        raise VaultError("제목은 '#'으로 시작하는 한 줄이어야 함: %r" % heading)
    if not line.strip() or "\n" in line:
        raise VaultError("추가할 내용은 비어 있지 않은 한 줄이어야 함: %r" % line)


def _new_file(rel: str, today: datetime) -> str:
    kind = TYPE_BY_FOLDER.get(rel.split("/")[0], "note")
    return "---\ntype: %s\nstatus: active\nvisibility: private\nupdated: %s\n---\n\n# %s\n" % (
        kind, today.strftime("%Y-%m-%d"), Path(rel).stem)


def _bump_updated(text: str, today: datetime) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    head, rest = text[:end], text[end:]
    stamp = "updated: %s" % today.strftime("%Y-%m-%d")
    if re.search(r"^updated:.*$", head, flags=re.M):
        head = re.sub(r"^updated:.*$", stamp, head, count=1, flags=re.M)
    else:
        head = head + "\n" + stamp
    return head + rest


def _insert(text: str, heading: str, line: str) -> Optional[str]:
    """제목 구역 끝에 줄을 넣은 새 본문. 이미 있으면 None."""
    lines = text.split("\n")
    level = len(HEADING.match(heading).group(1))
    start = next((i for i, l in enumerate(lines) if l.strip() == heading.strip()), None)
    if start is None:
        body = text.rstrip("\n")
        return "%s\n\n%s\n\n%s\n" % (body, heading, line)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        m = HEADING.match(lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    section = lines[start + 1:end]
    if any(l.strip() == line.strip() for l in section):
        return None
    last = start
    for i in range(start + 1, end):
        if lines[i].strip():
            last = i
    if last == start:
        lines[start + 1:start + 1] = ["", line]
    else:
        lines.insert(last + 1, line)
    return "\n".join(lines)


def validate(edits: List[Dict[str, str]], root: Path) -> List[Path]:
    """쓰지 않고 형식과 경로만 검사한다. 하나라도 틀리면 VaultError."""
    paths = []
    for edit in edits:
        if not isinstance(edit, dict):
            raise VaultError("편집 항목은 객체여야 함: %r" % (edit,))
        _check_edit(edit)
        paths.append(resolve(edit.get("file", ""), root))
    return paths


def apply_edits(edits: List[Dict[str, str]], root: Path, backup_dir: Path,
                today: Optional[datetime] = None) -> List[str]:
    today = today or datetime.now()
    targets = list(zip(edits, validate(edits, root)))

    stamp = today.strftime("%Y%m%d-%H%M%S")
    texts: Dict[Path, str] = {}
    originals: Dict[Path, Optional[str]] = {}
    for edit, path in targets:
        if path not in texts:
            original = path.read_text(encoding="utf-8") if path.exists() else None
            originals[path] = original
            texts[path] = original if original is not None else _new_file(edit["file"], today)
        new = _insert(texts[path], edit["heading"], edit["line"])
        if new is not None:
            texts[path] = new

    changed = []
    root_resolved = root.resolve()
    for path, text in texts.items():
        if text == originals[path]:
            continue
        rel = str(path.relative_to(root_resolved))
        if originals[path] is not None:
            backup = backup_dir / stamp / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_bump_updated(text, today), encoding="utf-8")
        changed.append(rel)
    return changed


def create_note(rel: str, text: str, root: Path) -> Path:
    """새 노트를 만든다. 이미 있으면 덮어쓰지 않고 VaultError."""
    path = resolve(rel, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as f:
            f.write(text)
    except FileExistsError:
        raise VaultError("이미 있는 노트: %r" % rel) from None
    return path


def append_log(path: Path, line: str, title: Optional[str] = None) -> None:
    if "\n" in line:
        line = " ".join(line.split("\n"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("---\ntype: log\nvisibility: private\n---\n\n# %s\n\n%s\n" % (title or path.stem, line),
                        encoding="utf-8")
        return
    body = path.read_text(encoding="utf-8")
    sep = "" if body.endswith("\n") else "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(sep + line + "\n")
