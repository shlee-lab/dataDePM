"""
Kleros 오라클 데이터 수집 (Etherscan API V2)
- Ethereum: PNK 토큰 전체 홀더 분포
- Arbitrum: Kleros v2 Court 스테이킹 분포
- Arbitrum: Kleros v2 Court 분쟁 이벤트 (DisputeCreation, Draw, VoteCast, Ruling 등)
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


# Kleros v2 Court 컨트랙트 (Arbitrum)
KLEROS_CORE = "0x991d2df165670b9cac3B022f4B68D65b664222ea"
DISPUTE_KIT_CLASSIC = "0x70B464be85A547144C72485eBa2577E5D3A45421"
ARBITRUM_CHAIN_ID = 42161

# topic0 해시 → 이벤트 이름 매핑 (keccak256 of event signatures)
KLEROS_EVENT_NAMES = {
    # KlerosCore events
    "0x141dfc18aa6a56fc816f44f0e9e2f1ebc92b15ab167770e17db5b084c10ed995": "DisputeCreation",
    "0x6119cf536152c11e0a9a6c22f3953ce4ecc93ee54fa72ffa326ffabded21509b": "Draw",
    "0x394027a5fa6e098a1191094d1719d6929b9abc535fcc0c8f448d6a4e75622276": "Ruling",
    "0x4e6f5cf43b95303e86aee81683df63992061723a829ee012db21dad388756b91": "NewPeriod",
    "0xa5d41b970d849372be1da1481ffd78d162bfe57a7aa2fe4e5fb73481fa5ac24f": "AppealPossible",
    "0x8975b837fe0d18616c65abb8b843726a32b552ee4feca009944fa658bbb282e7": "TokenAndETHShift",
    # DisputeKitClassic events
    "0xa000893c71384499023d2d7b21234f7b9e80c78e0330f357dcd667ff578bd3a4": "VoteCast",
    "0xd3106f74c2d30a4b9230e756a3e78bde53865d40f6af4c479bb010ebaab58108": "DisputeCreation",
}

# Kleros v2 Court 배포 블록 (Arbitrum, 2024-11-07)
KLEROS_COURT_START_BLOCK = 272000000
BLOCK_CHUNK_SIZE = 5000000  # Arbitrum 블록이 빠르므로 큰 청크


def collect_court_events_for_contract(contract_address: str, contract_name: str) -> list:
    """특정 컨트랙트의 이벤트를 블록 범위 페이징으로 수집"""

    print(f"  [{contract_name}] 이벤트 수집 중...")

    # Arbitrum 최신 블록 조회
    latest_result = etherscan_request({
        "module": "proxy",
        "action": "eth_blockNumber",
    }, ARBITRUM_CHAIN_ID)
    latest_block = int(latest_result.get("result", "0x0"), 16)
    print(f"  최신 블록: {latest_block:,}")

    all_records = []
    from_block = KLEROS_COURT_START_BLOCK

    while from_block <= latest_block:
        to_block = min(from_block + BLOCK_CHUNK_SIZE - 1, latest_block)

        page = 1
        while True:
            params = {
                "module": "logs",
                "action": "getLogs",
                "address": contract_address,
                "fromBlock": from_block,
                "toBlock": to_block,
                "page": page,
                "offset": 1000,
            }

            result = etherscan_request(params, ARBITRUM_CHAIN_ID)

            if result.get("status") != "1":
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
                    "contract": contract_name,
                    "topic0": topic0,
                    "event_name": KLEROS_EVENT_NAMES.get(topic0, "Unknown"),
                    "topics": json.dumps(event.get("topics", [])),
                    "data": event.get("data"),
                })

            if len(events) < 1000:
                break
            page += 1
            time.sleep(0.25)

        print(f"  [{contract_name}] Collected up to block {to_block:,}, total events: {len(all_records):,}")
        from_block = to_block + 1
        time.sleep(0.25)

    return all_records


def collect_court_events() -> pd.DataFrame:
    """Kleros v2 Court 분쟁 이벤트 수집 (KlerosCore + DisputeKitClassic)"""

    print("\n  Court 분쟁 이벤트 수집 시작...")

    records = []
    records.extend(collect_court_events_for_contract(KLEROS_CORE, "KlerosCore"))
    records.extend(collect_court_events_for_contract(DISPUTE_KIT_CLASSIC, "DisputeKitClassic"))

    df = pd.DataFrame(records)
    if not df.empty:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        df = df.sort_values("block_number").reset_index(drop=True)

    print(f"  Court 이벤트 총 {len(df):,}건 수집 완료")
    return df


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

    # Court 분쟁 이벤트 수집
    print(f"\n[{len(CHAINS) + 1}/{len(CHAINS) + 1}] Court 분쟁 이벤트 수집 중...")
    court_df = collect_court_events()
    if not court_df.empty:
        save_data(court_df, "kleros_court_events")

    print("\n=== 수집 완료 ===")


if __name__ == "__main__":
    main()
