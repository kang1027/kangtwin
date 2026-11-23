# Kang Twin

나를 기억하는 기록, 그리고 그 기록을 키우고 쓰는 AI 비서.

[English](README.en.md)

지원서를 쓸 때마다 내가 한 일을 처음부터 떠올리고, 좋아하던 것도 적어 두지 않으면 잊습니다. Kang Twin은 매일 밤 내 기록에서 빈 곳을 골라 텔레그램으로 질문을 하나 보내고, 내가 [반영]을 눌러야 그 답을 마크다운 노트에 넣습니다. 이렇게 쌓인 기록으로 공모전과 지원사업을 고르고 내 말투로 초안을 쓰며, 초안을 쓰지 않은 다른 AI가 그 초안을 한 번 더 검사합니다.

- **기록은 평범한 마크다운입니다.** Obsidian으로 열어도 되고, 폴더만 있어도 됩니다.
- **내가 누르기 전에는 노트를 바꾸지 않습니다.** 반영, 제출, 발송은 텔레그램 버튼으로 승인합니다.
- **AI는 기록을 읽기만 합니다.** `claude -p`를 셸 없이, 기록 폴더 읽기 권한만 주고 부릅니다.
- **설치할 패키지가 없습니다.** 파이썬 3.9 표준 라이브러리만 씁니다.

## 어떻게 동작하나

| 단계 | 하는 일 | 언제 |
|---|---|---|
| 묻고 | 빈칸 지도(`inbox/interview-gaps.md`)에서 주제를 골라, 옛 글과 기록을 읽고 질문합니다. 답이 기록과 다르면 다시 묻습니다. | 매일 22:00, `/ask` |
| 남기고 | 답을 노트에 넣을 변경안으로 보여 주고, [반영]을 누르면 줄을 추가합니다. 답 원문과 사건 로그도 남깁니다. | 답할 때 |
| 쓰고 | 기록과 말투 기준으로 초안을 쓰고, 말투 점검 스크립트와 검수 AI가 사실 근거와 빠진 항목을 짚습니다. | 정찰, `kt write` |

정찰은 확장입니다. 켜면 아침마다 새 공모전(공모전헌터 공개 API)과 지원사업(K-Startup, 기업마당 등)을 기록과 대조해 A·B·C로 나누고, A는 초안까지 씁니다.

## 시작하기

필요한 것: macOS, Python 3.9 이상, [Claude Code](https://code.claude.com/docs) 로그인, 텔레그램 봇 토큰. 공모전 초안까지 쓰려면 공고 원문을 읽는 aside CLI(브라우저 에이전트)가 필요합니다.

```bash
git clone https://github.com/kang1027/kangtwin.git && cd kangtwin
python3 -m unittest discover -s tests -t .      # 테스트

mkdir -p ~/.config/kang-twin
cp kangtwin.example.json ~/.config/kang-twin/config.json   # vault 경로와 이름을 고친다
security add-generic-password -s kang-twin-telegram -a kangtwin -w '<봇 토큰>'

launchd/install.sh          # 데몬을 올리고 스킬을 ~/.claude/skills에 링크
bin/kt pair                 # 텔레그램에서 봇에게 /start <코드>
```

설정 파일이 없으면 저장소의 `sample-vault/`(가상 인물 한서윤)로 돕니다. 텔레그램에서 `/ask`를 보내면 바로 첫 질문이 옵니다. 자세한 설치는 [docs/SETUP-macos.md](docs/SETUP-macos.md)에 있습니다.

## 텔레그램 명령

`/ask` 인터뷰 바로 시작 · `/status` 작업 상태 · `/contests` 공모전 정찰 · `/funds` 지원사업 정찰 · `/blind` 내 글과 AI 글 구별 테스트. 그 밖의 말은 메모로 저장합니다.

## 문서

- [docs/NOTE-FORMAT.md](docs/NOTE-FORMAT.md) 기록 폴더 구조와 노트 형식
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 모듈, 승인 흐름, 확장 붙이는 법
- [SECURITY.md](SECURITY.md) 무엇을 막고 무엇은 범위 밖인지

## 한계

- macOS 전용입니다. 키체인, launchd, iCloud 볼트 권한을 쓰려고 `.app` 껍데기 안에서 돕니다.
- 한국어 사용자를 기준으로 짰습니다. 질문 말투, 말투 점검 규칙, 정찰 출처가 한국어·한국 공고입니다.
- 말투 점검의 기본 규칙은 만든 사람의 글에서 뽑았습니다. `skills/voice-check/scripts/check_voice.py`와 `voice/registers/`를 내 글에 맞게 고쳐 쓰세요.
- 한 사람, 한 텔레그램 채팅만 처리합니다.

## 라이선스

MIT
