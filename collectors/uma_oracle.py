"""
UMA 오라클 데이터 수집 (Etherscan API)
- 토큰 홀더 분포
- 투표 컨트랙트 이벤트
"""

import json
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
CHAIN_ID = 1  # Ethereum mainnet

# UMA 토큰 컨트랙트 (Ethereum mainnet)
UMA_TOKEN = "0x04Fa0d235C4abf4BcF4787aF4CF447DE572eF828"

# UMA Voting 컨트랙트
UMA_VOTING = "0x8b1631ab830d11531ae83725fda4d86012eccd77"


def etherscan_request(params: dict) -> dict:
    """Etherscan API V2 요청"""
    params["apikey"] = ETHERSCAN_API_KEY
    params["chainid"] = CHAIN_ID

    response = requests.get(ETHERSCAN_API, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    if data.get("status") == "0" and "rate limit" in data.get("message", "").lower():
        print("  Rate limit 도달, 5초 대기...")
        time.sleep(5)
        return etherscan_request(params)

    return data


def collect_token_holders() -> pd.DataFrame:
    """UMA 토큰 상위 홀더 수집 (토큰 전송 이벤트 분석)"""

    print("  토큰 전송 이벤트에서 홀더 추출 중...")

    # 최근 토큰 전송 이벤트 수집
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": UMA_TOKEN,
        "page": 1,
        "offset": 10000,
        "sort": "desc"
    }

    result = etherscan_request(params)

    if result.get("status") != "1":
        print(f"  에러: {result.get('message')}")
        return pd.DataFrame()

    transfers = result.get("result", [])
    print(f"  {len(transfers)}개 전송 이벤트 수집됨")

    # 주소별 최근 활동 집계
    address_activity = {}
    for tx in transfers:
        for addr in [tx.get("from"), tx.get("to")]:
            if addr and addr != "0x0000000000000000000000000000000000000000":
                if addr not in address_activity:
                    address_activity[addr] = {"tx_count": 0, "last_active": 0}
                address_activity[addr]["tx_count"] += 1
                address_activity[addr]["last_active"] = max(
                    address_activity[addr]["last_active"],
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
            "contractaddress": UMA_TOKEN,
            "address": address,
            "tag": "latest"
        }

        result = etherscan_request(params)

        if result.get("status") == "1":
            balance = int(result.get("result", 0)) / 1e18  # Wei to UMA
            if balance > 0:
                holders.append({
                    "address": address,
                    "balance": balance,
                    "tx_count": activity["tx_count"],
                    "last_active": datetime.fromtimestamp(activity["last_active"]).isoformat()
                })

        if (i + 1) % 10 == 0:
            print(f"    {i + 1}/{len(active_addresses)} 완료")

        time.sleep(0.25)  # Rate limit 방지

    df = pd.DataFrame(holders)
    if not df.empty:
        df = df.sort_values("balance", ascending=False).reset_index(drop=True)

    return df


# topic0 해시 → 이벤트 이름 매핑 (keccak256 of event signatures)
UMA_EVENT_NAMES = {
    "0x8be0079c531659141344cd1fd0a4f28419497f9722a3daafe3b4186f6b6457e0": "OwnershipTransferred",
    "0x5d80f93c41e95cacea0b9ce9bb825092d709fa503a70bb26ea3f536bf16946bd": "PriceRequestAdded",
    "0x6beca723245953d9ed92ae4d320d4772838e841161bfff12c78ae4268df525eb": "VoteCommitted",
    "0x0296c44e55ad4a025c9701a71c746d4275d63dfe301e390a7429551010a8fea1": "EncryptedVote",
    "0x3fad5d37ee1be2f58ff1735699121a8ead73c3b70d02fc06d07b0db29854d3b4": "VoteRevealed",
    "0xb1f1bf5aec084730c2c09f66ae2099185eaf6f951ddc113a19aa886a9f5e71b7": "PriceResolved",
    "0x6fb9765a6e4b0dd2aaedad44f9b165a2a64a53ce67a6ec812075faa9220d41bc": "RewardsRetrieved",
}

