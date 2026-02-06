"""
집중도 지표 계산 모듈
- 지니 계수 (Gini Coefficient)
- HHI (Herfindahl-Hirschman Index)
- 나카모토 계수 (Nakamoto Coefficient)
- 섀넌 엔트로피 (Shannon Entropy)
- 타일 지수 (Theil Index)
"""

import numpy as np
import pandas as pd
from typing import List, Dict


def gini_coefficient(values: np.ndarray) -> float:
    """
    지니 계수 계산
    0 = 완전 평등, 1 = 완전 불평등

    공식: G = (2 * Σ(i * x_i)) / (n * Σx_i) - (n+1)/n
    """
    values = np.array(values, dtype=float)
    values = values[values > 0]  # 0 제외

    if len(values) == 0:
        return 0.0

    values = np.sort(values)
    n = len(values)
    cumsum = np.cumsum(values)

    gini = (2 * np.sum((np.arange(1, n + 1) * values))) / (n * cumsum[-1]) - (n + 1) / n
    return round(gini, 4)


def herfindahl_hirschman_index(values: np.ndarray) -> float:
    """
    허핀달-허쉬만 지수 (HHI) 계산
    0 = 완전 분산, 10000 = 완전 독점

    해석:
    - < 1500: 경쟁적 시장
    - 1500-2500: 중간 집중
    - > 2500: 고도 집중

    공식: HHI = Σ(s_i^2) * 10000, s_i = 시장 점유율
    """
    values = np.array(values, dtype=float)
    values = values[values > 0]

    if len(values) == 0:
        return 0.0

    total = np.sum(values)
    shares = values / total  # 점유율
    hhi = np.sum(shares ** 2) * 10000

    return round(hhi, 2)


def nakamoto_coefficient(values: np.ndarray, threshold: float = 0.51) -> int:
    """
    나카모토 계수 계산
    threshold(기본 51%)를 장악하기 위해 필요한 최소 엔티티 수

    값이 낮을수록 중앙화됨 (1 = 완전 중앙화)
    """
    values = np.array(values, dtype=float)
    values = values[values > 0]

    if len(values) == 0:
        return 0

    values = np.sort(values)[::-1]  # 내림차순
    total = np.sum(values)

    cumsum = 0
    for i, v in enumerate(values):
        cumsum += v
        if cumsum / total >= threshold:
            return i + 1

    return len(values)


def shannon_entropy(values: np.ndarray) -> float:
    """
    섀넌 엔트로피 계산
    높을수록 분산됨

    공식: H = -Σ(p_i * log2(p_i))
    """
    values = np.array(values, dtype=float)
    values = values[values > 0]

    if len(values) == 0:
        return 0.0

    total = np.sum(values)
    probs = values / total

    # log(0) 방지
    probs = probs[probs > 0]
    entropy = -np.sum(probs * np.log2(probs))

    return round(entropy, 4)


def normalized_entropy(values: np.ndarray) -> float:
    """
    정규화된 엔트로피 (0~1)
    0 = 완전 집중, 1 = 완전 분산
    """
    values = np.array(values, dtype=float)
    values = values[values > 0]

    if len(values) <= 1:
        return 0.0

    max_entropy = np.log2(len(values))
    if max_entropy == 0:
        return 0.0

    return round(shannon_entropy(values) / max_entropy, 4)


def theil_index(values: np.ndarray) -> float:
    """
    타일 지수 (Theil Index) 계산
    0 = 완전 평등, 값이 클수록 불평등

    지니 계수보다 극단값에 민감
    """
    values = np.array(values, dtype=float)
    values = values[values > 0]

    if len(values) == 0:
        return 0.0

    n = len(values)
    mean = np.mean(values)

    if mean == 0:
        return 0.0

    theil = np.sum((values / mean) * np.log(values / mean)) / n

    return round(theil, 4)


def top_n_share(values: np.ndarray, n: int) -> float:
    """상위 N개의 점유율 (%)"""
    values = np.array(values, dtype=float)
    values = values[values > 0]

    if len(values) == 0:
        return 0.0

    values = np.sort(values)[::-1]
    total = np.sum(values)

    top_sum = np.sum(values[:n])

    return round(top_sum / total * 100, 2)


def calculate_all_metrics(values: np.ndarray, name: str = "") -> Dict:
    """모든 집중도 지표 계산"""

    values = np.array(values, dtype=float)
    values = values[values > 0]

    return {
        "name": name,
        "sample_size": len(values),
        "total": float(np.sum(values)),

        # 기본 점유율
        "top5_share": top_n_share(values, 5),
        "top10_share": top_n_share(values, 10),
        "top20_share": top_n_share(values, 20),

        # 학술적 지표
        "gini": gini_coefficient(values),
        "hhi": herfindahl_hirschman_index(values),
        "nakamoto": nakamoto_coefficient(values),
        "entropy": shannon_entropy(values),
        "normalized_entropy": normalized_entropy(values),
        "theil": theil_index(values),
    }


def interpret_hhi(hhi: float) -> str:
    """HHI 해석"""
    if hhi < 1500:
        return "경쟁적 (< 1500)"
    elif hhi < 2500:
        return "중간 집중 (1500-2500)"
    else:
        return "고도 집중 (> 2500)"


def interpret_gini(gini: float) -> str:
    """지니 계수 해석"""
    if gini < 0.4:
        return "낮은 불평등"
    elif gini < 0.6:
        return "중간 불평등"
    else:
        return "높은 불평등"


if __name__ == "__main__":
    # 테스트
    from pathlib import Path

    DATA_DIR = Path(__file__).parent.parent / "data"

    print("=== 집중도 지표 계산 ===\n")

    # UMA
    uma_df = pd.read_parquet(DATA_DIR / "uma_holders.parquet")
    uma_metrics = calculate_all_metrics(uma_df["balance"].values, "UMA")

    print(f"[UMA Oracle]")
    print(f"  샘플 수: {uma_metrics['sample_size']}")
    print(f"  지니 계수: {uma_metrics['gini']} ({interpret_gini(uma_metrics['gini'])})")
    print(f"  HHI: {uma_metrics['hhi']} ({interpret_hhi(uma_metrics['hhi'])})")
    print(f"  나카모토 계수: {uma_metrics['nakamoto']} (51% 장악에 필요한 최소 수)")
    print(f"  정규화 엔트로피: {uma_metrics['normalized_entropy']} (1에 가까울수록 분산)")
    print()

    # Kleros
    kleros_df = pd.read_parquet(DATA_DIR / "kleros_holders.parquet")

    for chain in ["ethereum", "arbitrum"]:
        chain_df = kleros_df[kleros_df["chain"] == chain]
        metrics = calculate_all_metrics(chain_df["balance"].values, f"Kleros ({chain})")

        print(f"[Kleros - {chain.upper()}]")
        print(f"  샘플 수: {metrics['sample_size']}")
        print(f"  지니 계수: {metrics['gini']} ({interpret_gini(metrics['gini'])})")
        print(f"  HHI: {metrics['hhi']} ({interpret_hhi(metrics['hhi'])})")
        print(f"  나카모토 계수: {metrics['nakamoto']}")
        print(f"  정규화 엔트로피: {metrics['normalized_entropy']}")
        print()
