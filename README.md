# QQQM · SCHD 리밸런싱 대시보드

GitHub Actions가 1시간마다 `scripts/update_data.py`를 실행해 `data.json`을 갱신하고,
GitHub Pages가 `index.html`을 웹 주소로 띄웁니다. 보유 수량·평균단가 같은 입력값은
각자 브라우저에만 저장되므로 저장소에는 개인 정보가 올라가지 않습니다.

| 파일 | 역할 |
|---|---|
| `index.html` | 대시보드 화면. 열 때마다 `data.json`을 읽어 그림 |
| `data.json` | 자동 갱신 데이터 (처음엔 2026-10-02 기준 초기값) |
| `config.json` | 배당 지급일·확정 일정 등 수동 입력 |
| `scripts/update_data.py` | 데이터 수집 스크립트 |
| `.github/workflows/update.yml` | 1시간마다 실행 + 배포 |
| `requirements.txt` | 파이썬 패키지 목록 |

## 설치
1. 새 저장소 만들기 (Public), 예: `qqqm-schd-dashboard`
2. 압축을 푼 파일·폴더 전부 업로드 (`.github` 숨김 폴더 포함)
3. Settings → Actions → General → Workflow permissions → Read and write permissions
4. Settings → Pages → Source: GitHub Actions
5. Actions → Update data & deploy → Run workflow
6. Settings → Pages 에 표시된 주소로 접속

## config.json
배당이 공시되었지만 아직 배당락 전일 때만 `confirmed`에 넣습니다.
`amount`를 `null`로 두면 전년 같은 분기 금액으로 추정합니다.

개인 점검용 자료이며 투자 권유가 아닙니다.
