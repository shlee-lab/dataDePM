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

### 데이터 확장 완료 (expand_remaining.py)
- [x] 381개 미수집 마켓 CLOB API 시도 → 히스토리 없음 (삭제/만료 마켓)
- [x] 스냅샷 재추출: 18,696건 (변동 없음, 데이터 최대치 도달)
- [x] 카테고리 재분류 적용

### Phase 2: 고도화 백테스트 (phase2_backtest.py)
- [x] 3A. 스프레드 모델 백테스트 (vol-dependent: 4%/2%/0.75%)
- [x] 3B. 유동성 인식 전략 (Liquidity-Aware)
- [x] 3C. 카테고리별 전략 성과
- [x] 3D. Rolling Window 시뮬레이션 (6M lookback → 1M forward)
- [x] 3E. 종합 비교 테이블

#### Phase 2 핵심 결과

| Strategy | Trades | Win% | ROI | Sharpe | MaxDD | p-value |
|----------|--------|------|-----|--------|-------|---------|
| Naive Combined | 1,576 | 67.2% | +11.47% | 0.46 | 22.8 | <0.0001 |
| +Spread (vol-dep) | 1,576 | 67.2% | +9.15% | 0.38 | 23.8 | <0.0001 |
| +Liquidity Filter | 577 | 77.3% | +22.82% | 1.06 | 13.7 | <0.0001 |
| Rolling Window | 846 | 59.1% | +10.45% | 0.38 | 23.8 | 0.0015 |
| Optimal Combo | 577 | 77.3% | +22.82% | 1.06 | 13.7 | <0.0001 |

- **Spread cost**: 2.32pp ROI reduction
- **Liquidity filter**: +13.67pp ROI improvement (최강 단일 개선)
- **Low-Vol Mid→No** 압도적: 71.4% win, +33~38% ROI, Sharpe 1.3-1.5
- **High-Vol High→Yes** 비유의: 88.8% win, +3% ROI, p=0.21
- **Rolling Sharpe**: 0.71 (monthly-return basis), 누적 +88.4 units
- **카테고리**: Other/Sports 최강; Crypto는 전체적으로 음수

### Phase 2.5: Calibration Bias 대시보드 + 스프레드 실측 + Other 세분화

#### Step 1: Other 카테고리 세분화
- [x] classify_categories.py 업데이트: Sports 키워드 보강 + 4개 신규 카테고리 추가
  - Geopolitics (626건), Economics (286건), Weather (424건), Social Media (616건)
  - Other: 37.9% → 18.4% (resolved), 48.7% → 20.9% (snapshots)
  - Sports: 32.9% → 50.9% (resolved), 13.8% → 36.6% (snapshots)

#### Step 2: 스프레드 실측 수집
- [x] collect_spreads.py: Gamma API로 751개 활성 마켓 bid/ask 실측
  - 전체 median=2.0c, mean=3.9c
  - Liquidity별: <$1K=15.0c, $1K-$10K=2.9c, $10K-$100K=1.0c, $100K+=1.0c
  - 기존 추정(Low 4%, Mid 2%, High 0.75%)은 대체로 적절하지만 약간 보수적

#### Step 3: 데이터 생성 스크립트
- [x] build_calibration_dashboard.py: 대시보드용 JSON 생성 (34.3 KB)
  - calibration curve 데이터 (전체/카테고리별/유동성별)
  - bias heatmap 데이터
  - spread 실측 통계
  - 백테스트 요약 메트릭

#### Step 4: Calibration Bias 대시보드
- [x] site/calibration.html: Chart.js 기반 다크 테마 standalone 대시보드
  - A. Calibration Curves (전체/카테고리별/유동성별 탭 전환)
  - B. Bias Heatmaps (유동성×가격, 카테고리×가격)
  - C. Spread 실측 분포 + 기존 추정 vs 실측 비교
  - D. Phase 2 백테스트 요약 + Rolling Window 누적 PnL
  - E. Category Breakdown

#### Step 5: Phase 2 백테스트 재실행 (실측 스프레드 반영)
- [x] phase2_backtest.py 스프레드 모델 업데이트
  - 4-tier 측정 기반: <$1K=15c, $1K-$10K=2.8c, $10K-$100K=1c, $100K+=1c
  - 카테고리 확장: Geopolitics, Economics 추가

#### Updated Phase 2 Results (Measured Spread Model)

