# STABLE-7 Winning Check Pagination Fix

## 수정 내용
- 회원별 당첨확인 결과의 처음/이전/페이지 번호/다음/마지막 버튼 연결 복구
- 회원별 당첨확인 페이지당 표시 개수 선택 연결 복구
- 최근 저장 당첨번호 목록 페이지 이동 및 페이지 크기 연결도 함께 보강
- 실제 renderPagination 호출 함수와 공통 이벤트 허용 목록을 일치시킴

## 원인
`renderPagination()`은 `setWinCheckPage`, `setWinCheckPageSize`, `setDrawPage`, `setDrawPageSize`를 생성했지만 공통 이벤트 라우터의 허용 목록에 해당 함수가 없어 클릭 및 변경 이벤트가 무시되었습니다.
