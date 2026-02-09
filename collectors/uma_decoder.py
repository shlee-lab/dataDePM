"""
UMA raw hex 이벤트 디코딩

기존 uma_voting_events.parquet의 raw topics/data 필드를 디코딩하여:
- uma_decoded_requests.parquet: PriceRequest + PriceResolved 매칭
- uma_decoded_votes.parquet: VoteRevealed 디코딩
"""

import json
import struct
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"


def hex_to_int(hex_str: str, signed: bool = False) -> int:
    """32바이트 hex를 정수로 변환"""
    hex_str = hex_str.replace("0x", "").strip()
    if len(hex_str) > 64:
        hex_str = hex_str[:64]
    value = int(hex_str, 16)
    if signed and value >= 2**255:
        value -= 2**256
    return value


def hex_to_ascii(hex_str: str) -> str:
    """hex를 ASCII 문자열로 변환 (null 바이트 제거)"""
    hex_str = hex_str.replace("0x", "").strip()
    try:
        raw = bytes.fromhex(hex_str)
        return raw.rstrip(b"\x00").decode("ascii", errors="replace").strip()
    except Exception:
        return hex_str


def hex_to_address(hex_str: str) -> str:
    """32바이트 패딩된 hex를 이더리움 주소로 변환"""
    hex_str = hex_str.replace("0x", "").strip()
    # 마지막 40자가 주소
    return "0x" + hex_str[-40:]


def decode_data_fields(data_hex: str) -> list:
    """data 필드를 32바이트 청크로 분할"""
    data = data_hex.replace("0x", "")
    chunks = []
    for i in range(0, len(data), 64):
        chunk = data[i:i+64]
        if chunk:
            chunks.append(chunk)
    return chunks


def decode_price_requests(events_df: pd.DataFrame) -> pd.DataFrame:
    """PriceRequestAdded 이벤트 디코딩

    Event: PriceRequestAdded(uint256 indexed roundId, bytes32 indexed identifier, uint256 time)
    topics[1] = roundId
    topics[2] = identifier (bytes32, ASCII 인코딩)
    data[0:32] = timestamp
    """
    requests = events_df[events_df["event_name"] == "PriceRequestAdded"].copy()

    records = []
    for _, row in requests.iterrows():
        topics = json.loads(row["topics"])
        data_chunks = decode_data_fields(row["data"])

        round_id = hex_to_int(topics[1])
        identifier = hex_to_ascii(topics[2])
        request_time = hex_to_int(data_chunks[0]) if data_chunks else row["timestamp"]

        records.append({
            "round_id": round_id,
            "identifier": identifier,
            "request_time": request_time,
            "block_number": row["block_number"],
            "tx_hash": row["tx_hash"],
        })

    return pd.DataFrame(records)


def decode_price_resolved(events_df: pd.DataFrame) -> pd.DataFrame:
    """PriceResolved 이벤트 디코딩

    Event: PriceResolved(uint256 indexed roundId, bytes32 indexed identifier, uint256 time, int256 price, bytes ancillaryData)
    topics[1] = roundId
    topics[2] = identifier
    data[0:32] = timestamp
    data[32:64] = resolvedPrice (int256)
    data[64:96] = offset to ancillaryData
    data[96:128] = length of ancillaryData
    data[128:] = ancillaryData bytes
    """
    resolved = events_df[events_df["event_name"] == "PriceResolved"].copy()

    records = []
    for _, row in resolved.iterrows():
        topics = json.loads(row["topics"])
        data_chunks = decode_data_fields(row["data"])

        round_id = hex_to_int(topics[1])
        identifier = hex_to_ascii(topics[2])
        resolve_time = hex_to_int(data_chunks[0]) if len(data_chunks) > 0 else row["timestamp"]
        resolved_price_raw = hex_to_int(data_chunks[1], signed=True) if len(data_chunks) > 1 else 0

        # UMA 가격은 18 decimals (1e18 = 1.0)
        resolved_price = resolved_price_raw / 1e18

        # ancillaryData 추출 (있으면)
        ancillary_data = ""
        if len(data_chunks) > 3:
            anc_len = hex_to_int(data_chunks[3])
            if anc_len > 0 and len(data_chunks) > 4:
                anc_hex = "".join(data_chunks[4:])
                try:
                    ancillary_data = bytes.fromhex(anc_hex[:anc_len*2]).decode("utf-8", errors="replace")
                except Exception:
                    ancillary_data = anc_hex[:200]

        # Classify the resolution for display
        if abs(resolved_price - 1.0) < 0.001:
            resolution_label = "Yes"
        elif abs(resolved_price) < 0.001:
            resolution_label = "No"
        elif abs(resolved_price - 0.5) < 0.001:
            resolution_label = "Indeterminate"
        elif resolved_price < -1e50:
            resolution_label = "Unresolvable"
        else:
            resolution_label = f"{resolved_price:.6f}"

        records.append({
            "round_id": round_id,
            "identifier": identifier,
            "resolve_time": resolve_time,
            "resolved_price": resolved_price,
            "resolution_label": resolution_label,
            "ancillary_data": ancillary_data,
        })

    return pd.DataFrame(records)


