# STABLE-6 Pagination Fix

## Fixed
- 통계 페이지 번호 버튼이 클릭돼도 반응하지 않던 문제 수정.
- 공통 페이지 이벤트 허용 목록에 `setStatsPage` 추가.
- 페이지당 표시 개수 선택의 인라인 `onchange` 제거.
- CSP 환경에서도 동작하도록 `data-action="page-size-call"` 기반 공통 change 이벤트로 통합.
- 회원, 당첨확인, 문자이력, 추천이력, 통계 페이지 크기 선택을 동일한 방식으로 처리.

## Root cause
통계 페이지 버튼은 `data-page-fn="setStatsPage"`를 생성했지만 이벤트 라우터의 허용 함수 목록에 `setStatsPage`가 누락되어 클릭이 조용히 무시되고 있었습니다.
