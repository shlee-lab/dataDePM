"""
Polymarket 가격 히스토리 수집 및 Calibration 스냅샷 추출

1. Gamma API로 clobTokenIds 수집 (resolved parquet 마켓과 매칭)
2. CLOB API로 일별 가격 시계열 수집
3. closed_time 기준 T-0, T-1d, T-7d, T-30d 가격 스냅샷 추출
"""

import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def get_session() -> requests.Session:
    """Retry 로직이 포함된 세션 생성"""
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


# ─── Step 1A: clobTokenIds 수집 ───────────────────────────────────

def fetch_clob_token_ids(max_markets: int = 15000) -> pd.DataFrame:
    """Gamma API에서 종료 마켓의 clobTokenIds 수집.

    Returns:
        DataFrame with columns: id, clob_token_id_yes
    """
    session = get_session()
    records = []
    offset = 0
    limit = 100

    print("  [1A] clobTokenIds 수집 중...", flush=True)

    while True:
        params = {
            "limit": limit,
            "offset": offset,
            "closed": "true",
        }
        try:
            resp = session.get(f"{GAMMA_API}/markets", params=params, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"    에러 (offset={offset}): {e}", flush=True)
            break

        markets = resp.json()
        if not markets:
            break

        for m in markets:
            clob_ids = m.get("clobTokenIds")
            if clob_ids:
                # clobTokenIds는 JSON 문자열 또는 리스트
                if isinstance(clob_ids, str):
                    try:
                        clob_ids = json.loads(clob_ids)
                    except Exception:
                        continue
                if isinstance(clob_ids, list) and len(clob_ids) > 0:
                    records.append({
                        "id": m.get("id"),
                        "clob_token_id_yes": clob_ids[0],  # first = Yes outcome
                    })

        offset += limit
        if len(records) % 1000 < limit:
            print(f"    {len(records)} 마켓 수집...", flush=True)

        if max_markets and offset >= max_markets:
            break

        time.sleep(0.3)

    print(f"    완료: {len(records)} 마켓의 clobTokenId 확보", flush=True)
    return pd.DataFrame(records)


# ─── Step 1B: 가격 히스토리 수집 ──────────────────────────────────

def fetch_price_history(clob_token_id: str, session: requests.Session) -> list:
    """단일 마켓의 일별 가격 시계열 수집.

    Returns:
        list of {t: unix_timestamp, p: price}
    """
    url = f"{CLOB_API}/prices-history"
    params = {
        "market": clob_token_id,
        "interval": "all",
        "fidelity": 1440,  # 일별
    }
    try:
        resp = session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "history" in data:
            return data["history"]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def collect_price_histories(target_df: pd.DataFrame) -> pd.DataFrame:
    """대상 마켓들의 가격 히스토리 일괄 수집.

    Args:
        target_df: must have columns [id, clob_token_id_yes]

    Returns:
        DataFrame with columns: market_id, t, p
    """
    session = get_session()
    all_rows = []
    total = len(target_df)
    success = 0
    empty = 0

    print(f"  [1B] 가격 히스토리 수집 중... ({total} 마켓)", flush=True)

    for i, row in target_df.iterrows():
        market_id = row["id"]
        clob_id = row["clob_token_id_yes"]

        history = fetch_price_history(clob_id, session)

        if history:
            for point in history:
                all_rows.append({
                    "market_id": market_id,
                    "t": int(point.get("t", 0)),
                    "p": float(point.get("p", 0)),
                })
            success += 1
        else:
            empty += 1

        if (success + empty) % 100 == 0:
            print(f"    진행: {success + empty}/{total} (성공: {success}, 빈 히스토리: {empty})", flush=True)

        time.sleep(0.3)

    print(f"    완료: {success} 마켓 히스토리, {len(all_rows)} 데이터포인트", flush=True)
    return pd.DataFrame(all_rows)


# ─── Step 1C: 가격 스냅샷 추출 ───────────────────────────────────

