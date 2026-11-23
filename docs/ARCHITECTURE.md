# 구조

## 흐름

```
텔레그램 ── telegram ── daemon(수신 루프 + 정시 작업) ── router(명령 분류)
                              │
                              ├─ jobs: 밤 인터뷰 ── llm.ask_skill(kang-twin-interview) ── vault.apply_edits
                              ├─ contestscout / fundscout (확장, 별도 프로세스)
                              │     └─ llm(kang-twin-contests / -funds) ── write(kang-twin-write → check_voice → kang-twin-review)
                              └─ remind, blind, notify
```

- **데몬**은 하나만 돕니다. 텔레그램 롱폴링과 정시 작업(`schedule.SLOTS`)을 같이 봅니다. 두 곳에서 돌면 텔레그램이 409를 줍니다.
- **LLM 호출**은 모두 `llm.run_claude`를 거칩니다. 프롬프트 첫 줄에 `기록 폴더:`를 넣어 스킬이 경로를 알게 합니다.
- **반영**은 인터뷰 상태가 `proposed`일 때 [반영] 버튼으로만 일어납니다. 반영 전 파일은 백업하고, 사건 로그에 한 줄 남깁니다.

## 인터뷰 상태

`asked → awaiting_answer → (꼬리 질문) → proposed → closed`. 답할 때마다 원문을 `voice/corpus/chat/`에 남깁니다. [고쳐줘]를 누르면 `revising`으로 가서 다시 변경안을 만듭니다.

## 대필과 검수

1. `kang-twin-write`가 말투 기준, 견본, 원본 노트만 보고 씁니다.
2. `check_voice.py`가 종결 어미, 문장 길이, 문장 잇기, 금지 표현을 기계로 봅니다. 오류가 있으면 한 번 다시 씁니다.
3. `kang-twin-review`가 새 컨텍스트에서 사실 근거, 심사 기준 대비 빠짐·약함, AI 말투를 짚습니다. 걸리면 한 번 더 고쳐 쓰고, 점검이 나빠지면 버립니다.

## 확장 붙이기

1. `kangtwin/` 아래에 `python -m`으로 도는 모듈을 만듭니다. 기록은 `config.OUTPUTS`, 알림은 `notify.send`.
2. `schedule.SLOTS`에 (작업, 시, 분), `daemon.launch_scheduled`의 모듈 표에 (작업 → 모듈, 로그 파일)을 더합니다.
3. 수동 실행 명령이 필요하면 `router.route`에 한 줄 더합니다.
4. 설정 파일 `jobs`에 작업 이름을 넣으면 정시에 돕니다.
