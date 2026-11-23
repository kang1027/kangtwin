"""데몬 안의 정시 작업. launchd 대신 데몬이 띄워야 Kang Twin.app의 파일 권한을 물려받는다."""
from datetime import datetime, timedelta
from typing import Dict, FrozenSet, List, Optional, Tuple

from . import config

# (작업, 시, 분). 맥이 잠들어 놓쳐도 WINDOW 안에 깨면 한 번 돈다.
SLOTS = [("contest-scout", 8, 30), ("fund-scout", 10, 0), ("interview", 22, 0)]
# 설정 파일의 jobs에 없는 작업은 정시에 돌지 않는다. /contests 같은 수동 실행은 그대로 된다.
PAUSED = frozenset(job for job, _, _ in SLOTS if job not in config.ENABLED_JOBS)
WINDOW = timedelta(hours=3)
FMT = "%Y-%m-%d %H:%M"


def due(now: datetime, last: Dict[str, str], paused: Optional[FrozenSet[str]] = None) -> List[Tuple[str, str]]:
    """지금 돌려야 할 (작업, 슬롯 키) 목록. last는 작업별 마지막으로 돈 슬롯 키."""
    paused = PAUSED if paused is None else paused
    out: Dict[str, str] = {}
    for job, hour, minute in SLOTS:
        if job in paused:
            continue
        for days_back in (1, 0):
            slot = (now - timedelta(days=days_back)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            key = slot.strftime(FMT)
            if slot <= now < slot + WINDOW and key > last.get(job, "") and key > out.get(job, ""):
                out[job] = key
    return sorted(out.items(), key=lambda kv: kv[1])
