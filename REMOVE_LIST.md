# STABLE-1 제거 내역

## 실제 제거

- `__pycache__/`, `backend/__pycache__/`: Python 실행 캐시
- `database/exports/BBLOTTO_V34_BACKUP_20260713_050516.db`: 압축본에 포함된 과거 백업 DB
- `frontend/setup.html`, `frontend/setup.js`: 서버 라우트 및 메인 화면에서 참조되지 않는 초기 설정 화면
- `frontend/static/js/auth-client.js`: 현재 로그인/메인 화면에서 로드되지 않는 별도 인증 실험 파일

## 보류

다음 파일은 중복 가능성이 있지만 삭제 시 기능 영향이 불명확해 유지했습니다.

- `backend/ai_engine.py`
- `backend/analyzer.py`
- `backend/db.py`
- `backend/draw_service.py`

STABLE-2에서 실제 호출 경로와 DB 연결을 확인한 후 통합 또는 제거합니다.
