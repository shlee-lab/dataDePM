"""
Kleros raw hex 이벤트 디코딩

기존 kleros_court_events.parquet의 raw topics/data 필드를 디코딩하여:
- kleros_decoded_disputes.parquet: DisputeCreation + Ruling 매칭
- kleros_decoded_votes.parquet: VoteCast 디코딩
"""

import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"


def hex_to_int(hex_str: str) -> int:
    """32바이트 hex를 정수로 변환"""
    hex_str = hex_str.replace("0x", "").strip()
    return int(hex_str, 16) if hex_str else 0


def hex_to_address(hex_str: str) -> str:
    """32바이트 패딩된 hex를 이더리움 주소로 변환"""
    hex_str = hex_str.replace("0x", "").strip()
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


def decode_dispute_creation(events_df: pd.DataFrame) -> pd.DataFrame:
    """DisputeCreation 이벤트 디코딩

    KlerosCore의 DisputeCreation:
    topics[1] = disputeId (uint256)
    topics[2] = arbitrable (address, padded)
    data = empty (0x)
    """
    disputes = events_df[
        (events_df["event_name"] == "DisputeCreation") &
        (events_df["contract"] == "KlerosCore")
    ].copy()

    records = []
    for _, row in disputes.iterrows():
        topics = json.loads(row["topics"])
        dispute_id = hex_to_int(topics[1])
        arbitrable = hex_to_address(topics[2])

        records.append({
            "dispute_id": dispute_id,
            "arbitrable": arbitrable,
            "created_time": row["timestamp"],
            "block_number": row["block_number"],
            "tx_hash": row["tx_hash"],
        })

    return pd.DataFrame(records)


def decode_ruling(events_df: pd.DataFrame) -> pd.DataFrame:
    """Ruling 이벤트 디코딩

    KlerosCore의 Ruling:
    topics[1] = arbitrable (address, padded)
    topics[2] = disputeId (uint256)
    data[0:32] = ruling (uint256)
    """
    rulings = events_df[
        (events_df["event_name"] == "Ruling") &
        (events_df["contract"] == "KlerosCore")
    ].copy()

    records = []
    for _, row in rulings.iterrows():
        topics = json.loads(row["topics"])
        data_chunks = decode_data_fields(row["data"])

        arbitrable = hex_to_address(topics[1])
        dispute_id = hex_to_int(topics[2])
        ruling = hex_to_int(data_chunks[0]) if data_chunks else 0

        records.append({
            "dispute_id": dispute_id,
            "arbitrable": arbitrable,
            "ruling": ruling,
            "ruling_time": row["timestamp"],
            "tx_hash": row["tx_hash"],
        })

    return pd.DataFrame(records)


def decode_vote_cast(events_df: pd.DataFrame) -> pd.DataFrame:
    """VoteCast 이벤트 디코딩

    DisputeKitClassic의 VoteCast:
    topics[1] = coreDisputeId (uint256)
    topics[2] = voter (address, padded)
    topics[3] = choice (uint256)
    data = justification (bytes, ABI encoded)
    """
    votes = events_df[
        (events_df["event_name"] == "VoteCast") &
        (events_df["contract"] == "DisputeKitClassic")
    ].copy()

    records = []
    for _, row in votes.iterrows():
        topics = json.loads(row["topics"])
        dispute_id = hex_to_int(topics[1])
        voter = hex_to_address(topics[2])
        choice = hex_to_int(topics[3])

        records.append({
            "dispute_id": dispute_id,
            "voter": voter,
            "choice": choice,
            "timestamp": row["timestamp"],
            "tx_hash": row["tx_hash"],
        })

    return pd.DataFrame(records)


def decode_draw(events_df: pd.DataFrame) -> pd.DataFrame:
    """Draw 이벤트 디코딩

    KlerosCore의 Draw:
    topics[1] = juror (address, padded)
    topics[2] = disputeId (uint256)
    data[0:32] = roundId (uint256)
    data[32:64] = voteId (uint256)
    """
    draws = events_df[
        (events_df["event_name"] == "Draw") &
        (events_df["contract"] == "KlerosCore")
    ].copy()

    records = []
    for _, row in draws.iterrows():
        topics = json.loads(row["topics"])
        data_chunks = decode_data_fields(row["data"])

        juror = hex_to_address(topics[1])
        dispute_id = hex_to_int(topics[2])
        round_id = hex_to_int(data_chunks[0]) if len(data_chunks) > 0 else 0
        vote_id = hex_to_int(data_chunks[1]) if len(data_chunks) > 1 else 0

        records.append({
            "dispute_id": dispute_id,
            "juror": juror,
            "round_id": round_id,
            "vote_id": vote_id,
            "timestamp": row["timestamp"],
        })

    return pd.DataFrame(records)


def decode_appeal_possible(events_df: pd.DataFrame) -> pd.DataFrame:
    """AppealPossible 이벤트 디코딩

    KlerosCore의 AppealPossible:
    topics[1] = disputeId (uint256)
    topics[2] = arbitrable (address, padded)
    """
    appeals = events_df[
        (events_df["event_name"] == "AppealPossible") &
        (events_df["contract"] == "KlerosCore")
    ].copy()

    records = []
    for _, row in appeals.iterrows():
        topics = json.loads(row["topics"])
        dispute_id = hex_to_int(topics[1])
        arbitrable = hex_to_address(topics[2])

        records.append({
            "dispute_id": dispute_id,
            "arbitrable": arbitrable,
            "timestamp": row["timestamp"],
        })

    return pd.DataFrame(records)


