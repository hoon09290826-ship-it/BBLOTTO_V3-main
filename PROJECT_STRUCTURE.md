# BBLOTTO V3 STABLE-1 프로젝트 구조

## 실행 핵심

- `start.py`: 배포/로컬 실행 진입점
- `backend/app.py`: FastAPI 서버, API, 인증, DB 마이그레이션 및 화면 파일 제공
- `frontend/index.html`: 관리자 메인 화면
- `frontend/app.js`: 관리자 화면 이벤트 및 API 연결
- `frontend/style.css`: 관리자 화면 스타일
- `frontend/login.html`, `frontend/login.js`: 로그인 화면
- `database/bblotto_v34.db`: 회원·관리자·추천·문자·설정 운영 DB
- `database/lotto.db`: 당첨번호/분석 데이터 DB
- `database/winning_numbers_1_1231.csv`: 초기 당첨번호 데이터

## 분석 엔진

- `backend/ai_engine_v7.py`: 현재 `backend/app.py`에서 직접 사용하는 추천/분석 엔진
- `backend/analysis_engine_rc11.py`: 회원용 분석 문구 생성에 사용
- `backend/ai_engine.py`, `backend/analyzer.py`: 이전 분석 경로로 보이며 STABLE-2에서 호출 여부를 추가 확인
- `backend/db.py`, `backend/draw_service.py`: 별도 당첨번호 서비스 경로. 현재 메인 앱의 DB 경로와 다르므로 STABLE-2에서 통합 여부 확인

## STABLE-1 정리 원칙

운영 동작에 영향이 명확하지 않은 백엔드 파일은 삭제하지 않았습니다. 실행에서 참조되지 않는 프론트 설정 화면, 인증 실험 파일, 생성된 캐시와 압축에 포함된 DB 백업만 제거했습니다.
