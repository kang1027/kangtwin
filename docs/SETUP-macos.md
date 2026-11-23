# macOS 설치

## 1. 준비

- Python 3.9 이상(`/usr/bin/python3`이면 됩니다).
- Claude Code CLI를 설치하고 로그인합니다. 데몬은 키체인의 로그인 정보를 씁니다.
- 텔레그램 @BotFather에서 봇을 만들고 토큰을 받습니다.

## 2. 설정

```bash
mkdir -p ~/.config/kang-twin && chmod 700 ~/.config/kang-twin
cp kangtwin.example.json ~/.config/kang-twin/config.json
```

- `vault`: 기록 볼트 경로. 그 안의 `me_dir`(기본 `Me`)이 기록 폴더입니다. 처음이면 `sample-vault/Me`를 복사해 시작하세요.
- `jobs`: 정시에 돌 작업. `interview`만 두면 밤 질문만 옵니다.
- `home_regions`, `egbiz_area`: 지원사업 정찰의 지역 조건. 경기기업비서 시군 코드를 비우면 그 출처는 건너뜁니다.

토큰은 키체인에 넣거나, 권한 600 파일 `~/.config/kang-twin/telegram-token`에 둡니다.

```bash
security add-generic-password -s kang-twin-telegram -a kangtwin -w '<봇 토큰>'
```

지원사업 정찰을 쓰면 공공데이터포털 키를 `~/.config/kang-twin/datagokr-key`(600)에 둡니다.

## 3. 데몬

```bash
launchd/install.sh
bin/kt pair
```

`install.sh`는 `~/Applications/Kang Twin.app`을 만들고 LaunchAgent를 올립니다. launchd가 바로 띄운 파이썬은 iCloud 안 볼트를 못 읽는 경우가 있어서, 데몬은 이 앱 아래에서 돕니다. 처음 실행 때 볼트 접근 허용 창이 뜨면 허용하세요.

## 4. 확인

- 텔레그램에서 `/status`, `/ask`.
- 로그: `~/Library/Logs/kang-twin/receiver.log`.