def decode_vote_revealed(events_df: pd.DataFrame) -> pd.DataFrame:
    """VoteRevealed 이벤트 디코딩

    Event: VoteRevealed(address indexed voter, uint256 indexed roundId, bytes32 indexed identifier, uint256 time, int256 price, bytes ancillaryData, uint256 numTokens)
    topics[1] = voter (address, padded)
    topics[2] = roundId
    topics[3] = identifier
    data[0:32] = timestamp
    data[32:64] = price (int256, 18 decimals)
    data[64:96] = offset to ancillaryData
    data[96:128] = numTokens
    data[128:160] = ancillaryData length
    data[160:] = ancillaryData bytes
    """
    reveals = events_df[events_df["event_name"] == "VoteRevealed"].copy()

    records = []
    for _, row in reveals.iterrows():
        topics = json.loads(row["topics"])
        data_chunks = decode_data_fields(row["data"])

        voter = hex_to_address(topics[1])
        round_id = hex_to_int(topics[2])
        identifier = hex_to_ascii(topics[3])

        timestamp = hex_to_int(data_chunks[0]) if len(data_chunks) > 0 else row["timestamp"]
        voted_price_raw = hex_to_int(data_chunks[1], signed=True) if len(data_chunks) > 1 else 0
        voted_price = voted_price_raw / 1e18

        num_tokens_raw = hex_to_int(data_chunks[3]) if len(data_chunks) > 3 else 0
        num_tokens = num_tokens_raw / 1e18

        # ancillaryData (if present)
        ancillary_data = ""
        if len(data_chunks) > 4:
            anc_len = hex_to_int(data_chunks[4])
            if anc_len > 0 and len(data_chunks) > 5:
                anc_hex = "".join(data_chunks[5:])
                try:
                    ancillary_data = bytes.fromhex(anc_hex[:anc_len*2]).decode("utf-8", errors="replace")
                except Exception:
                    ancillary_data = ""

        records.append({
            "round_id": round_id,
            "identifier": identifier,
            "voter": voter,
            "voted_price": voted_price,
            "num_tokens": num_tokens,
            "timestamp": timestamp,
            "ancillary_data": ancillary_data,
            "tx_hash": row["tx_hash"],
        })

    return pd.DataFrame(records)


