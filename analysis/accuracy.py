"""
오라클 정확성 및 합의도 분석 모듈

디코딩된 UMA/Kleros 데이터를 분석하여 build_site.py에서 사용할 dict 생성.
"""

from pathlib import Path
import pandas as pd
import numpy as np

DATA_DIR = Path(__file__).parent.parent / "data"


def analyze_polymarket_resolved() -> dict:
    """Polymarket 종료 마켓 해결 통계"""
    path = DATA_DIR / "polymarket_resolved.parquet"
    if not path.exists():
        return {}

    df = pd.read_parquet(path)
    if df.empty:
        return {}

    total = len(df)
    res_counts = df["resolution"].value_counts().to_dict()

    # Yes/No 비율
    yes_count = res_counts.get("Yes", 0)
    no_count = res_counts.get("No", 0)
    unknown_count = res_counts.get("Unknown", 0)

    # 카테고리별 분포
    cat_counts = df["category"].value_counts().head(10).to_dict()

    # 거래량 대비 해결 분포
    vol_median = df["volume"].median()
    high_vol = df[df["volume"] > vol_median]
    low_vol = df[df["volume"] <= vol_median]

    high_vol_res = high_vol["resolution"].value_counts().to_dict() if not high_vol.empty else {}
    low_vol_res = low_vol["resolution"].value_counts().to_dict() if not low_vol.empty else {}

    return {
        "total_resolved": total,
        "resolution_distribution": {k: int(v) for k, v in res_counts.items()},
        "yes_count": yes_count,
        "no_count": no_count,
        "unknown_count": unknown_count,
        "yes_ratio": round(yes_count / max(total, 1) * 100, 1),
        "no_ratio": round(no_count / max(total, 1) * 100, 1),
        "category_distribution": {str(k): int(v) for k, v in cat_counts.items()},
        "high_volume_resolution": {k: int(v) for k, v in high_vol_res.items()},
        "low_volume_resolution": {k: int(v) for k, v in low_vol_res.items()},
        "total_volume": float(df["volume"].sum()),
        "median_volume": float(vol_median),
    }


def analyze_uma_disputes() -> dict:
    """UMA 분쟁 해결 분석"""
    req_path = DATA_DIR / "uma_decoded_requests.parquet"
    votes_path = DATA_DIR / "uma_decoded_votes.parquet"

    if not req_path.exists():
        return {}

    req_df = pd.read_parquet(req_path)
    if req_df.empty:
        return {}

    # 식별자 유형별 통계
    identifier_counts = req_df["identifier"].value_counts()

    # 식별자를 카테고리로 분류
    def categorize_identifier(ident: str) -> str:
        if ident.startswith("Admin"):
            return "Admin (Governance)"
        elif ident == "YES_OR_NO_QUERY":
            return "YES_OR_NO_QUERY"
        elif ident in ("ACROSS-V2", "IS_RELAY_VALID"):
            return "Bridge Verification"
        else:
            return "Price Feed"

    req_df["category"] = req_df["identifier"].apply(categorize_identifier)
    cat_counts = req_df["category"].value_counts().to_dict()

    # YES_OR_NO_QUERY 상세 분석
    yesno = req_df[req_df["identifier"] == "YES_OR_NO_QUERY"].copy()
    yesno_stats = {}
    if not yesno.empty:
        label_counts = yesno["resolution_label"].value_counts().to_dict()
        yesno_stats = {
            "total": len(yesno),
            "resolution_distribution": {str(k): int(v) for k, v in label_counts.items()},
            "yes_count": int(label_counts.get("Yes", 0)),
            "no_count": int(label_counts.get("No", 0)),
            "indeterminate_count": int(label_counts.get("Indeterminate", 0)),
            "unresolvable_count": int(label_counts.get("Unresolvable", 0)),
        }

        # 투표자 수 통계
        if "num_voters" in yesno.columns:
            voters = yesno["num_voters"].dropna()
            yesno_stats["avg_voters"] = round(float(voters.mean()), 1)
            yesno_stats["min_voters"] = int(voters.min())
            yesno_stats["max_voters"] = int(voters.max())

        # 합의 강도 통계
        if "consensus_rate" in yesno.columns:
            cons = yesno["consensus_rate"].dropna()
            yesno_stats["avg_consensus"] = round(float(cons.mean()), 4)
            yesno_stats["min_consensus"] = round(float(cons.min()), 4)
            # 만장일치 비율
            unanimous = (cons >= 0.99).sum()
            yesno_stats["unanimous_ratio"] = round(int(unanimous) / max(len(cons), 1) * 100, 1)

        # 개별 분쟁 데이터 (차트용)
        yesno_details = []
        for _, row in yesno.iterrows():
            yesno_details.append({
                "round_id": int(row["round_id"]),
                "resolution": str(row.get("resolution_label", "Unknown")),
                "voters": int(row.get("num_voters", 0)),
                "consensus": round(float(row.get("consensus_rate", 0)), 4),
            })
        yesno_stats["details"] = yesno_details

    # 전체 UMA DVM 통계
    overall_stats = {
        "total_requests": len(req_df),
        "identifier_categories": {str(k): int(v) for k, v in cat_counts.items()},
    }

    if "num_voters" in req_df.columns:
        voters = req_df["num_voters"].dropna()
        overall_stats["avg_voters_per_request"] = round(float(voters.mean()), 1)

    # 투표자 재참여율 분석
    if votes_path.exists():
        votes_df = pd.read_parquet(votes_path)
        if not votes_df.empty:
            # 투표자별 참여 라운드 수
            voter_rounds = votes_df.groupby("voter")["round_id"].nunique()
            total_voters = len(voter_rounds)
            repeat_voters = (voter_rounds > 1).sum()
            overall_stats["total_unique_voters"] = int(total_voters)
            overall_stats["repeat_voters"] = int(repeat_voters)
            overall_stats["repeat_voter_ratio"] = round(int(repeat_voters) / max(total_voters, 1) * 100, 1)

            # 상위 5명 투표자의 토큰 비율
            voter_tokens = votes_df.groupby("voter")["num_tokens"].sum().sort_values(ascending=False)
            total_tokens = voter_tokens.sum()
            if total_tokens > 0:
                top5_tokens = voter_tokens.head(5).sum()
                top10_tokens = voter_tokens.head(10).sum()
                overall_stats["top5_voter_token_share"] = round(float(top5_tokens / total_tokens * 100), 1)
                overall_stats["top10_voter_token_share"] = round(float(top10_tokens / total_tokens * 100), 1)

            # 상위 투표자 목록 (차트용)
            top_voters = []
            for addr, tokens in voter_tokens.head(10).items():
                rounds = voter_rounds.get(addr, 0)
                top_voters.append({
                    "address": str(addr),
                    "total_tokens": float(tokens),
                    "token_share": round(float(tokens / total_tokens * 100), 2),
                    "rounds_participated": int(rounds),
                })
            overall_stats["top_voters"] = top_voters

    return {
        "overall": overall_stats,
        "yesno": yesno_stats,
    }


