"""
Polymarket 데이터 수집 (공식 API)
- 마켓 데이터 (TVL, 거래량)
- 거래 내역 (wash trading 분석용)

API 문서: https://docs.polymarket.com/
"""

import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Polymarket API 엔드포인트
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


def get_session() -> requests.Session:
    """Retry 로직이 포함된 세션 생성"""
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


def fetch_all_markets(closed: bool = False, max_markets: int = 5000) -> list:
    """마켓 데이터 수집 (페이지네이션)

    Args:
        closed: True면 종료된 마켓, False면 진행중인 마켓
        max_markets: 최대 수집 마켓 수 (API 부하 방지)
    """

    session = get_session()
    all_markets = []
    offset = 0
    limit = 100

    base_url = f"{GAMMA_API}/markets"
    params = {
        "limit": limit,
        "closed": str(closed).lower(),
    }

    while True:
        params["offset"] = offset

        try:
            response = session.get(base_url, params=params, timeout=30)
            response.raise_for_status()
        except Exception as e:
            print(f"  에러 발생 (offset={offset}): {e}")
            print(f"  현재까지 수집: {len(all_markets)} 마켓")
            break

        markets = response.json()
        if not markets:
            break

        all_markets.extend(markets)
        offset += limit

        print(f"  수집 중... {len(all_markets)} 마켓")

        if max_markets and len(all_markets) >= max_markets:
            print(f"  최대 수집 수 도달 ({max_markets})")
            break

        time.sleep(0.3)

    return all_markets


def fetch_market_trades(clob_token_id: str, limit: int = 500) -> list:
    """특정 마켓의 거래 내역 수집"""

    url = f"{CLOB_API}/trades"
    params = {
        "asset_id": clob_token_id,
        "limit": limit
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return []


def collect_markets(closed: bool = False) -> pd.DataFrame:
    """마켓 데이터 수집 및 정리"""

    markets = fetch_all_markets(closed=closed)

    records = []
    for m in markets:
        records.append({
            "id": m.get("id"),
            "question": m.get("question"),
            "slug": m.get("slug"),
            "category": m.get("category"),
            "end_date": m.get("endDate"),
            "created_at": m.get("createdAt"),
            "volume": float(m.get("volume", 0) or 0),
            "liquidity": float(m.get("liquidity", 0) or 0),
            "volume_24hr": float(m.get("volume24hr", 0) or 0),
            "volume_1wk": float(m.get("volume1wk", 0) or 0),
            "volume_1mo": float(m.get("volume1mo", 0) or 0),
            "active": m.get("active"),
            "closed": m.get("closed"),
            "outcomes": m.get("outcomes"),
            "outcome_prices": m.get("outcomePrices"),
        })

    df = pd.DataFrame(records)
    return df


def collect_trades_sample(markets_df: pd.DataFrame, sample_size: int = 50) -> pd.DataFrame:
    """상위 마켓들의 거래 내역 샘플 수집"""

    # 거래량 상위 마켓 선택
    top_markets = markets_df.nlargest(sample_size, "volume")

    all_trades = []
    for idx, row in top_markets.iterrows():
        # clobTokenIds 파싱 시도
        try:
            market_id = row["id"]
            trades = fetch_market_trades(market_id)

            for t in trades:
                t["market_id"] = market_id
                t["market_question"] = row["question"]
                all_trades.append(t)

            print(f"  [{len(all_trades)}] {row['question'][:50]}...")
            time.sleep(0.3)
        except Exception as e:
            continue

    if all_trades:
        return pd.DataFrame(all_trades)
    return pd.DataFrame()


def analyze_liquidity(markets_df: pd.DataFrame) -> dict:
    """유동성 집중도 분석"""

    total_volume = markets_df["volume"].sum()
    total_liquidity = markets_df["liquidity"].sum()

    # 상위 N개 마켓 점유율
    top10_volume = markets_df.nlargest(10, "volume")["volume"].sum()
    top20_volume = markets_df.nlargest(20, "volume")["volume"].sum()
    top50_volume = markets_df.nlargest(50, "volume")["volume"].sum()

    top10_liquidity = markets_df.nlargest(10, "liquidity")["liquidity"].sum()

    # 활성 마켓 수
    active_markets = markets_df[markets_df["active"] == True]
    liquid_markets = markets_df[markets_df["liquidity"] > 10000]  # $10K 이상

    return {
        "total_markets": len(markets_df),
        "active_markets": len(active_markets),
        "liquid_markets_10k": len(liquid_markets),
        "total_volume_usd": total_volume,
        "total_liquidity_usd": total_liquidity,
        "top10_volume_share": top10_volume / total_volume * 100 if total_volume > 0 else 0,
        "top20_volume_share": top20_volume / total_volume * 100 if total_volume > 0 else 0,
        "top50_volume_share": top50_volume / total_volume * 100 if total_volume > 0 else 0,
        "top10_liquidity_share": top10_liquidity / total_liquidity * 100 if total_liquidity > 0 else 0,
    }


def save_data(df: pd.DataFrame, name: str):
    """Parquet으로 저장"""
    path = DATA_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"Saved: {path} ({len(df)} rows)")


def main():
    print("=== Polymarket 데이터 수집 시작 ===")
    print(f"시간: {datetime.now().isoformat()}")

    # 진행중인 마켓만 수집 (closed=False)
    print("\n[1/2] 진행중인 마켓 데이터 수집 중 (최대 5000개)...")
    markets_df = collect_markets(closed=False)
    save_data(markets_df, "polymarket_markets")

    # 유동성 분석 출력
    print("\n--- 유동성 집중도 분석 ---")
    stats = analyze_liquidity(markets_df)
    print(f"  전체 마켓 수: {stats['total_markets']}")
    print(f"  활성 마켓 수: {stats['active_markets']}")
    print(f"  유동성 $10K 이상: {stats['liquid_markets_10k']}")
    print(f"  총 거래량: ${stats['total_volume_usd']:,.0f}")
    print(f"  총 유동성: ${stats['total_liquidity_usd']:,.0f}")
    print(f"  상위 10개 거래량 점유율: {stats['top10_volume_share']:.1f}%")
    print(f"  상위 20개 거래량 점유율: {stats['top20_volume_share']:.1f}%")
    print(f"  상위 10개 유동성 점유율: {stats['top10_liquidity_share']:.1f}%")

    # 분석 결과도 저장
    stats_df = pd.DataFrame([stats])
    stats_df["collected_at"] = datetime.now().isoformat()
    save_data(stats_df, "polymarket_liquidity_stats")

    print("\n[2/2] 거래 내역 샘플 수집 중...")
    trades_df = collect_trades_sample(markets_df, sample_size=30)
    if not trades_df.empty:
        save_data(trades_df, "polymarket_trades")
    else:
        print("  거래 내역 수집 실패 (API 제한일 수 있음)")

    print("\n=== 수집 완료 ===")


if __name__ == "__main__":
    main()