| Strategy | Trades | Win% | ROI | Sharpe | MaxDD | p-value |
|----------|--------|------|-----|--------|-------|---------|
| Naive Combined | 1,576 | 67.2% | +11.47% | 0.46 | 22.8 | <0.0001 |
| +Spread (measured) | 1,576 | 67.1% | +8.36% | 0.35 | 23.8 | 0.0001 |
| +Liquidity Filter | 577 | 77.3% | +20.01% | 0.96 | 13.7 | <0.0001 |
| Rolling Window | 846 | 59.0% | +9.76% | 0.36 | 23.8 | 0.0029 |

- **Spread cost**: 3.11pp ROI reduction (vs 2.32pp with old model)
- **Liquidity filter**: +11.65pp ROI improvement
- **Rolling Sharpe**: 0.56 (monthly-return basis), cumulative +82.6 units

### Phase 2.7: Fine-grained DTC Bias Analysis (daily price history)
- [x] fine_grained_dtc_analysis.py: 828K daily observations, 18,629 markets
- [x] Timestamp bug fix: datetime64[us] → ÷10⁶ (not ÷10⁹)

#### 핵심 발견: Bias는 DTC의 함수
- **Mid-range (35-65%)**: slope = -12.4 pp/log₁₀(day), R²=0.278
  - DTC=1d: +10.8pp (overpriced → corrected), DTC=30d: -7.5pp, DTC=180d: -17.1pp
  - 교차점: DTC ≈ 3-7일에서 bias가 부호 반전
- **High-range (65-85%)**: slope = -5.5 pp/log₁₀(day)
  - DTC<14d: slight positive bias (+2pp), DTC>30d: deeply negative (-6 to -17pp)
- **Very High (85-95%)**: slope = **+4.1** pp/log₁₀(day) — 반대 방향!
  - Near-certain 가격은 close에서 오히려 덜 정확

#### Volume × DTC (가장 강력한 교차 효과)
- **<$10K**: 모든 DTC에서 강한 negative bias (-16.5pp ~ -36.1pp)
- **$100K-1M**: short DTC에서 positive (+6pp), long DTC에서 deep negative (-23.7pp)
- **$1M+**: short DTC에서 **+18.6pp**, long DTC에서 -47.5pp (가장 극적인 반전)

#### Category × DTC
- **Sports**: 모든 DTC에서 일관된 negative bias (-12.8pp ~ -25.5pp)
- **Crypto**: short DTC에서 positive (+3~6pp), long DTC에서 deep negative (-27.7pp)
- **Geopolitics**: short DTC에서 neutral, long DTC에서 deep negative (-33pp)

#### Duration × DTC
- **Short (<7d) markets**: close 근처에서도 강한 bias (-8pp ~ -14pp)
- **VLong (90d+) markets**: DTC=1-7d에서 약한 bias, DTC=90d+에서 -24.4pp

#### 전략적 시사점
1. **Time-aware 진입**: DTC>7d일 때만 Mid→No 진입 (crossover 이후)
2. **High-range도 overpriced**: DTC>30d에서 High→No도 유효한 전략
3. **Volume 필터 강화**: $1M+ 마켓은 DTC>60d에서만 진입
4. **Exit timing**: bias가 줄어드는 DTC<3d 전에 청산

### Phase 2.8: Unified Calibration Bias Report
- [x] paper/build_unified_report.py: calibration_data.json + dtc_report_data.json → unified_report_data.json
  - Bias trajectories: raw price → bias (pp) = resolution - price
- [x] paper/report.html: 7-section unified report
  - 1. Overview (calibration curves, stat cards)
  - 2. Bias Structure (static heatmaps by liq/category)
  - 3. Time Dimension (DTC curves, regression)
  - 4. Cross Analysis (cat×DTC, vol×DTC, dur×DTC heatmaps)
  - 5. Bias Reality (bias trajectory chart: No vs Yes resolution)
  - 6. Actionability (spread, backtest, category breakdown)
  - 7. Strategic Implications

### Phase 2.9: Calibration Bias Storytelling Page
- [x] site/bias.html: single-page storytelling analysis
  - 7 sections: Discovery → Where → When → Crossover → Reality → Profitability → Implications
  - GitHub-dark design (report.html CSS vars) + stat-grid/insight-box layout (index.html patterns)
  - Side nav with scroll-spy highlighting + mobile top nav fallback
  - KO/EN i18n toggle (50+ data-i18n elements)
  - 8 Chart.js charts: calibration curve, deviation bar, DTC curves, regression scatter, bias trajectory, rolling PnL, spread × 2
  - DTC cross-heatmaps with tabs (category, volume, duration)
  - Data from ../paper/unified_report_data.json (no build step needed)

### 다음 단계
- [ ] Phase 3: LaTeX 논문 작성 (LIPIcs format)