def extract_snapshots(
    history_df: pd.DataFrame,
    resolved_df: pd.DataFrame,
) -> pd.DataFrame:
    """각 마켓의 시계열에서 T-0, T-1d, T-7d, T-30d 가격 추출.

    Args:
        history_df: columns [market_id, t, p]
        resolved_df: columns [id, resolution, volume, category, closed_time, outcomes]

    Returns:
        DataFrame with calibration snapshot per market
    """
    print("  [1C] 가격 스냅샷 추출 중...", flush=True)

    # Yes/No 마켓만 필터 + resolution이 Yes 또는 No인 것만
    yesno = resolved_df[resolved_df["outcomes"] == '["Yes", "No"]'].copy()
    yesno = yesno[yesno["resolution"].isin(["Yes", "No"])].copy()

    # closed_time을 unix timestamp로 변환 (datetime64[us] -> int64)
    yesno["closed_ts"] = pd.to_datetime(yesno["closed_time"], format="mixed", utc=True).astype('int64') // 10**6
    yesno["resolution_binary"] = (yesno["resolution"] == "Yes").astype(int)

    # 히스토리가 있는 마켓만
    markets_with_history = set(history_df["market_id"].unique())
    yesno = yesno[yesno["id"].isin(markets_with_history)]

    offsets = {
        "price_t0": 0,             # 마지막 가격 (해결 당일)
        "price_t1d": 86400,        # 1일 전
        "price_t7d": 7 * 86400,    # 7일 전
        "price_t30d": 30 * 86400,  # 30일 전
    }

    records = []
    for _, mkt in yesno.iterrows():
        mkt_id = mkt["id"]
        closed_ts = mkt["closed_ts"]

        # 해당 마켓의 가격 시계열
        mkt_hist = history_df[history_df["market_id"] == mkt_id].copy()
        if mkt_hist.empty:
            continue

        timestamps = mkt_hist["t"].values
        prices = mkt_hist["p"].values

        row = {
            "market_id": mkt_id,
            "resolution": mkt["resolution"],
            "resolution_binary": mkt["resolution_binary"],
            "volume": mkt["volume"],
            "category": mkt["category"],
            "closed_time": mkt["closed_time"],
        }

        for col, offset_secs in offsets.items():
            target_ts = closed_ts - offset_secs
            # 가장 가까운 데이터포인트 (target_ts 이전만)
            mask = timestamps <= target_ts
            if mask.any():
                idx = np.argmin(np.abs(timestamps[mask] - target_ts))
                row[col] = float(prices[mask][idx])
            else:
                row[col] = None

        records.append(row)

    result = pd.DataFrame(records)
    print(f"    완료: {len(result)} 마켓 스냅샷 ({result['price_t0'].notna().sum()} T-0, "
          f"{result['price_t7d'].notna().sum()} T-7d, {result['price_t30d'].notna().sum()} T-30d)")
    return result


# ─── Main ─────────────────────────────────────────────────────────

def main():
    print("=== Polymarket 가격 데이터 수집 시작 ===", flush=True)
    print(f"시간: {datetime.now().isoformat()}\n", flush=True)

    # 기존 resolved 데이터 로드
    resolved_path = DATA_DIR / "polymarket_resolved.parquet"
    if not resolved_path.exists():
        print("ERROR: polymarket_resolved.parquet이 없습니다. 먼저 polymarket.py를 실행하세요.", flush=True)
        return

    resolved_df = pd.read_parquet(resolved_path)
    print(f"종료 마켓 로드: {len(resolved_df)}건", flush=True)

    # 2023+ Yes/No 마켓만 대상
    resolved_df["year"] = pd.to_datetime(
        resolved_df["created_at"], format="ISO8601"
    ).dt.year
    target_resolved = resolved_df[
        (resolved_df["year"] >= 2023)
        & (resolved_df["outcomes"] == '["Yes", "No"]')
    ].copy()
    print(f"대상 마켓 (2023+ Yes/No): {len(target_resolved)}건\n", flush=True)

    # Step 1A: clobTokenIds 수집
    clob_ids_path = DATA_DIR / "polymarket_clob_ids.parquet"
    if clob_ids_path.exists():
        print("  [1A] 기존 clobTokenIds 파일 사용", flush=True)
        clob_df = pd.read_parquet(clob_ids_path)
    else:
        clob_df = fetch_clob_token_ids()
        clob_df.to_parquet(clob_ids_path, index=False)
        print(f"  저장: {clob_ids_path} ({len(clob_df)} rows)\n", flush=True)

    # 대상 마켓과 매칭
    target_with_clob = target_resolved.merge(clob_df, on="id", how="inner")
    print(f"clobTokenId 매칭 마켓: {len(target_with_clob)}건\n", flush=True)

    if target_with_clob.empty:
        print("ERROR: 매칭된 마켓이 없습니다.", flush=True)
        return

    # Step 1B: 가격 히스토리 수집
    history_path = DATA_DIR / "polymarket_price_history.parquet"
    if history_path.exists():
        print("  [1B] 기존 가격 히스토리 파일 사용", flush=True)
        history_df = pd.read_parquet(history_path)
    else:
        history_df = collect_price_histories(target_with_clob[["id", "clob_token_id_yes"]])
        if not history_df.empty:
            history_df.to_parquet(history_path, index=False)
            print(f"  저장: {history_path} ({len(history_df)} rows)\n", flush=True)
        else:
            print("ERROR: 가격 히스토리 수집 실패", flush=True)
            return

    # Step 1C: 스냅샷 추출
    snapshot_df = extract_snapshots(history_df, resolved_df)
    if not snapshot_df.empty:
        snapshot_path = DATA_DIR / "polymarket_calibration_snapshots.parquet"
        snapshot_df.to_parquet(snapshot_path, index=False)
        print(f"  저장: {snapshot_path} ({len(snapshot_df)} rows)", flush=True)

        # CSV도 site/에 저장
        site_dir = Path(__file__).parent.parent / "site"
        site_dir.mkdir(exist_ok=True)
        snapshot_df.to_csv(site_dir / "calibration_snapshots.csv", index=False)
        print(f"  CSV 저장: site/calibration_snapshots.csv", flush=True)

    print("\n=== 수집 완료 ===", flush=True)


if __name__ == "__main__":
    main()