def analyze_kleros_disputes() -> dict:
    """Kleros 분쟁 해결 분석"""
    disputes_path = DATA_DIR / "kleros_decoded_disputes.parquet"
    votes_path = DATA_DIR / "kleros_decoded_votes.parquet"

    if not disputes_path.exists():
        return {}

    disputes_df = pd.read_parquet(disputes_path)
    if disputes_df.empty:
        return {}

    total = len(disputes_df)

    # 판결 완료 비율
    has_ruling = disputes_df[disputes_df["ruling"].notna() & (disputes_df["ruling"] > 0)]
    resolved_count = len(has_ruling)

    # Ruling 값 분포
    ruling_dist = {}
    if not has_ruling.empty:
        ruling_dist = has_ruling["ruling"].value_counts().sort_index().to_dict()
        ruling_dist = {f"Ruling {int(k)}": int(v) for k, v in ruling_dist.items()}

    # 배심원 참여 분석
    juror_stats = {}
    if "num_jurors_drawn" in disputes_df.columns:
        draws = disputes_df["num_jurors_drawn"].dropna()
        juror_stats["avg_jurors_per_dispute"] = round(float(draws.mean()), 1)

    if "num_votes" in disputes_df.columns:
        votes = disputes_df["num_votes"].dropna()
        juror_stats["avg_votes_per_dispute"] = round(float(votes.mean()), 1)

    # 합의도 통계
    consensus_stats = {}
    if "consensus_rate" in disputes_df.columns:
        cons = disputes_df["consensus_rate"].dropna()
        cons = cons[cons > 0]
        if not cons.empty:
            consensus_stats["avg_consensus"] = round(float(cons.mean()), 4)
            consensus_stats["min_consensus"] = round(float(cons.min()), 4)
            unanimous = (cons >= 0.99).sum()
            consensus_stats["unanimous_ratio"] = round(int(unanimous) / max(len(cons), 1) * 100, 1)

    # 항소율
    appeal_rate = 0
    if "num_appeals" in disputes_df.columns:
        appealed = (disputes_df["num_appeals"] > 0).sum()
        appeal_rate = round(int(appealed) / max(total, 1) * 100, 1)

    # 배심원 재참여 분석
    voter_stats = {}
    if votes_path.exists():
        votes_df = pd.read_parquet(votes_path)
        if not votes_df.empty:
            voter_disputes = votes_df.groupby("voter")["dispute_id"].nunique()
            total_voters = len(voter_disputes)
            repeat_voters = (voter_disputes > 1).sum()
            voter_stats["total_unique_voters"] = int(total_voters)
            voter_stats["repeat_voters"] = int(repeat_voters)
            voter_stats["repeat_voter_ratio"] = round(int(repeat_voters) / max(total_voters, 1) * 100, 1)

            # 상위 투표자 목록
            voter_vote_counts = votes_df.groupby("voter")["dispute_id"].count().sort_values(ascending=False)
            top_jurors = []
            for addr, count in voter_vote_counts.head(10).items():
                disputes = voter_disputes.get(addr, 0)
                top_jurors.append({
                    "address": str(addr),
                    "total_votes": int(count),
                    "disputes_participated": int(disputes),
                })
            voter_stats["top_jurors"] = top_jurors

    # 개별 분쟁 데이터 (차트용) - 판결 완료 분쟁만
    dispute_details = []
    for _, row in has_ruling.iterrows():
        dispute_details.append({
            "dispute_id": int(row["dispute_id"]),
            "ruling": int(row.get("ruling", 0)),
            "num_votes": int(row.get("num_votes", 0)),
            "num_jurors": int(row.get("num_jurors_drawn", 0)),
            "consensus": round(float(row.get("consensus_rate", 0)), 4),
        })

    return {
        "total_disputes": total,
        "resolved_count": resolved_count,
        "unresolved_count": total - resolved_count,
        "resolution_rate": round(resolved_count / max(total, 1) * 100, 1),
        "ruling_distribution": ruling_dist,
        "juror_stats": juror_stats,
        "consensus_stats": consensus_stats,
        "appeal_rate": appeal_rate,
        "voter_stats": voter_stats,
        "dispute_details": dispute_details,
    }