def build_decoded_requests(requests_df: pd.DataFrame, resolved_df: pd.DataFrame, votes_df: pd.DataFrame) -> pd.DataFrame:
    """Request-Resolution 매칭 및 투표 통계 집계

    Unique key = (round_id, identifier, request_time/resolve_time).
    Since request_time and resolve_time differ, we match on (round_id, identifier, request_time)
    where resolved has a 'request_time' carried from the timestamp in the data field.
    Actually, PriceResolved data[0] = the same timestamp as PriceRequestAdded data[0].
    So we can join on (round_id, identifier, time).
    """

    # Rename resolve_time column to request_time for join (they share the same 'time' field)
    resolved_for_join = resolved_df.rename(columns={"resolve_time": "request_time"})

    # 매칭: (round_id, identifier, request_time) 기준
    merged = requests_df.merge(
        resolved_for_join[["round_id", "identifier", "request_time", "resolved_price", "resolution_label", "ancillary_data"]],
        on=["round_id", "identifier", "request_time"],
        how="left",
        suffixes=("", "_resolved")
    )

    # 투표 통계 집계: votes also have timestamp matching the request_time
    if not votes_df.empty:
        # Vote key is (round_id, identifier, timestamp) where timestamp = request_time
        vote_stats = votes_df.groupby(["round_id", "identifier", "timestamp"]).agg(
            num_voters=("voter", "nunique"),
            total_tokens=("num_tokens", "sum"),
            votes_count=("voter", "count"),
        ).reset_index().rename(columns={"timestamp": "request_time"})

        # 다수파 비율 (합의 강도) 계산
        consensus_records = []
        for (rid, ident, ts), group in votes_df.groupby(["round_id", "identifier", "timestamp"]):
            # 토큰 가중 다수파 비율
            price_tokens = group.groupby("voted_price")["num_tokens"].sum()
            if price_tokens.sum() > 0:
                majority_share = price_tokens.max() / price_tokens.sum()
            else:
                majority_share = 0
            consensus_records.append({
                "round_id": rid,
                "identifier": ident,
                "request_time": ts,
                "consensus_rate": round(majority_share, 4),
            })
        consensus_df = pd.DataFrame(consensus_records)

        merged = merged.merge(vote_stats, on=["round_id", "identifier", "request_time"], how="left")
        merged = merged.merge(consensus_df, on=["round_id", "identifier", "request_time"], how="left")
    else:
        merged["num_voters"] = 0
        merged["total_tokens"] = 0
        merged["votes_count"] = 0
        merged["consensus_rate"] = 0

    return merged


def save_data(df: pd.DataFrame, name: str):
    path = DATA_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"Saved: {path} ({len(df)} rows)")


def main():
    print("=== UMA 이벤트 디코딩 시작 ===")

    events_path = DATA_DIR / "uma_voting_events.parquet"
    if not events_path.exists():
        print(f"Error: {events_path} not found. Run uma_oracle.py first.")
        return

    events_df = pd.read_parquet(events_path)
    print(f"Loaded {len(events_df)} raw events")

    # 디코딩
    print("\n[1/3] PriceRequestAdded 디코딩...")
    requests_df = decode_price_requests(events_df)
    print(f"  {len(requests_df)} requests decoded")

    print("\n[2/3] PriceResolved 디코딩...")
    resolved_df = decode_price_resolved(events_df)
    print(f"  {len(resolved_df)} resolutions decoded")

    print("\n[3/3] VoteRevealed 디코딩...")
    votes_df = decode_vote_revealed(events_df)
    print(f"  {len(votes_df)} votes decoded")

    # 매칭 및 통계 집계
    print("\nRequest-Resolution 매칭 및 통계 집계...")
    decoded_requests = build_decoded_requests(requests_df, resolved_df, votes_df)

    # 식별자 유형별 통계 출력
    print("\n--- 식별자 유형별 통계 ---")
    id_counts = decoded_requests["identifier"].value_counts()
    for ident, count in id_counts.items():
        print(f"  {ident}: {count}")

    # YES_OR_NO_QUERY 상세
    yesno = decoded_requests[decoded_requests["identifier"] == "YES_OR_NO_QUERY"]
    if not yesno.empty:
        print(f"\n--- YES_OR_NO_QUERY 상세 ({len(yesno)}건) ---")
        for _, row in yesno.iterrows():
            label = row.get("resolution_label", "Unknown")
            print(f"  Round {row['round_id']}: {label} (voters={row.get('num_voters', 0)}, consensus={row.get('consensus_rate', 0):.1%})")

    # 저장
    save_data(decoded_requests, "uma_decoded_requests")
    save_data(votes_df, "uma_decoded_votes")

    print("\n=== 디코딩 완료 ===")


if __name__ == "__main__":
    main()
