"""
Kleros 오라클 데이터 수집 (Etherscan API V2)
- Ethereum: PNK 토큰 전체 홀더 분포
- Arbitrum: Kleros v2 Court 스테이킹 분포
"""

import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Etherscan API V2
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")
ETHERSCAN_API = "https://api.etherscan.io/v2/api"

# PNK 토큰 컨트랙트
CHAINS = {
    "ethereum": {
        "chainid": 1,
        "pnk_token": "0x93ed3fbe21207ec2e8f2d3c3de6e058cb73bc04d",
        "name": "Ethereum Mainnet"
    },
    "arbitrum": {
        "chainid": 42161,
        "pnk_token": "0x330bD769382cFc6d50175903434CCC8D206DCAE5",
        "name": "Arbitrum One (v2 Court)"
    }
}


def etherscan_request(params: dict, chainid: int) -> dict:
    """Etherscan API V2 요청"""
    params["apikey"] = ETHERSCAN_API_KEY
    params["chainid"] = chainid

    response = requests.get(ETHERSCAN_API, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    if data.get("status") == "0" and "rate limit" in data.get("message", "").lower():
        print("  Rate limit 도달, 5초 대기...")
        time.sleep(5)
        return etherscan_request(params, chainid)

    return data


def collect_token_holders(chain_key: str) -> pd.DataFrame:
    """PNK 토큰 홀더 수집"""

    chain = CHAINS[chain_key]
    print(f"  [{chain['name']}] 토큰 전송 이벤트에서 홀더 추출 중...")

    # 최근 토큰 전송 이벤트 수집
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": chain["pnk_token"],
        "page": 1,
        "offset": 10000,
        "sort": "desc"
    }

    result = etherscan_request(params, chain["chainid"])

    if result.get("status") != "1":
        print(f"  에러: {result.get('message')} - {result.get('result')}")
        return pd.DataFrame()

    transfers = result.get("result", [])
    print(f"  {len(transfers)}개 전송 이벤트 수집됨")

    # 주소별 최근 활동 집계
    address_activity = {}
    for tx in transfers:
        for addr in [tx.get("from"), tx.get("to")]:
            if addr and addr.lower() != "0x0000000000000000000000000000000000000000":
                addr_lower = addr.lower()
                if addr_lower not in address_activity:
                    address_activity[addr_lower] = {"tx_count": 0, "last_active": 0}
                address_activity[addr_lower]["tx_count"] += 1
                address_activity[addr_lower]["last_active"] = max(
                    address_activity[addr_lower]["last_active"],
                    int(tx.get("timeStamp", 0))
                )

    # 활성 주소 상위 100개의 잔액 조회
    active_addresses = sorted(
        address_activity.items(),
        key=lambda x: x[1]["tx_count"],
        reverse=True
    )[:100]

    print(f"  상위 {len(active_addresses)}개 활성 주소 잔액 조회 중...")

    holders = []
    for i, (address, activity) in enumerate(active_addresses):
        params = {
            "module": "account",
            "action": "tokenbalance",
            "contractaddress": chain["pnk_token"],
            "address": address,
            "tag": "latest"
        }

        result = etherscan_request(params, chain["chainid"])

        if result.get("status") == "1":
            balance = int(result.get("result", 0)) / 1e18  # Wei to PNK
            if balance > 0:
                holders.append({
                    "address": address,
                    "balance": balance,
                    "tx_count": activity["tx_count"],
                    "last_active": datetime.fromtimestamp(activity["last_active"]).isoformat(),
                    "chain": chain_key
                })

        if (i + 1) % 10 == 0:
            print(f"    {i + 1}/{len(active_addresses)} 완료")

        time.sleep(0.25)  # Rate limit 방지

    df = pd.DataFrame(holders)
    if not df.empty:
        df = df.sort_values("balance", ascending=False).reset_index(drop=True)

    return df


def analyze_holder_concentration(holders_df: pd.DataFrame, chain_name: str) -> dict:
    """홀더 집중도 분석"""

    if holders_df.empty:
        return {}

    total_balance = holders_df["balance"].sum()

    top5 = holders_df.head(5)["balance"].sum()
    top10 = holders_df.head(10)["balance"].sum()
    top20 = holders_df.head(20)["balance"].sum()

    return {
        "chain": chain_name,
        "total_sampled_balance": total_balance,
        "holder_count": len(holders_df),
        "top5_share": top5 / total_balance * 100 if total_balance > 0 else 0,
        "top10_share": top10 / total_balance * 100 if total_balance > 0 else 0,
        "top20_share": top20 / total_balance * 100 if total_balance > 0 else 0,
        "top5_balance": top5,
        "top10_balance": top10,
    }


def save_data(df: pd.DataFrame, name: str):
    """Parquet으로 저장"""
    path = DATA_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"Saved: {path} ({len(df)} rows)")


def main():
    print("=== Kleros 오라클 데이터 수집 시작 ===")
    print(f"시간: {datetime.now().isoformat()}")

    all_holders = []
    all_stats = []

    for i, (chain_key, chain_info) in enumerate(CHAINS.items(), 1):
        print(f"\n[{i}/{len(CHAINS)}] {chain_info['name']} 수집 중...")

        holders_df = collect_token_holders(chain_key)

        if not holders_df.empty:
            all_holders.append(holders_df)

            # 집중도 분석
            stats = analyze_holder_concentration(holders_df, chain_info['name'])
            all_stats.append(stats)

            print(f"\n  --- {chain_info['name']} 집중도 ---")
            print(f"  샘플 홀더 수: {stats['holder_count']}")
            print(f"  샘플 총 잔액: {stats['total_sampled_balance']:,.0f} PNK")
            print(f"  상위 5명 점유율: {stats['top5_share']:.1f}%")
            print(f"  상위 10명 점유율: {stats['top10_share']:.1f}%")

    # 전체 데이터 저장
    if all_holders:
        combined_df = pd.concat(all_holders, ignore_index=True)
        save_data(combined_df, "kleros_holders")

    if all_stats:
        stats_df = pd.DataFrame(all_stats)
        stats_df["collected_at"] = datetime.now().isoformat()
        save_data(stats_df, "kleros_holder_stats")

    print("\n=== 수집 완료 ===")


if __name__ == "__main__":
    main()