def analyze_all() -> dict:
    """모든 분석 실행"""
    return {
        "polymarket_resolved": analyze_polymarket_resolved(),
        "uma_disputes": analyze_uma_disputes(),
        "kleros_disputes": analyze_kleros_disputes(),
    }


def main():
    print("=== 오라클 정확성 분석 ===\n")

    results = analyze_all()

    # Polymarket
    pm = results["polymarket_resolved"]
    if pm:
        print(f"[Polymarket 종료 마켓]")
        print(f"  종료 마켓 수: {pm['total_resolved']}")
        print(f"  Yes 해결: {pm['yes_count']} ({pm['yes_ratio']}%)")
        print(f"  No 해결: {pm['no_count']} ({pm['no_ratio']}%)")
        print(f"  Unknown: {pm['unknown_count']}")
        print()

    # UMA
    uma = results["uma_disputes"]
    if uma:
        overall = uma["overall"]
        print(f"[UMA DVM]")
        print(f"  전체 요청: {overall['total_requests']}")
        print(f"  식별자 카테고리: {overall['identifier_categories']}")
        if "top5_voter_token_share" in overall:
            print(f"  상위 5명 투표 토큰 점유율: {overall['top5_voter_token_share']}%")
        if "repeat_voter_ratio" in overall:
            print(f"  반복 투표자 비율: {overall['repeat_voter_ratio']}%")

        yesno = uma.get("yesno", {})
        if yesno:
            print(f"\n  [YES_OR_NO_QUERY]")
            print(f"    총 {yesno['total']}건")
            print(f"    해결 분포: {yesno['resolution_distribution']}")
            if "avg_consensus" in yesno:
                print(f"    평균 합의율: {yesno['avg_consensus']:.1%}")
                print(f"    만장일치 비율: {yesno.get('unanimous_ratio', 0)}%")
        print()

    # Kleros
    kl = results["kleros_disputes"]
    if kl:
        print(f"[Kleros Court]")
        print(f"  전체 분쟁: {kl['total_disputes']}")
        print(f"  판결 완료: {kl['resolved_count']} ({kl['resolution_rate']}%)")
        print(f"  Ruling 분포: {kl['ruling_distribution']}")
        print(f"  항소율: {kl['appeal_rate']}%")
        vs = kl.get("voter_stats", {})
        if vs:
            print(f"  고유 투표자: {vs.get('total_unique_voters', 0)}")
            print(f"  반복 참여자: {vs.get('repeat_voters', 0)} ({vs.get('repeat_voter_ratio', 0)}%)")

    print("\n=== 분석 완료 ===")


if __name__ == "__main__":
    main()