def build_decoded_disputes(
    disputes_df: pd.DataFrame,
    rulings_df: pd.DataFrame,
    votes_df: pd.DataFrame,
    draws_df: pd.DataFrame,
    appeals_df: pd.DataFrame,
) -> pd.DataFrame:
    """분쟁-판결 매칭 및 통계 집계"""

    # Ruling 매칭
    merged = disputes_df.merge(
        rulings_df[["dispute_id", "ruling", "ruling_time"]],
        on="dispute_id",
        how="left",
    )

    # 투표 통계
    if not votes_df.empty:
        vote_stats = votes_df.groupby("dispute_id").agg(
            num_votes=("voter", "count"),
            num_unique_voters=("voter", "nunique"),
        ).reset_index()

        # 합의 강도 (다수파 비율)
        consensus_records = []
        for did, group in votes_df.groupby("dispute_id"):
            choice_counts = group["choice"].value_counts()
            total = choice_counts.sum()
            majority_share = choice_counts.iloc[0] / total if total > 0 else 0
            consensus_records.append({
                "dispute_id": did,
                "consensus_rate": round(majority_share, 4),
                "majority_choice": int(choice_counts.index[0]),
            })
        consensus_df = pd.DataFrame(consensus_records)

        merged = merged.merge(vote_stats, on="dispute_id", how="left")
        merged = merged.merge(consensus_df, on="dispute_id", how="left")
    else:
        merged["num_votes"] = 0
        merged["num_unique_voters"] = 0
        merged["consensus_rate"] = 0
        merged["majority_choice"] = 0

    # Draw 통계 (배심원 수)
    if not draws_df.empty:
        draw_stats = draws_df.groupby("dispute_id").agg(
            num_jurors_drawn=("juror", "nunique"),
            num_draws=("juror", "count"),
        ).reset_index()
        merged = merged.merge(draw_stats, on="dispute_id", how="left")
    else:
        merged["num_jurors_drawn"] = 0
        merged["num_draws"] = 0

    # Appeal count per dispute
    if not appeals_df.empty:
        appeal_counts = appeals_df.groupby("dispute_id").size().reset_index(name="num_appeals")
        merged = merged.merge(appeal_counts, on="dispute_id", how="left")
    else:
        merged["num_appeals"] = 0

    # NaN -> 0
    for col in ["num_votes", "num_unique_voters", "consensus_rate", "num_jurors_drawn", "num_draws", "num_appeals", "majority_choice"]:
        if col in merged.columns:
            merged[col] = merged[col].fillna(0)

    return merged


def save_data(df: pd.DataFrame, name: str):
    path = DATA_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"Saved: {path} ({len(df)} rows)")


def main():
    print("=== Kleros 이벤트 디코딩 시작 ===")

    events_path = DATA_DIR / "kleros_court_events.parquet"
    if not events_path.exists():
        print(f"Error: {events_path} not found. Run kleros_oracle.py first.")
        return

    events_df = pd.read_parquet(events_path)
    print(f"Loaded {len(events_df)} raw events")

    # 디코딩
    print("\n[1/5] DisputeCreation 디코딩...")
    disputes_df = decode_dispute_creation(events_df)
    print(f"  {len(disputes_df)} disputes decoded")

    print("\n[2/5] Ruling 디코딩...")
    rulings_df = decode_ruling(events_df)
    print(f"  {len(rulings_df)} rulings decoded")

    print("\n[3/5] VoteCast 디코딩...")
    votes_df = decode_vote_cast(events_df)
    print(f"  {len(votes_df)} votes decoded")

    print("\n[4/5] Draw 디코딩...")
    draws_df = decode_draw(events_df)
    print(f"  {len(draws_df)} draws decoded")

    print("\n[5/5] AppealPossible 디코딩...")
    appeals_df = decode_appeal_possible(events_df)
    print(f"  {len(appeals_df)} appeals decoded")

    # 매칭 및 통계 집계
    print("\n분쟁-판결 매칭 및 통계 집계...")
    decoded_disputes = build_decoded_disputes(disputes_df, rulings_df, votes_df, draws_df, appeals_df)

    # 통계 출력
    resolved = decoded_disputes[decoded_disputes["ruling"].notna() & (decoded_disputes["ruling"] > 0)]
    print(f"\n--- 분쟁 해결 통계 ---")
    print(f"  전체 분쟁: {len(decoded_disputes)}")
    print(f"  판결 완료: {len(resolved)} ({len(resolved)/max(len(decoded_disputes),1)*100:.1f}%)")
    print(f"  미해결: {len(decoded_disputes) - len(resolved)}")

    if not resolved.empty:
        ruling_dist = resolved["ruling"].value_counts().sort_index()
        print(f"\n  Ruling 값 분포:")
        for val, count in ruling_dist.items():
            print(f"    Ruling {int(val)}: {count}")

    # 배심원 재참여 분석
    if not votes_df.empty:
        voter_counts = votes_df.groupby("voter")["dispute_id"].nunique()
        repeat_voters = (voter_counts > 1).sum()
        total_voters = len(voter_counts)
        print(f"\n  고유 투표자: {total_voters}")
        print(f"  반복 참여 투표자 (2+ 분쟁): {repeat_voters} ({repeat_voters/max(total_voters,1)*100:.1f}%)")

    # 저장
    save_data(decoded_disputes, "kleros_decoded_disputes")
    save_data(votes_df, "kleros_decoded_votes")

    print("\n=== 디코딩 완료 ===")


if __name__ == "__main__":
    main()
