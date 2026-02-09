# 예측시장 구조적 리스크 데이터 수집

## 수집 항목
- [x] Polymarket 유동성 데이터 (TVL 히스토리, 마켓별 분포)
- [x] Polymarket 거래 데이터 (wash trading 분석용)
- [x] Polymarket 종료 마켓 데이터 (10,000건 수집, 해결 결과 파싱)
- [x] UMA 오라클 토큰 분포
- [x] UMA dispute 기록
- [x] UMA 이벤트 hex 디코딩 (PriceRequest, PriceResolved, VoteRevealed)
- [x] Kleros 분쟁 이벤트 hex 디코딩 (DisputeCreation, Ruling, VoteCast, Draw)

## 분석 항목
- [x] 유동성 집중도 분석
- [x] 시장 조작 취약도 분석
- [x] 오라클 결정권 집중도 분석
- [x] UMA 분쟁 해결 분석 (YES_OR_NO_QUERY 결과, 합의도, 투표 권한 집중도)
- [x] Kleros 분쟁 해결 분석 (Ruling 분포, 배심원 재참여율, 항소율)
- [x] Polymarket 종료 마켓 해결 통계

## 대시보드
- [x] Section 1-4: 유동성, 조작, 오라클 집중도, 투표 활동
- [x] Section 5: 오라클 정확성 검증 (신규)
  - UMA 식별자 카테고리 도넛, YES_OR_NO 해결 도넛
  - UMA 투표 합의도 바차트, 투표 권한 집중도 차트
  - Kleros Ruling 분포 도넛, 배심원 참여 빈도 차트
  - 한/영 전환 지원

## 완료 기준
- [x] 6개월 히스토리컬 데이터 수집 완료
- [x] 각 리스크별 핵심 지표 산출
- [x] 오라클 정확성 검증 섹션 추가
