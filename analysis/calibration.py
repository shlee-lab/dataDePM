"""
Polymarket 예측 Calibration 분석 모듈

Calibration curve, Brier score, 거래량 티어별 분석, Sharpness 계산.
build_site.py에서 사용할 dict 반환.
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"


def analyze_calibration() -> dict:
    """Calibration 분석 실행.

    Returns:
        dict with calibration_curves, brier_scores, volume_tier_brier,
        sharpness, total_markets, yes_rate, data_period
    """
    path = DATA_DIR / "polymarket_calibration_snapshots.parquet"
    if not path.exists():
        return {}

    df = pd.read_parquet(path)
    if df.empty:
        return {}

    total = len(df)
    yes_rate = float(df["resolution_binary"].mean())

    # 데이터 기간
    closed_times = pd.to_datetime(df["closed_time"], format="mixed", utc=True)
    data_period = {
        "start": closed_times.min().strftime("%Y-%m-%d"),
        "end": closed_times.max().strftime("%Y-%m-%d"),
    }

    # ── Calibration Curves ────────────────────────────────────────
    price_cols = {
        "t0": "price_t0",
        "t1d": "price_t1d",
        "t7d": "price_t7d",
        "t30d": "price_t30d",
    }

    calibration_curves = {}
    brier_scores = {}
    sharpness = {}

    bin_edges = np.arange(0, 1.1, 0.1)  # 0, 0.1, 0.2, ..., 1.0
    bin_mids = (bin_edges[:-1] + bin_edges[1:]) / 2  # 0.05, 0.15, ..., 0.95

    for label, col in price_cols.items():
        valid = df[df[col].notna()].copy()
        if valid.empty:
            continue

        prices = valid[col].values
        outcomes = valid["resolution_binary"].values

        # Brier score: mean((price - outcome)^2)
        brier = float(np.mean((prices - outcomes) ** 2))
        brier_scores[label] = round(brier, 4)

        # Sharpness: mean((price - 0.5)^2) — 높을수록 확신 있는 예측
        sharp = float(np.mean((prices - 0.5) ** 2))
        sharpness[label] = round(sharp, 4)

        # Calibration curve (10 bins)
        curve = []
        bin_indices = np.digitize(prices, bin_edges) - 1
        # clamp to valid range [0, 9]
        bin_indices = np.clip(bin_indices, 0, len(bin_mids) - 1)

        for i in range(len(bin_mids)):
            mask = bin_indices == i
            count = int(mask.sum())
            if count > 0:
                actual_rate = float(outcomes[mask].mean())
            else:
                actual_rate = None
            curve.append({
                "bin_mid": round(float(bin_mids[i]), 2),
                "actual_rate": round(actual_rate, 4) if actual_rate is not None else None,
                "count": count,
            })

        calibration_curves[label] = curve

    # ── 편차(Deviation) 분석 ──────────────────────────────────────
    deviation_summary = {}
    deviation_by_range = {}

    for label, curve in calibration_curves.items():
        # 각 bin의 deviation = actual_rate - bin_mid
        dev_bins = []
        for pt in curve:
            dev = None
            if pt["actual_rate"] is not None:
                dev = round(pt["actual_rate"] - pt["bin_mid"], 4)
            dev_bins.append({
                "bin_label": f'{int(pt["bin_mid"] * 100)}%',
                "bin_mid": pt["bin_mid"],
                "actual_rate": pt["actual_rate"],
                "deviation": dev,
                "count": pt["count"],
            })
        deviation_summary[label] = dev_bins

        # 구간별 가중평균 편차 (low: 5-25%, mid: 35-65%, high: 75-95%)
        range_defs = {
            "low":  {"range": "5-25%",  "mids": {0.05, 0.15, 0.25}},
            "mid":  {"range": "35-65%", "mids": {0.35, 0.45, 0.55, 0.65}},
            "high": {"range": "75-95%", "mids": {0.75, 0.85, 0.95}},
        }
        range_result = {}
        for rng_key, rng_def in range_defs.items():
            bins_in_range = [b for b in dev_bins
                             if b["bin_mid"] in rng_def["mids"]
                             and b["deviation"] is not None
                             and b["count"] > 0]
            total_count = sum(b["count"] for b in bins_in_range)
            if total_count > 0:
                weighted_dev = sum(b["deviation"] * b["count"] for b in bins_in_range) / total_count
                range_result[rng_key] = {
                    "range": rng_def["range"],
                    "avg_deviation": round(weighted_dev, 4),
                    "avg_deviation_pp": round(weighted_dev * 100, 1),
                    "count": total_count,
                }
            else:
                range_result[rng_key] = {
                    "range": rng_def["range"],
                    "avg_deviation": 0,
                    "avg_deviation_pp": 0.0,
                    "count": 0,
                }
        deviation_by_range[label] = range_result

    # ── 회귀 분석 (Regression): Predicted vs Actual ───────────────
    regression_models = {}

    for label, curve in calibration_curves.items():
        valid_points = [(pt["bin_mid"], pt["actual_rate"])
                        for pt in curve
                        if pt["actual_rate"] is not None and pt["count"] > 0]

        if len(valid_points) >= 3:  # 최소 3개 포인트 필요
            x_vals = np.array([p[0] for p in valid_points])
            y_vals = np.array([p[1] for p in valid_points])

            # 선형 회귀: y = slope * x + intercept
            slope, intercept = np.polyfit(x_vals, y_vals, 1)

            # R² 계산
            y_pred = slope * x_vals + intercept
            ss_res = np.sum((y_vals - y_pred) ** 2)
            ss_tot = np.sum((y_vals - np.mean(y_vals)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

            # 회귀선 데이터 (0 ~ 1 범위)
            regression_line = [
                {"x": 0.0, "y": float(intercept)},
                {"x": 1.0, "y": float(slope + intercept)},
            ]

            regression_models[label] = {
                "slope": round(float(slope), 4),
                "intercept": round(float(intercept), 4),
                "r_squared": round(float(r_squared), 4),
                "regression_line": regression_line,
                "n_points": len(valid_points),
            }

    # ── 거래량 티어별 Brier Score ─────────────────────────────────
    volume_tiers = {
        "1M+": df["volume"] >= 1_000_000,
        "100K+": (df["volume"] >= 100_000) & (df["volume"] < 1_000_000),
        "10K+": (df["volume"] >= 10_000) & (df["volume"] < 100_000),
        "< 10K": df["volume"] < 10_000,
    }

    volume_tier_brier = {}
    for tier_name, mask in volume_tiers.items():
        tier_data = df[mask]
        tier_brier = {}
        tier_count = len(tier_data)

        for label, col in price_cols.items():
            valid = tier_data[tier_data[col].notna()]
            if len(valid) >= 5:  # 최소 5개 이상
                prices = valid[col].values
                outcomes = valid["resolution_binary"].values
                tier_brier[label] = round(float(np.mean((prices - outcomes) ** 2)), 4)

        if tier_brier:
            volume_tier_brier[tier_name] = {
                "count": tier_count,
                **tier_brier,
            }

    return {
        "total_markets": total,
        "yes_rate": round(yes_rate, 4),
        "calibration_curves": calibration_curves,
        "brier_scores": brier_scores,
        "volume_tier_brier": volume_tier_brier,
        "sharpness": sharpness,
        "data_period": data_period,
        "deviation_summary": deviation_summary,
        "deviation_by_range": deviation_by_range,
        "regression_models": regression_models,
    }


def main():
    print("=== Calibration 분석 ===\n")

    result = analyze_calibration()
    if not result:
        print("calibration_snapshots.parquet이 없습니다.")
        return

    print(f"분석 마켓: {result['total_markets']}")
    print(f"Yes 비율: {result['yes_rate']:.1%}")
    print(f"데이터 기간: {result['data_period']['start']} ~ {result['data_period']['end']}")

    print(f"\nBrier Scores:")
    for k, v in result["brier_scores"].items():
        print(f"  {k}: {v:.4f}")

    print(f"\nSharpness:")
    for k, v in result["sharpness"].items():
        print(f"  {k}: {v:.4f}")

    print(f"\n거래량 티어별 Brier (T-7d):")
    for tier, data in result["volume_tier_brier"].items():
        t7d = data.get("t7d", "N/A")
        print(f"  {tier} ({data['count']}건): {t7d}")

    print(f"\n편차 분석 (T-7d):")
    dev_range = result.get("deviation_by_range", {}).get("t7d", {})
    for rng_key in ["low", "mid", "high"]:
        r = dev_range.get(rng_key, {})
        pp = r.get("avg_deviation_pp", 0)
        sign = "+" if pp > 0 else ""
        print(f"  {r.get('range', '?')}: {sign}{pp}pp ({r.get('count', 0)}건)")

    print(f"\nBin별 편차 (T-7d):")
    dev_bins = result.get("deviation_summary", {}).get("t7d", [])
    for b in dev_bins:
        if b["deviation"] is not None:
            sign = "+" if b["deviation"] > 0 else ""
            print(f"  {b['bin_label']:>3}: actual {b['actual_rate']:.3f}, dev {sign}{b['deviation']*100:.1f}pp ({b['count']}건)")

    print(f"\n회귀 분석 (T-7d):")
    reg_t7d = result.get("regression_models", {}).get("t7d", {})
    if reg_t7d:
        print(f"  y = {reg_t7d['slope']:.4f} * x + {reg_t7d['intercept']:.4f}")
        print(f"  R² = {reg_t7d['r_squared']:.4f}")
        print(f"  ({reg_t7d['n_points']}개 포인트)")

    print("\n=== 분석 완료 ===")


if __name__ == "__main__":
    main()
