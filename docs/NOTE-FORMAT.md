# 기록 폴더 형식

기록은 마크다운 파일입니다. 파일이 원본이고, Kang Twin은 줄을 더하기만 합니다. `sample-vault/Me`가 가장 작은 예시입니다.

## 폴더

| 폴더 | 무엇 | 누가 쓰나 |
|---|---|---|
| `facts/` | 사실. `profile.md`(자격 줄, 주력 아이템), `timeline.md`, `education.md`, `work-style.md`, `life.md`(취미, 운동, 읽기와 보기) | 나, 인터뷰 반영 |
| `projects/` | 만든 것 하나에 노트 하나. 역할, 스택, 상태 | 나, 인터뷰 반영 |
| `stories/` | 겪은 일. 지원서 문단의 재료 | 나, 인터뷰 반영 |
| `claims/` | 내세울 점과 그 근거 노트 | 나 |
| `inbox/interview-gaps.md` | 밤 인터뷰가 고르는 빈칸 목록(표) | 나 |
| `inbox/interview-*.md` | 인터뷰 변경안 | Kang Twin |
| `inbox/memos.md` | 텔레그램으로 보낸 메모 | Kang Twin |
| `voice/registers/` | 말투 기준. `apply.md`, `message.md`, `mail.md` | 나 |
| `voice/exemplars/` | 내가 쓴 글 견본. 앞머리 `voice: own` | 나 |
| `voice/corpus/` | 옛 글(노션, 블로그)과 인터뷰 답 원문(`chat/YYYY-MM.md`) | 나, Kang Twin |
| `events/YYYY-MM.md` | 사건 로그. 인터뷰 반영, 공모전 제출 줄 | Kang Twin, 나 |
| `policy.md` | 혼자 하는 일, 승인받는 일, 사실로 쓰지 않을 파일 | 나 |

## 앞머리

```markdown
---
type: fact
status: active
---
```

`type`은 fact, project, story, claim, guide, exemplar, log 중 하나면 충분합니다. 견본은 `voice: own|edited|approved`로 내가 직접 쓴 정도를 적습니다.

## 빈칸 지도

```markdown
| 주제 | 지금 아는 것 | 아직 모르는 것 | 단서 |
|---|---|---|---|
| 취미 | 기타를 잠깐 배움 | 지금 하는 취미 | `facts/life.md` |
```

위에 있는 주제부터 묻습니다. 채워지면 줄을 지우거나 "채움"으로 바꿉니다.

## 공모전 제출 기록

정찰이 이미 낸 대회를 다시 고르지 않게, 낸 대회는 사건 로그에 이렇게 남깁니다.

```markdown
- 2026-10-22 공모전 제출: OO 어워즈 2026 학생부, 작품 Sprout
```
