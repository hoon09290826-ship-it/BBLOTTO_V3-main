# STABLE-5 변경사항

- app.js가 정상 바인딩되면 기존 단일 이벤트 구조를 그대로 사용합니다.
- app.js 바인딩 신호가 1.2초 안에 확인되지 않을 때만 `critical-buttons.js` 안전 모드가 활성화됩니다.
- 안전 모드는 왼쪽 메뉴, 회차 조회, 당첨확인 적용, 당첨확인/저장, 통계 기간 버튼을 독립 처리합니다.
- `/critical-buttons.js` 전용 서버 라우트와 no-store 캐시 정책을 추가했습니다.
- 배포 화면 버전을 `STABLE-5 · RUNTIME SAFETY`로 갱신했습니다.
- Python 캐시 및 컴파일 산출물을 제거했습니다.
