# Kang Twin

나를 기억하는 기록(마크다운 폴더)과, 그 기록을 밤 인터뷰로 키우고 정찰·대필·검수에 쓰는 개인 에이전트.

## 원칙

- 내용은 기록 폴더(`config.ME`), 코드는 이 저장소, 상태는 `~/.local/state/kang-twin`.
- 바깥으로 나가는 행동과 기록 반영은 텔레그램 승인 뒤에만 한다.
- 기록 편집은 `kangtwin.vault.apply_edits`(줄 추가)와 `create_note`(없던 파일)로만 한다.
- headless `claude -p`는 `llm.run_claude`로만 부른다. 읽기 전용, Bash 금지.
- 비밀값을 코드, 로그, 노트, 커밋에 쓰지 않는다.

## 구조

- `kangtwin/`: 표준 라이브러리만 쓰는 패키지. 핵심은 telegram, daemon, router, schedule, store, vault, llm, jobs(인터뷰), write(대필·검수), blind, remind, notify, pair, edits. 확장은 contestscout·gonghunt(공모전), fundscout·fundsources(지원사업).
- `skills/`: `claude -p`가 부르는 판단 단계. `_template/`은 새 스킬의 시작점.
- `sample-vault/`: 가상 인물 기록. 설정이 없으면 여기로 돈다.
- `launchd/`: macOS 데몬 설치.

## 명령

- 테스트: `python3 -m unittest discover -s tests -t .` (`-t .`가 있어야 tests/__init__.py가 임시 경로로 돌린다)
- 실행: `bin/kt <module> ...`

## 작업 규칙

- 새 기능은 테스트부터. 커밋은 작게.
