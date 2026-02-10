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
- [x] Section 5: 오라클 정확성 검증
- [x] Section 6: 가격 ≠ 확률 편차 분석 (Beta Calibration, 다중 호라이즌, 편차 차트)

## AFT 2026 논문 (paper/ — gitignored)

### Phase 1: 통계적 엄밀성 보강
- [x] Out-of-sample split (train~2024.06 / test 2024.07~)
- [x] Bootstrap CI (10,000 iterations) for ROI, Sharpe
- [x] Statistical significance (t-test, Wilcoxon)
- [x] Kelly criterion position sizing

### Option A: 데이터 확장 (2025-2026)
- [x] expand_data.py: 30,000 resolved 마켓 수집 (Step 2 완료)
- [x] clobTokenIds 매칭 (26,534건, Step 3 완료)
- [ ] 가격 히스토리 수집 (19,058건 중 진행 중, ~58% 성공률)
- [ ] 스냅샷 재추출 → 확장 데이터셋 calibration 분석

### Option B: High→Yes 전략 심층 분석
- [x] 서브구간별 성과 (75-80, 80-85, 85-90, 90-95)
- [x] 호라이즌별 비교 (T-30d, T-7d, T-1d)
- [x] Volume tier별 성과
- [x] Category별 성과
- [x] Rolling window bias 지속성
- [x] Risk 메트릭 (Sharpe, Drawdown, VaR, Kelly)

### Option C: 교차 검증
- [x] Expanding Window CV
- [x] Leave-One-Quarter-Out CV
- [x] Blocked Time-Series CV (30일 purge)
- [x] Permutation Test — **핵심 발견: High→Yes p=0.0000, Combined p=0.79**

### 핵심 결과 요약
- High→Yes (75-95%): permutation test p=0.0000 → 진짜 calibration bias arbitrage
- Combined (Mid→No + High→Yes): permutation p=0.79 → Mid→No는 bias가 아닌 구조에서 수익
- High→Yes T-1d: 166 trades, 92.8% win, +7.77% ROI, p=0.002
- 모든 CV 방법에서 High→Yes 양의 수익 확인

### Option D: 전략 현실성 검증
- [x] 시간에 따른 ROI 감소 추이 (market efficiency)
- [x] 유동성/스프레드 시뮬레이션 (실행 가능성)

### Option E: 유동성/카테고리별 Bias 구조 분석
- [x] classify_categories.py: 키워드 기반 카테고리 분류 (30K 마켓)
  - Sports 32.9%, Politics 18.5%, Crypto 6.7%, Other 37.9%
- [x] option_e_bias_structure.py: 5개 분석 (A~E)
- [x] Analysis A: 유동성 × 가격구간 Bias Heatmap (T-7d/T-30d/T-1d)
- [x] Analysis B: 카테고리 × 가격구간 Bias Heatmap
- [x] Analysis C: 유동성 × 카테고리 교차 분석
- [x] Analysis D: 통계 검정 (t-test, Spearman, Kruskal-Wallis)
- [x] Analysis E: 시간 × 유동성 교차 분석

#### Option E 핵심 발견
- **Bias 반전 확인**: 모든 카테고리에서 Low→High 유동성 bias 반전 발생
  - Low (<$10K): -6.5pp bias (***), Mid: -1.5pp (**), High: +1.6pp (***)
- **반전 임계점**: ~$72K (P50 분위수)에서 부호 전환
- **카테고리별 차이**: Kruskal-Wallis H=166.4, p<1e-35 (유의)
  - Crypto mid-range: Low -7.9pp → High +17.7pp (가장 극적)
  - Politics mid-range: Low -20.0pp → High +10.8pp
  - Sports mid-range: Low -12.8pp → High +4.9pp
- **Spearman rho = +0.29** (volume vs bias, p<1e-182)
- **시간 추이**: 저유동성 bias 2025에도 지속 (-7.7pp, p<0.001)

### 다음 단계
- [ ] 확장 데이터 수집 완료 후 전체 재분석
- [ ] Phase 2: 백테스트 고도화 (슬리피지, category별, rolling)
- [ ] Phase 3: LaTeX 논문 작성 (LIPIcs format)