# UMA Voting 첫 이벤트 블록 (2021-02-17)
UMA_VOTING_START_BLOCK = 11876839
# 블록 범위 청크 사이즈
BLOCK_CHUNK_SIZE = 50000


def collect_voting_events() -> pd.DataFrame:
    """UMA Voting 컨트랙트 이벤트 수집 (블록 범위 페이징)"""

    print("  Voting 컨트랙트 이벤트 수집 중 (블록 범위 페이징)...")

    # 현재 최신 블록 번호 조회
    latest_result = etherscan_request({
        "module": "proxy",
        "action": "eth_blockNumber",
    })
    latest_block = int(latest_result.get("result", "0x0"), 16)
    print(f"  최신 블록: {latest_block:,}")

    all_records = []
    from_block = UMA_VOTING_START_BLOCK

    while from_block <= latest_block:
        to_block = min(from_block + BLOCK_CHUNK_SIZE - 1, latest_block)

        # 각 청크 내에서 페이지 반복
        page = 1
        while True:
            params = {
                "module": "logs",
                "action": "getLogs",
                "address": UMA_VOTING,
                "fromBlock": from_block,
                "toBlock": to_block,
                "page": page,
                "offset": 1000,
            }

            result = etherscan_request(params)

            if result.get("status") != "1":
                # "No records found" 등은 정상 — 해당 범위에 이벤트 없음
                break

            events = result.get("result", [])
            if not events:
                break

            for event in events:
                topic0 = event.get("topics", [None])[0]
                all_records.append({
                    "block_number": int(event.get("blockNumber", "0"), 16),
                    "timestamp": int(event.get("timeStamp", "0"), 16),
                    "tx_hash": event.get("transactionHash"),
                    "topic0": topic0,
                    "event_name": UMA_EVENT_NAMES.get(topic0, "Unknown"),
                    "topics": json.dumps(event.get("topics", [])),
                    "data": event.get("data"),
                })

            # 1,000건 미만이면 다음 청크로
            if len(events) < 1000:
                break
            page += 1
            time.sleep(0.25)

        print(f"  Collected up to block {to_block:,}, total events: {len(all_records):,}")
        from_block = to_block + 1
        time.sleep(0.25)  # Rate limit 방지

    df = pd.DataFrame(all_records)
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")

    return df


def analyze_holder_concentration(holders_df: pd.DataFrame) -> dict:
    """홀더 집중도 분석"""

    if holders_df.empty:
        return {}

    total_balance = holders_df["balance"].sum()

    top5 = holders_df.head(5)["balance"].sum()
    top10 = holders_df.head(10)["balance"].sum()
    top20 = holders_df.head(20)["balance"].sum()

    return {
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
    print("=== UMA 오라클 데이터 수집 시작 ===")
    print(f"시간: {datetime.now().isoformat()}")

    print("\n[1/2] 토큰 홀더 분포 수집 중...")
    holders_df = collect_token_holders()

    if not holders_df.empty:
        save_data(holders_df, "uma_holders")

        # 집중도 분석
        print("\n--- 토큰 홀더 집중도 분석 ---")
        stats = analyze_holder_concentration(holders_df)
        print(f"  샘플 홀더 수: {stats['holder_count']}")
        print(f"  샘플 총 잔액: {stats['total_sampled_balance']:,.0f} UMA")
        print(f"  상위 5명 점유율: {stats['top5_share']:.1f}%")
        print(f"  상위 10명 점유율: {stats['top10_share']:.1f}%")
        print(f"  상위 20명 점유율: {stats['top20_share']:.1f}%")

        # 통계도 저장
        stats_df = pd.DataFrame([stats])
        stats_df["collected_at"] = datetime.now().isoformat()
        save_data(stats_df, "uma_holder_stats")

    print("\n[2/2] Voting 이벤트 수집 중...")
    events_df = collect_voting_events()
    if not events_df.empty:
        save_data(events_df, "uma_voting_events")

    print("\n=== 수집 완료 ===")


if __name__ == "__main__":
    main()
