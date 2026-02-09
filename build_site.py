"""
Static 웹사이트 빌드 스크립트
- parquet 데이터를 JSON으로 변환
- HTML 페이지 생성
"""

import json
from pathlib import Path
import pandas as pd
import numpy as np
from collectors.concentration_metrics import calculate_all_metrics, interpret_hhi, interpret_gini
from analysis.accuracy import analyze_all
from analysis.calibration import analyze_calibration

DATA_DIR = Path("data")
SITE_DIR = Path("site")
SITE_DIR.mkdir(exist_ok=True)

# 컨트랙트 주소
CONTRACTS = {
    "uma_token": {
        "address": "0x04Fa0d235C4abf4BcF4787aF4CF447DE572eF828",
        "chain": "ethereum",
        "explorer": "https://etherscan.io/token/0x04Fa0d235C4abf4BcF4787aF4CF447DE572eF828"
    },
    "kleros_ethereum": {
        "address": "0x93ed3fbe21207ec2e8f2d3c3de6e058cb73bc04d",
        "chain": "ethereum",
        "explorer": "https://etherscan.io/token/0x93ed3fbe21207ec2e8f2d3c3de6e058cb73bc04d"
    },
    "kleros_arbitrum": {
        "address": "0x330bD769382cFc6d50175903434CCC8D206DCAE5",
        "chain": "arbitrum",
        "explorer": "https://arbiscan.io/token/0x330bD769382cFc6d50175903434CCC8D206DCAE5"
    }
}


def load_data():
    """parquet 파일들 로드"""
    data = {}

    # Polymarket 마켓 데이터
    markets_df = pd.read_parquet(DATA_DIR / "polymarket_markets.parquet")
    data["polymarket_markets"] = {
        "total": len(markets_df),
        "total_volume": markets_df["volume"].sum(),
        "total_liquidity": markets_df["liquidity"].sum(),
        "active_count": len(markets_df[markets_df["active"] == True]),
        "liquid_10k": len(markets_df[markets_df["liquidity"] > 10000]),
        "top_20_markets": markets_df.nlargest(20, "volume")[["question", "volume", "liquidity", "category"]].to_dict("records"),
    }

    # 유동성 집중도 계산
    total_vol = markets_df["volume"].sum()
    total_liq = markets_df["liquidity"].sum()

    concentration = []
    for n in [5, 10, 20, 50, 100]:
        top_vol = markets_df.nlargest(n, "volume")["volume"].sum()
        top_liq = markets_df.nlargest(n, "liquidity")["liquidity"].sum()
        concentration.append({
            "top_n": n,
            "volume_share": round(top_vol / total_vol * 100, 1) if total_vol > 0 else 0,
            "liquidity_share": round(top_liq / total_liq * 100, 1) if total_liq > 0 else 0,
        })
    data["liquidity_concentration"] = concentration

    # 유동성 분포 (버킷별)
    bins = [0, 100, 1000, 10000, 100000, 1000000, float("inf")]
    labels = ["$0-100", "$100-1K", "$1K-10K", "$10K-100K", "$100K-1M", "$1M+"]
    markets_df["liq_bucket"] = pd.cut(markets_df["liquidity"], bins=bins, labels=labels)
    liq_dist = markets_df["liq_bucket"].value_counts().sort_index().to_dict()
    data["liquidity_distribution"] = [{"bucket": str(k), "count": int(v)} for k, v in liq_dist.items()]

    # UMA 홀더 데이터 + 집중도 지표
    holders_df = pd.read_parquet(DATA_DIR / "uma_holders.parquet")
    total_balance = holders_df["balance"].sum()
    uma_metrics = calculate_all_metrics(holders_df["balance"].values, "UMA")

    data["uma_holders"] = {
        "total_holders": len(holders_df),
        "total_balance": total_balance,
        "top_holders": holders_df.head(10)[["address", "balance"]].to_dict("records"),
        "concentration": {
            "top5": round(holders_df.head(5)["balance"].sum() / total_balance * 100, 1),
            "top10": round(holders_df.head(10)["balance"].sum() / total_balance * 100, 1),
            "top20": round(holders_df.head(20)["balance"].sum() / total_balance * 100, 1),
        },
        "metrics": uma_metrics
    }

    # UMA 투표 이벤트 (확장 통계)
    events_df = pd.read_parquet(DATA_DIR / "uma_voting_events.parquet")
    uma_events_stats = {
        "total_events": len(events_df),
        "unique_tx": int(events_df["tx_hash"].nunique()) if "tx_hash" in events_df.columns else 0,
    }

    if "datetime" in events_df.columns and not events_df.empty:
        uma_events_stats["date_range"] = [
            events_df["datetime"].min().strftime("%Y-%m-%d"),
            events_df["datetime"].max().strftime("%Y-%m-%d"),
        ]

    if "event_name" in events_df.columns:
        by_type = events_df["event_name"].value_counts().to_dict()
        uma_events_stats["by_type"] = {k: int(v) for k, v in by_type.items()}
        # 투표 관련 트랜잭션의 고유 발신자 근사 (unique tx_hash for vote events)
        vote_events = events_df[events_df["event_name"].isin(["VoteCommitted", "VoteRevealed", "EncryptedVote"])]
        uma_events_stats["unique_voters_tx"] = int(vote_events["tx_hash"].nunique()) if not vote_events.empty else 0

    data["uma_events"] = uma_events_stats

    # UMA 투표 이벤트 CSV export
    if not events_df.empty:
        csv_cols = [c for c in ["block_number", "timestamp", "tx_hash", "event_name", "topic0", "data", "datetime"] if c in events_df.columns]
        events_df[csv_cols].to_csv(SITE_DIR / "uma_voting_events.csv", index=False)
        print(f"  CSV 저장: site/uma_voting_events.csv ({len(events_df)} rows)")

    # Kleros Court 이벤트
    kleros_court_path = DATA_DIR / "kleros_court_events.parquet"
    if kleros_court_path.exists():
        court_df = pd.read_parquet(kleros_court_path)
        court_stats = {
            "total_events": len(court_df),
            "disputes_created": int((court_df["event_name"] == "DisputeCreation").sum()) if "event_name" in court_df.columns else 0,
            "juror_draws": int((court_df["event_name"] == "Draw").sum()) if "event_name" in court_df.columns else 0,
            "votes_cast": int((court_df["event_name"] == "VoteCast").sum()) if "event_name" in court_df.columns else 0,
            "rulings": int((court_df["event_name"] == "Ruling").sum()) if "event_name" in court_df.columns else 0,
            "appeals": int(court_df["event_name"].isin(["AppealDecision", "AppealPossible"]).sum()) if "event_name" in court_df.columns else 0,
            "new_period": int((court_df["event_name"] == "NewPeriod").sum()) if "event_name" in court_df.columns else 0,
            "token_shifts": int((court_df["event_name"] == "TokenAndETHShift").sum()) if "event_name" in court_df.columns else 0,
        }

        if "tx_hash" in court_df.columns:
            # Draw 이벤트의 고유 주소 수로 unique jurors 근사
            draw_events = court_df[court_df["event_name"] == "Draw"] if "event_name" in court_df.columns else pd.DataFrame()
            court_stats["unique_jurors"] = int(draw_events["tx_hash"].nunique()) if not draw_events.empty else 0

        if "datetime" in court_df.columns and not court_df.empty:
            court_stats["date_range"] = [
                court_df["datetime"].min().strftime("%Y-%m-%d"),
                court_df["datetime"].max().strftime("%Y-%m-%d"),
            ]

        data["kleros_court"] = court_stats

        # Kleros Court CSV export
        csv_cols = [c for c in ["block_number", "timestamp", "tx_hash", "contract", "event_name", "topic0", "data", "datetime"] if c in court_df.columns]
        court_df[csv_cols].to_csv(SITE_DIR / "kleros_court_events.csv", index=False)
        print(f"  CSV 저장: site/kleros_court_events.csv ({len(court_df)} rows)")
    else:
        data["kleros_court"] = {"total_events": 0}

    # Kleros 홀더 데이터 + 집중도 지표
    kleros_df = pd.read_parquet(DATA_DIR / "kleros_holders.parquet")

    kleros_eth = kleros_df[kleros_df["chain"] == "ethereum"].copy()
    kleros_arb = kleros_df[kleros_df["chain"] == "arbitrum"].copy()

    eth_total = kleros_eth["balance"].sum() if not kleros_eth.empty else 1
    arb_total = kleros_arb["balance"].sum() if not kleros_arb.empty else 1

    eth_metrics = calculate_all_metrics(kleros_eth["balance"].values, "Kleros Ethereum") if not kleros_eth.empty else {}
    arb_metrics = calculate_all_metrics(kleros_arb["balance"].values, "Kleros Arbitrum") if not kleros_arb.empty else {}

    data["kleros"] = {
        "ethereum": {
            "total_holders": len(kleros_eth),
            "total_balance": eth_total,
            "top_holders": kleros_eth.head(10)[["address", "balance"]].to_dict("records") if not kleros_eth.empty else [],
            "concentration": {
                "top5": round(kleros_eth.head(5)["balance"].sum() / eth_total * 100, 1) if not kleros_eth.empty else 0,
                "top10": round(kleros_eth.head(10)["balance"].sum() / eth_total * 100, 1) if not kleros_eth.empty else 0,
            },
            "metrics": eth_metrics
        },
        "arbitrum": {
            "total_holders": len(kleros_arb),
            "total_balance": arb_total,
            "top_holders": kleros_arb.head(10)[["address", "balance"]].to_dict("records") if not kleros_arb.empty else [],
            "concentration": {
                "top5": round(kleros_arb.head(5)["balance"].sum() / arb_total * 100, 1) if not kleros_arb.empty else 0,
                "top10": round(kleros_arb.head(10)["balance"].sum() / arb_total * 100, 1) if not kleros_arb.empty else 0,
            },
            "metrics": arb_metrics
        }
    }

    data["contracts"] = CONTRACTS

    # Section 5: Oracle accuracy analysis
    print("  오라클 정확성 분석 중...")
    accuracy_data = analyze_all()
    data["accuracy"] = accuracy_data

    # CSV exports for decoded data
    uma_req_path = DATA_DIR / "uma_decoded_requests.parquet"
    if uma_req_path.exists():
        uma_req_df = pd.read_parquet(uma_req_path)
        uma_req_df.to_csv(SITE_DIR / "uma_decoded_requests.csv", index=False)
        print(f"  CSV 저장: site/uma_decoded_requests.csv ({len(uma_req_df)} rows)")

    kleros_disp_path = DATA_DIR / "kleros_decoded_disputes.parquet"
    if kleros_disp_path.exists():
        kleros_disp_df = pd.read_parquet(kleros_disp_path)
        kleros_disp_df.to_csv(SITE_DIR / "kleros_decoded_disputes.csv", index=False)
        print(f"  CSV 저장: site/kleros_decoded_disputes.csv ({len(kleros_disp_df)} rows)")

    # Section 6: Calibration analysis
    print("  Calibration 분석 중...")
    calibration_data = analyze_calibration()
    data["calibration"] = calibration_data

    # Calibration snapshots CSV export
    cal_path = DATA_DIR / "polymarket_calibration_snapshots.parquet"
    if cal_path.exists():
        cal_df = pd.read_parquet(cal_path)
        cal_df.to_csv(SITE_DIR / "calibration_snapshots.csv", index=False)
        print(f"  CSV 저장: site/calibration_snapshots.csv ({len(cal_df)} rows)")

    return data


def build_html(data):
    """HTML 페이지 생성"""

    def t(ko, en):
        """Bilingual span wrapper"""
        return f'<span class="lang-ko">{ko}</span><span class="lang-en">{en}</span>'

    # Pre-compute values for Section 4 (f-string에서 dict.get() 체이닝 불가)
    uma_by_type = data["uma_events"].get("by_type", {})
    uma_date_range = data["uma_events"].get("date_range", ["?", "?"])
    uma_price_req = uma_by_type.get("PriceRequestAdded", 0)
    uma_vote_committed = uma_by_type.get("VoteCommitted", 0)
    uma_encrypted_vote = uma_by_type.get("EncryptedVote", 0)
    uma_vote_revealed = uma_by_type.get("VoteRevealed", 0)
    uma_price_resolved = uma_by_type.get("PriceResolved", 0)
    uma_rewards = uma_by_type.get("RewardsRetrieved", 0)
    uma_reveal_rate = uma_vote_revealed / max(uma_vote_committed, 1) * 100
    uma_votes_per_req = uma_vote_committed / max(uma_price_req, 1)

    kc = data.get("kleros_court", {})
    kc_date_range = kc.get("date_range", ["?", "?"])
    kc_disputes = kc.get("disputes_created", 0)
    kc_draws = kc.get("juror_draws", 0)
    kc_votes = kc.get("votes_cast", 0)
    kc_rulings = kc.get("rulings", 0)
    kc_appeals = kc.get("appeals", 0)
    kc_jurors = kc.get("unique_jurors", 0)
    kc_total = kc.get("total_events", 0)
    kc_new_period = kc.get("new_period", 0)
    kc_shifts = kc.get("token_shifts", 0)
    kc_draws_per_dispute = kc_draws / max(kc_disputes, 1)
    kc_votes_per_dispute = kc_votes / max(kc_disputes, 1)

    # Pre-compute Section 5 values
    acc = data.get("accuracy", {})
    acc_uma = acc.get("uma_disputes", {})
    acc_uma_overall = acc_uma.get("overall", {})
    acc_uma_yesno = acc_uma.get("yesno", {})
    acc_kleros = acc.get("kleros_disputes", {})
    acc_pm = acc.get("polymarket_resolved", {})

    # 데이터 기간 정보
    uma_period = acc_uma_overall.get("data_period", {})
    kleros_period = acc_kleros.get("data_period", {})

    # UMA YES_OR_NO_QUERY resolution distribution for chart
    yesno_res_dist = acc_uma_yesno.get("resolution_distribution", {})
    yesno_details = acc_uma_yesno.get("details", [])

    # Kleros ruling distribution for chart
    kleros_ruling_dist = acc_kleros.get("ruling_distribution", {})
    kleros_dispute_details = acc_kleros.get("dispute_details", [])
    kleros_voter_stats = acc_kleros.get("voter_stats", {})
    kleros_consensus = acc_kleros.get("consensus_stats", {})

    # Pre-compute Section 6 (Calibration) values
    cal = data.get("calibration", {})
    cal_total = cal.get("total_markets", 0)
    cal_yes_rate = cal.get("yes_rate", 0)
    cal_brier = cal.get("brier_scores", {})
    cal_sharpness = cal.get("sharpness", {})
    cal_curves = cal.get("calibration_curves", {})
    cal_vol_tier = cal.get("volume_tier_brier", {})
    cal_period = cal.get("data_period", {})
    cal_dev_summary = cal.get("deviation_summary", {})
    cal_dev_range = cal.get("deviation_by_range", {})

    # 편차 핵심 수치 (T-7d 기준)
    cal_mid_dev_pp = cal_dev_range.get("t7d", {}).get("mid", {}).get("avg_deviation_pp", 0)
    cal_mid_dev_count = cal_dev_range.get("t7d", {}).get("mid", {}).get("count", 0)

    # Pre-compute values used in multiple places
    liquid_ratio = data["polymarket_markets"]["liquid_10k"] / data["polymarket_markets"]["total"] * 100
    illiquid_ratio = 100 - liquid_ratio

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Prediction Market Structural Risk Analysis</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📊</text></svg>">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            line-height: 1.6;
        }}
        body.lang-en .lang-ko {{ display: none; }}
        body.lang-ko .lang-en {{ display: none; }}
        .lang-toggle {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #252525;
            color: #ccc;
            border: 1px solid #444;
            border-radius: 8px;
            padding: 8px 16px;
            cursor: pointer;
            font-size: 0.9rem;
            z-index: 1000;
            transition: background 0.2s;
        }}
        .lang-toggle:hover {{ background: #333; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 40px 20px; }}
        header {{ text-align: center; margin-bottom: 60px; padding: 40px 0; border-bottom: 1px solid #333; }}
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #ff6b6b, #ffa500);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .subtitle {{ color: #888; font-size: 1.1rem; }}
        .section {{ margin-bottom: 60px; }}
        h2 {{
            font-size: 1.8rem;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #333;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        h3 {{ color: #ccc; margin: 30px 0 15px; }}
        .section-number {{
            background: linear-gradient(135deg, #ff6b6b, #ffa500);
            color: #000;
            width: 36px; height: 36px;
            border-radius: 50%;
            display: flex; align-items: center; justify-content: center;
            font-weight: bold;
        }}
        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 20px;
        }}
        .stat-value {{ font-size: 2rem; font-weight: bold; color: #fff; }}
        .stat-value.danger {{ color: #ff6b6b; }}
        .stat-value.warning {{ color: #ffa500; }}
        .stat-label {{ color: #888; font-size: 0.9rem; margin-top: 5px; }}
        .chart-container {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .chart-title {{ font-size: 1.1rem; margin-bottom: 15px; color: #ccc; }}
        table {{ width: 100%; border-collapse: collapse; background: #1a1a1a; border-radius: 12px; overflow: hidden; }}
        th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #333; }}
        th {{ background: #252525; font-weight: 600; color: #ccc; }}
        tr:hover {{ background: #252525; }}
        .address {{ font-family: monospace; font-size: 0.85rem; color: #888; }}
        .address a {{ color: #6cb6ff; text-decoration: none; }}
        .address a:hover {{ text-decoration: underline; }}
        .insight-box {{
            background: linear-gradient(135deg, rgba(255, 107, 107, 0.1), rgba(255, 165, 0, 0.1));
            border: 1px solid #333;
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
        }}
        .insight-box h4 {{ color: #ffa500; margin-bottom: 10px; }}
        .metric-explanation {{
            background: #151515;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 15px;
            margin: 15px 0;
            font-size: 0.9rem;
        }}
        .metric-explanation dt {{ color: #ffa500; font-weight: bold; margin-top: 10px; }}
        .metric-explanation dt:first-child {{ margin-top: 0; }}
        .metric-explanation dd {{ color: #aaa; margin-left: 15px; }}
        .download-links {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin: 20px 0;
        }}
        .download-links a {{
            background: #252525;
            color: #6cb6ff;
            padding: 8px 16px;
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.9rem;
        }}
        .download-links a:hover {{ background: #333; }}
        .contract-link {{
            display: inline-flex;
            align-items: center;
            gap: 5px;
            color: #6cb6ff;
            text-decoration: none;
            font-size: 0.85rem;
        }}
        .contract-link:hover {{ text-decoration: underline; }}
        .oracle-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 30px;
            margin: 30px 0;
        }}
        .oracle-card {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 25px;
        }}
        .oracle-card h4 {{
            color: #fff;
            font-size: 1.2rem;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .oracle-card .metrics {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 15px;
        }}
        .oracle-card .metric {{
            text-align: center;
            padding: 10px;
            background: #252525;
            border-radius: 8px;
        }}
        .oracle-card .metric-value {{
            font-size: 1.5rem;
            font-weight: bold;
        }}
        .oracle-card .metric-name {{
            font-size: 0.8rem;
            color: #888;
        }}
        footer {{
            text-align: center;
            padding: 40px 0;
            border-top: 1px solid #333;
            color: #666;
        }}
    </style>
</head>
<body>
    <button id="langToggle" class="lang-toggle" onclick="toggleLang()">한국어</button>
    <div class="container">
        <header>
            <h1>{t('예측시장 구조적 리스크 분석', 'Prediction Market Structural Risk Analysis')}</h1>
            <p class="subtitle">{t('Polymarket, UMA &amp; Kleros Oracle 데이터 기반', 'Based on Polymarket, UMA &amp; Kleros Oracle Data')}</p>
            <div class="download-links" style="justify-content: center; margin-top: 20px;">
                <a href="polymarket_markets.csv" download>📥 {t('Polymarket 마켓 데이터', 'Polymarket Market Data')}</a>
                <a href="uma_holders.csv" download>📥 {t('UMA 홀더 데이터', 'UMA Holder Data')}</a>
                <a href="uma_voting_events.csv" download>📥 {t('UMA 투표 이벤트', 'UMA Voting Events')}</a>
                <a href="kleros_holders.csv" download>📥 {t('Kleros 홀더 데이터', 'Kleros Holder Data')}</a>
                <a href="kleros_court_events.csv" download>📥 {t('Kleros Court 이벤트', 'Kleros Court Events')}</a>
            </div>
        </header>

        <!-- 1. 유동성 리스크 -->
        <section class="section">
            <h2><span class="section-number">1</span> {t('유동성 리스크', 'Liquidity Risk')}</h2>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{data["polymarket_markets"]["total"]:,}</div>
                    <div class="stat-label">{t('전체 마켓 수', 'Total Markets')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{data["polymarket_markets"]["liquid_10k"]:,}</div>
                    <div class="stat-label">{t('유동성 $10K+ 마켓', 'Markets with $10K+ Liquidity')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{liquid_ratio:.1f}%</div>
                    <div class="stat-label">{t('$10K+ 비율', '$10K+ Ratio')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data["polymarket_markets"]["total_liquidity"]/1e6:.1f}M</div>
                    <div class="stat-label">{t('총 유동성', 'Total Liquidity')}</div>
                </div>
            </div>

            <div class="chart-container">
                <div class="chart-title">{t('유동성 집중도: 상위 N개 마켓 점유율', 'Liquidity Concentration: Top N Market Share')}</div>
                <canvas id="concentrationChart" height="100"></canvas>
            </div>

            <div class="chart-container">
                <div class="chart-title">{t('유동성 분포 (마켓 수)', 'Liquidity Distribution (Market Count)')}</div>
                <canvas id="distributionChart" height="100"></canvas>
            </div>

            <div class="insight-box">
                <h4>{t('핵심 인사이트', 'Key Insight')}</h4>
                <p class="lang-ko">전체 {data["polymarket_markets"]["total"]:,}개 마켓 중 유동성 $10K 이상인 마켓은 {data["polymarket_markets"]["liquid_10k"]:,}개 ({liquid_ratio:.1f}%)에 불과합니다.
                상위 10개 마켓이 전체 거래량의 {data["liquidity_concentration"][1]["volume_share"]}%를 차지하며, 대부분의 마켓에서는 원하는 가격에 베팅하기 어렵습니다.</p>
                <p class="lang-en">Of the total {data["polymarket_markets"]["total"]:,} markets, only {data["polymarket_markets"]["liquid_10k"]:,} ({liquid_ratio:.1f}%) have liquidity above $10K.
                The top 10 markets account for {data["liquidity_concentration"][1]["volume_share"]}% of total volume, making it difficult to place bets at desired prices in most markets.</p>
            </div>
        </section>

        <!-- 2. 시장 조작 리스크 -->
        <section class="section">
            <h2><span class="section-number">2</span> {t('시장 조작 리스크', 'Market Manipulation Risk')}</h2>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value danger">{illiquid_ratio:.1f}%</div>
                    <div class="stat-label">{t('조작 취약 마켓 비율', 'Manipulation-Vulnerable Ratio')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{data["liquidity_concentration"][0]["volume_share"]}%</div>
                    <div class="stat-label">{t('상위 5개 거래량 점유율', 'Top 5 Volume Share')}</div>
                </div>
            </div>

            <div class="insight-box">
                <h4>{t('유동성-조작 연결고리', 'Liquidity-Manipulation Link')}</h4>
                <p class="lang-ko">유동성이 낮은 마켓({illiquid_ratio:.1f}%)은 소액으로도 가격 조작이 가능합니다.
                이는 wash trading, 자전거래 등의 조작에 취약하며, 조작이 의심되면 참여자가 줄어 유동성이 더 낮아지는 악순환이 발생합니다.</p>
                <p class="lang-en">Low-liquidity markets ({illiquid_ratio:.1f}%) can be price-manipulated with small amounts.
                They are vulnerable to wash trading and self-dealing. When manipulation is suspected, participants withdraw, further reducing liquidity in a vicious cycle.</p>
            </div>

            <h3>{t('거래량 상위 20개 마켓', 'Top 20 Markets by Volume')}</h3>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>{t('마켓', 'Market')}</th>
                        <th>{t('거래량', 'Volume')}</th>
                        <th>{t('유동성', 'Liquidity')}</th>
                        <th>{t('카테고리', 'Category')}</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(f'''
                    <tr>
                        <td>{i+1}</td>
                        <td>{m["question"][:60]}{"..." if len(m["question"]) > 60 else ""}</td>
                        <td>${m["volume"]/1e6:.2f}M</td>
                        <td>${m["liquidity"]/1e3:.0f}K</td>
                        <td>{m["category"] or "-"}</td>
                    </tr>''' for i, m in enumerate(data["polymarket_markets"]["top_20_markets"]))}
                </tbody>
            </table>
        </section>

        <!-- 3. 오라클 리스크 -->
        <section class="section">
            <h2><span class="section-number">3</span> {t('오라클/결정 메커니즘 리스크', 'Oracle/Resolution Mechanism Risk')}</h2>

            <div class="chart-container">
                <div class="chart-title">{t('오라클 집중도 비교', 'Oracle Concentration Comparison')}</div>
                <canvas id="oracleCompareChart" height="100"></canvas>
            </div>

            <dl class="metric-explanation">
                <dt>{t('지니 계수 (Gini Coefficient)', 'Gini Coefficient')}</dt>
                <dd class="lang-ko">0~1 사이 값. 0은 완전 평등, 1은 완전 불평등. 경제학에서 소득 불평등 측정에 표준으로 사용됨. 0.4 이상이면 높은 불평등으로 간주.</dd>
                <dd class="lang-en">Value between 0-1. 0 = perfect equality, 1 = perfect inequality. Standard measure for income inequality in economics. Above 0.4 is considered high inequality.</dd>

                <dt>{t('HHI (Herfindahl-Hirschman Index)', 'HHI (Herfindahl-Hirschman Index)')}</dt>
                <dd class="lang-ko">0~10,000 사이 값. 시장 집중도 측정에 사용되며, 미국 법무부가 독점 심사에 활용. 1,500 미만 = 경쟁적, 1,500~2,500 = 중간 집중, 2,500 이상 = 고도 집중.</dd>
                <dd class="lang-en">Value between 0-10,000. Used by the U.S. DOJ for antitrust analysis. &lt;1,500 = competitive, 1,500-2,500 = moderately concentrated, &gt;2,500 = highly concentrated.</dd>

                <dt>{t('나카모토 계수 (Nakamoto Coefficient)', 'Nakamoto Coefficient')}</dt>
                <dd class="lang-ko">시스템의 51%를 장악하는 데 필요한 최소 엔티티 수. 블록체인 탈중앙화 측정의 표준 지표. 값이 낮을수록 중앙화됨 (1 = 사실상 중앙화).</dd>
                <dd class="lang-en">Minimum number of entities needed to control 51% of the system. Standard blockchain decentralization metric. Lower = more centralized (1 = effectively centralized).</dd>

                <dt>{t('정규화 엔트로피 (Normalized Entropy)', 'Normalized Entropy')}</dt>
                <dd class="lang-ko">0~1 사이 값. 정보이론의 섀넌 엔트로피를 정규화한 것. 1에 가까울수록 분산됨, 0에 가까울수록 집중됨.</dd>
                <dd class="lang-en">Value between 0-1. Normalized Shannon entropy from information theory. Closer to 1 = more distributed, closer to 0 = more concentrated.</dd>
            </dl>

            <div class="oracle-grid">
                <!-- UMA -->
                <div class="oracle-card">
                    <h4>
                        UMA Oracle
                        <a class="contract-link" href="{CONTRACTS['uma_token']['explorer']}" target="_blank">
                            📄 {t('컨트랙트', 'Contract')}
                        </a>
                    </h4>
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-value danger">{data["uma_holders"]["metrics"]["nakamoto"]}</div>
                            <div class="metric-name">{t('나카모토 계수', 'Nakamoto Coeff.')}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value danger">{data["uma_holders"]["metrics"]["gini"]}</div>
                            <div class="metric-name">{t('지니 계수', 'Gini Coeff.')}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value warning">{data["uma_holders"]["metrics"]["hhi"]:,.0f}</div>
                            <div class="metric-name">HHI</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["uma_holders"]["metrics"]["normalized_entropy"]}</div>
                            <div class="metric-name">{t('정규화 엔트로피', 'Norm. Entropy')}</div>
                        </div>
                    </div>
                    <p class="lang-ko" style="color: #888; font-size: 0.85rem;">
                        나카모토 계수 {data["uma_holders"]["metrics"]["nakamoto"]} = 단 {data["uma_holders"]["metrics"]["nakamoto"]}명이 51% 이상 보유.<br>
                        HHI {data["uma_holders"]["metrics"]["hhi"]:,.0f} = 고도 집중 (&gt;2,500)
                    </p>
                    <p class="lang-en" style="color: #888; font-size: 0.85rem;">
                        Nakamoto Coeff. {data["uma_holders"]["metrics"]["nakamoto"]} = only {data["uma_holders"]["metrics"]["nakamoto"]} entity holds &gt;51%.<br>
                        HHI {data["uma_holders"]["metrics"]["hhi"]:,.0f} = highly concentrated (&gt;2,500)
                    </p>
                </div>

                <!-- Kleros Arbitrum -->
                <div class="oracle-card">
                    <h4>
                        Kleros v2 (Arbitrum)
                        <a class="contract-link" href="{CONTRACTS['kleros_arbitrum']['explorer']}" target="_blank">
                            📄 {t('컨트랙트', 'Contract')}
                        </a>
                    </h4>
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-value danger">{data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}</div>
                            <div class="metric-name">{t('나카모토 계수', 'Nakamoto Coeff.')}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value danger">{data["kleros"]["arbitrum"]["metrics"].get("gini", 0)}</div>
                            <div class="metric-name">{t('지니 계수', 'Gini Coeff.')}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value warning">{data["kleros"]["arbitrum"]["metrics"].get("hhi", 0):,.0f}</div>
                            <div class="metric-name">HHI</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["kleros"]["arbitrum"]["metrics"].get("normalized_entropy", 0)}</div>
                            <div class="metric-name">{t('정규화 엔트로피', 'Norm. Entropy')}</div>
                        </div>
                    </div>
                    <p class="lang-ko" style="color: #888; font-size: 0.85rem;">
                        나카모토 계수 {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)} = {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}명이면 51% 장악 가능.<br>
                        HHI {data["kleros"]["arbitrum"]["metrics"].get("hhi", 0):,.0f} = 중간 집중 (1,500~2,500)
                    </p>
                    <p class="lang-en" style="color: #888; font-size: 0.85rem;">
                        Nakamoto Coeff. {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)} = {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)} entities can control 51%.<br>
                        HHI {data["kleros"]["arbitrum"]["metrics"].get("hhi", 0):,.0f} = moderately concentrated (1,500-2,500)
                    </p>
                </div>

                <!-- Kleros Ethereum -->
                <div class="oracle-card">
                    <h4>
                        Kleros (Ethereum)
                        <a class="contract-link" href="{CONTRACTS['kleros_ethereum']['explorer']}" target="_blank">
                            📄 {t('컨트랙트', 'Contract')}
                        </a>
                    </h4>
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-value warning">{data["kleros"]["ethereum"]["metrics"].get("nakamoto", 0)}</div>
                            <div class="metric-name">{t('나카모토 계수', 'Nakamoto Coeff.')}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value warning">{data["kleros"]["ethereum"]["metrics"].get("gini", 0)}</div>
                            <div class="metric-name">{t('지니 계수', 'Gini Coeff.')}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["kleros"]["ethereum"]["metrics"].get("hhi", 0):,.0f}</div>
                            <div class="metric-name">HHI</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["kleros"]["ethereum"]["metrics"].get("normalized_entropy", 0)}</div>
                            <div class="metric-name">{t('정규화 엔트로피', 'Norm. Entropy')}</div>
                        </div>
                    </div>
                    <p class="lang-ko" style="color: #888; font-size: 0.85rem;">
                        Ethereum 메인넷의 PNK 토큰 분포.<br>
                        실제 Court는 Arbitrum에서 운영됨.
                    </p>
                    <p class="lang-en" style="color: #888; font-size: 0.85rem;">
                        PNK token distribution on Ethereum mainnet.<br>
                        Actual Court operates on Arbitrum.
                    </p>
                </div>
            </div>

            <div class="insight-box">
                <h4>{t('오라클 신뢰 문제', 'Oracle Trust Issues')}</h4>
                <p class="lang-ko"><strong>UMA의 나카모토 계수가 {data["uma_holders"]["metrics"]["nakamoto"]}</strong>이라는 것은 단 {data["uma_holders"]["metrics"]["nakamoto"]}명이 전체 투표권의 과반을 보유하고 있어 사실상 결과를 좌우할 수 있다는 의미입니다.
                Kleros v2(Arbitrum)도 나카모토 계수 {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}로, {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}명이면 51%를 장악할 수 있습니다.
                두 오라클 모두 지니 계수 0.9 이상으로 극단적 불평등 상태입니다.</p>
                <p class="lang-en"><strong>UMA's Nakamoto Coefficient of {data["uma_holders"]["metrics"]["nakamoto"]}</strong> means just {data["uma_holders"]["metrics"]["nakamoto"]} entity holds a majority of voting power, effectively controlling outcomes.
                Kleros v2 (Arbitrum) also has a Nakamoto Coefficient of {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}, meaning {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)} entities can control 51%.
                Both oracles have Gini coefficients above 0.9, indicating extreme inequality.</p>
            </div>

            <h3>{t('UMA 토큰 상위 10개 주소', 'UMA Token Top 10 Addresses')}</h3>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>{t('주소', 'Address')}</th>
                        <th>{t('잔액 (UMA)', 'Balance (UMA)')}</th>
                        <th>{t('점유율', 'Share')}</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(f'''
                    <tr>
                        <td>{i+1}</td>
                        <td class="address"><a href="https://etherscan.io/address/{h["address"]}" target="_blank">{h["address"][:10]}...{h["address"][-8:]}</a></td>
                        <td>{h["balance"]:,.0f}</td>
                        <td>{h["balance"]/data["uma_holders"]["total_balance"]*100:.1f}%</td>
                    </tr>''' for i, h in enumerate(data["uma_holders"]["top_holders"]))}
                </tbody>
            </table>

            <h3 style="margin-top: 40px;">{t('Kleros (Arbitrum) 토큰 상위 10개 주소', 'Kleros (Arbitrum) Token Top 10 Addresses')}</h3>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>{t('주소', 'Address')}</th>
                        <th>{t('잔액 (PNK)', 'Balance (PNK)')}</th>
                        <th>{t('점유율', 'Share')}</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(f'''
                    <tr>
                        <td>{i+1}</td>
                        <td class="address"><a href="https://arbiscan.io/address/{h["address"]}" target="_blank">{h["address"][:10]}...{h["address"][-8:]}</a></td>
                        <td>{h["balance"]:,.0f}</td>
                        <td>{h["balance"]/data["kleros"]["arbitrum"]["total_balance"]*100:.1f}%</td>
                    </tr>''' for i, h in enumerate(data["kleros"]["arbitrum"]["top_holders"]))}
                </tbody>
            </table>
        </section>

        <!-- 4. 분쟁 투표 활동 분석 -->
        <section class="section">
            <h2><span class="section-number">4</span> {t('분쟁 투표 활동 분석', 'Dispute Voting Activity Analysis')}</h2>

            <h3>{t('UMA 투표 이벤트', 'UMA Voting Events')}</h3>
            <p class="lang-ko" style="color: #888; margin-bottom: 20px;">UMA Voting 컨트랙트의 전체 이벤트 로그 ({uma_date_range[0]} ~ {uma_date_range[1]})</p>
            <p class="lang-en" style="color: #888; margin-bottom: 20px;">Full event log from UMA Voting contract ({uma_date_range[0]} ~ {uma_date_range[1]})</p>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{data["uma_events"]["total_events"]:,}</div>
                    <div class="stat-label">{t('전체 이벤트', 'Total Events')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{data["uma_events"].get("unique_tx", 0):,}</div>
                    <div class="stat-label">{t('고유 트랜잭션', 'Unique Transactions')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{uma_price_req:,}</div>
                    <div class="stat-label">{t('가격 요청 (분쟁 라운드)', 'Price Requests (Dispute Rounds)')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{data["uma_events"].get("unique_voters_tx", 0):,}</div>
                    <div class="stat-label">{t('고유 투표 트랜잭션', 'Unique Vote Transactions')}</div>
                </div>
            </div>

            <div class="oracle-grid">
                <div class="chart-container">
                    <div class="chart-title">{t('UMA 이벤트 유형별 분포', 'UMA Event Type Distribution')}</div>
                    <canvas id="umaEventsChart" height="200"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-title">{t('UMA 투표 파이프라인', 'UMA Voting Pipeline')}</div>
                    <canvas id="umaFunnelChart" height="200"></canvas>
                </div>
            </div>

            <div class="insight-box">
                <h4>{t('UMA 투표 참여 분석', 'UMA Voting Participation Analysis')}</h4>
                <p class="lang-ko">{uma_price_req:,}건의 가격 요청에 대해 {uma_vote_committed:,}건의 투표 커밋과 {uma_vote_revealed:,}건의 투표 공개가 이루어졌습니다.
                커밋 대비 공개 비율은 {uma_reveal_rate:.1f}%로, 일부 투표자는 커밋 후 공개를 하지 않고 있습니다.
                요청당 평균 {uma_votes_per_req:.1f}건의 투표가 이루어지며, 소수의 참여자에 의존하는 구조입니다.</p>
                <p class="lang-en">{uma_price_req:,} price requests received {uma_vote_committed:,} vote commits and {uma_vote_revealed:,} vote reveals.
                The commit-to-reveal ratio is {uma_reveal_rate:.1f}%, meaning some voters commit but never reveal.
                An average of {uma_votes_per_req:.1f} votes per request indicates reliance on a small set of participants.</p>
            </div>

            <h3 style="margin-top: 50px;">{t('Kleros v2 Court 분쟁 이벤트', 'Kleros v2 Court Dispute Events')}</h3>
            <p class="lang-ko" style="color: #888; margin-bottom: 20px;">KlerosCore + DisputeKitClassic 컨트랙트 (Arbitrum, {kc_date_range[0]} ~ {kc_date_range[1]})</p>
            <p class="lang-en" style="color: #888; margin-bottom: 20px;">KlerosCore + DisputeKitClassic contracts (Arbitrum, {kc_date_range[0]} ~ {kc_date_range[1]})</p>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{kc_disputes:,}</div>
                    <div class="stat-label">{t('분쟁 생성', 'Disputes Created')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{kc_draws:,}</div>
                    <div class="stat-label">{t('배심원 선발 (Draw)', 'Juror Draws')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{kc_votes:,}</div>
                    <div class="stat-label">{t('투표 (VoteCast)', 'Votes Cast')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{kc_rulings:,}</div>
                    <div class="stat-label">{t('최종 판결 (Ruling)', 'Final Rulings')}</div>
                </div>
            </div>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{kc_appeals:,}</div>
                    <div class="stat-label">{t('항소 가능 통보', 'Appeal Notifications')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value danger">{kc_jurors:,}</div>
                    <div class="stat-label">{t('고유 배심원 (추정)', 'Unique Jurors (est.)')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{kc_total:,}</div>
                    <div class="stat-label">{t('전체 이벤트', 'Total Events')}</div>
                </div>
            </div>

            <div class="oracle-grid">
                <div class="chart-container">
                    <div class="chart-title">{t('Kleros Court 이벤트 유형별 분포', 'Kleros Court Event Type Distribution')}</div>
                    <canvas id="klerosEventsChart" height="200"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-title">{t('Kleros 분쟁 파이프라인', 'Kleros Dispute Pipeline')}</div>
                    <canvas id="klerosFunnelChart" height="200"></canvas>
                </div>
            </div>

            <div class="insight-box">
                <h4>{t('Kleros Court 분쟁 해결 패턴', 'Kleros Court Dispute Resolution Pattern')}</h4>
                <p class="lang-ko">총 {kc_disputes:,}건의 분쟁이 생성되어 {kc_rulings:,}건의 최종 판결이 내려졌습니다.
                분쟁당 평균 {kc_draws_per_dispute:.1f}명의 배심원이 선발되고
                {kc_votes_per_dispute:.1f}건의 투표가 이루어집니다.
                추정 고유 배심원 수 {kc_jurors:,}명은 전체 PNK 스테이커 대비 극소수로, 실질적 분쟁 해결 권한이 소수에게 집중되어 있음을 보여줍니다.</p>
                <p class="lang-en">A total of {kc_disputes:,} disputes were created, resulting in {kc_rulings:,} final rulings.
                Each dispute averages {kc_draws_per_dispute:.1f} juror draws and
                {kc_votes_per_dispute:.1f} votes cast.
                The estimated {kc_jurors:,} unique jurors represent a tiny fraction of all PNK stakers, showing that dispute resolution power is concentrated among a few.</p>
            </div>
        </section>

        <!-- 5. 오라클 정확성 검증 -->
        <section class="section">
            <h2><span class="section-number">5</span> {t('오라클 정확성 검증', 'Oracle Accuracy Verification')}</h2>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{acc_pm.get("total_resolved", 0):,}</div>
                    <div class="stat-label">{t('종료 마켓 수', 'Resolved Markets')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{acc_uma_yesno.get("total", 0)}</div>
                    <div class="stat-label">{t('UMA 예측시장 분쟁', 'UMA Prediction Disputes')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{acc_kleros.get("total_disputes", 0)}</div>
                    <div class="stat-label">{t('Kleros 분쟁', 'Kleros Disputes')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{acc_uma_yesno.get("unresolvable_count", 0)}</div>
                    <div class="stat-label">{t('UMA 해결불가 건', 'UMA Unresolvable')}</div>
                </div>
            </div>

            <h3>{t('UMA 분쟁 해결 분석', 'UMA Dispute Resolution Analysis')}</h3>
            <p style="color: #888; font-size: 0.9rem; margin-bottom: 20px;">
                {t(f'데이터 기간: {uma_period.get("start_date", "?")} ~ {uma_period.get("end_date", "?")} ({uma_period.get("days", 0)}일)',
                   f'Data period: {uma_period.get("start_date", "?")} ~ {uma_period.get("end_date", "?")} ({uma_period.get("days", 0)} days)')}
            </p>

            <div class="oracle-grid">
                <div class="chart-container">
                    <div class="chart-title">{t('UMA 식별자 유형별 분포', 'UMA Request Categories')}</div>
                    <canvas id="umaIdentCatChart" height="200"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-title">{t('YES_OR_NO_QUERY 해결 결과', 'YES_OR_NO_QUERY Resolution')}</div>
                    <canvas id="umaYesNoChart" height="200"></canvas>
                </div>
            </div>

            <div class="oracle-grid">
                <div class="chart-container">
                    <div class="chart-title">{t('YES_OR_NO_QUERY 투표 합의도', 'YES_OR_NO_QUERY Vote Consensus')}</div>
                    <canvas id="umaConsensusChart" height="200"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-title">{t('UMA 투표 권한 집중도 (상위 10명)', 'UMA Voting Power Concentration (Top 10)')}</div>
                    <canvas id="umaVoterPowerChart" height="200"></canvas>
                </div>
            </div>

            <div class="insight-box">
                <h4>{t('UMA 분쟁 해결 인사이트', 'UMA Dispute Resolution Insights')}</h4>
                <p class="lang-ko">UMA DVM에 제출된 {acc_uma_overall.get("total_requests", 0)}건의 가격 요청 중 YES_OR_NO_QUERY(예측시장 분쟁)는 {acc_uma_yesno.get("total", 0)}건입니다.
                이 중 Yes {acc_uma_yesno.get("yes_count", 0)}건, No {acc_uma_yesno.get("no_count", 0)}건, 해결불가 {acc_uma_yesno.get("unresolvable_count", 0)}건, 불확정 {acc_uma_yesno.get("indeterminate_count", 0)}건으로 해결되었습니다.
                평균 합의율 {acc_uma_yesno.get("avg_consensus", 0):.1%}, 만장일치 비율 {acc_uma_yesno.get("unanimous_ratio", 0)}%로 높은 합의 수준을 보이지만,
                상위 5명이 전체 투표 토큰의 {acc_uma_overall.get("top5_voter_token_share", 0)}%를 차지하여 소수에 의한 결정 구조입니다.</p>
                <p class="lang-en">Of {acc_uma_overall.get("total_requests", 0)} price requests submitted to UMA DVM, {acc_uma_yesno.get("total", 0)} were YES_OR_NO_QUERY (prediction market disputes).
                Results: Yes {acc_uma_yesno.get("yes_count", 0)}, No {acc_uma_yesno.get("no_count", 0)}, Unresolvable {acc_uma_yesno.get("unresolvable_count", 0)}, Indeterminate {acc_uma_yesno.get("indeterminate_count", 0)}.
                Average consensus {acc_uma_yesno.get("avg_consensus", 0):.1%} with {acc_uma_yesno.get("unanimous_ratio", 0)}% unanimous, showing high agreement.
                However, top 5 voters control {acc_uma_overall.get("top5_voter_token_share", 0)}% of voting tokens — decisions are made by a few.</p>
            </div>

            <h3 style="margin-top: 50px;">{t('🚨 해결 불가(Unresolvable) 케이스 상세', '🚨 Unresolvable Cases Details')}</h3>
            <div class="insight-box" style="background: linear-gradient(135deg, rgba(255, 107, 107, 0.15), rgba(255, 165, 0, 0.15));">
                <h4 style="color: #ff6b6b;">{t('왜 40%가 해결 불가인가?', 'Why 40% Unresolvable?')}</h4>
                <p class="lang-ko">YES_OR_NO_QUERY 25건 중 10건({acc_uma_yesno.get("unresolvable_count", 0)/max(acc_uma_yesno.get("total", 1), 1)*100:.0f}%)이 "해결 불가"로 판정되었습니다.
                UMA 투표자들이 <code>type(int256).min</code> 값을 반환하면 "이 질문은 답할 수 없다"는 의미입니다.
                주요 원인: 데이터 소스 불명확, 질문 모호, 경기 취소/연기, 검증 불가능한 이벤트.</p>
                <p class="lang-en">{acc_uma_yesno.get("unresolvable_count", 0)} of {acc_uma_yesno.get("total", 0)} ({acc_uma_yesno.get("unresolvable_count", 0)/max(acc_uma_yesno.get("total", 1), 1)*100:.0f}%) YES_OR_NO_QUERY disputes were marked "Unresolvable".
                When UMA voters return <code>type(int256).min</code>, it means "this question cannot be answered".
                Main causes: unclear data sources, ambiguous questions, cancelled/postponed events, unverifiable outcomes.</p>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Round</th>
                        <th>{t('마켓 제목', 'Market Title')}</th>
                        <th>{t('날짜', 'Date')}</th>
                        <th>{t('투표자', 'Voters')}</th>
                        <th>{t('합의율', 'Consensus')}</th>
                        <th>{t('이유', 'Reason')}</th>
                        <th>{t('링크', 'Link')}</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(f'''
                    <tr>
                        <td><a href="https://etherscan.io/tx/{case.get("tx_hash", "")}" target="_blank" style="color: #6cb6ff; text-decoration: none;">{case.get("round_id", 0)}</a></td>
                        <td style="max-width: 350px;">{case.get("title", "Unknown")[:120]}{"..." if len(case.get("title", "")) > 120 else ""}</td>
                        <td>{case.get("request_date", "?")}</td>
                        <td>{case.get("voters", 0)}</td>
                        <td>{case.get("consensus", 0):.1%}</td>
                        <td style="max-width: 250px; font-size: 0.85rem; color: #ffa500;">{case.get("reason", "Unknown")}</td>
                        <td><a href="{case.get("link", "#")}" target="_blank" style="color: #6cb6ff;">🔗</a></td>
                    </tr>''' for case in acc_uma_yesno.get("unresolvable_cases", []))}
                </tbody>
            </table>

            <h3 style="margin-top: 50px;">{t('Kleros Court 분쟁 해결 분석', 'Kleros Court Dispute Resolution Analysis')}</h3>
            <p style="color: #888; font-size: 0.9rem; margin-bottom: 20px;">
                {t(f'데이터 기간: {kleros_period.get("start_date", "?")} ~ {kleros_period.get("end_date", "?")} ({kleros_period.get("days", 0)}일)',
                   f'Data period: {kleros_period.get("start_date", "?")} ~ {kleros_period.get("end_date", "?")} ({kleros_period.get("days", 0)} days)')}
            </p>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{acc_kleros.get("resolved_count", 0)}</div>
                    <div class="stat-label">{t('판결 완료', 'Resolved')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{acc_kleros.get("unresolved_count", 0)}</div>
                    <div class="stat-label">{t('미해결', 'Unresolved')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{kleros_consensus.get("avg_consensus", 0):.1%}</div>
                    <div class="stat-label">{t('평균 합의율', 'Avg Consensus')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value danger">{kleros_voter_stats.get("repeat_voter_ratio", 0)}%</div>
                    <div class="stat-label">{t('배심원 반복 참여율', 'Juror Repeat Rate')}</div>
                </div>
            </div>

            <div class="oracle-grid">
                <div class="chart-container">
                    <div class="chart-title">{t('Kleros Ruling 분포', 'Kleros Ruling Distribution')}</div>
                    <canvas id="klerosRulingChart" height="200"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-title">{t('Kleros 배심원 참여 빈도 (상위 10명)', 'Kleros Juror Participation (Top 10)')}</div>
                    <canvas id="klerosJurorChart" height="200"></canvas>
                </div>
            </div>

            <div class="insight-box">
                <h4>{t('Kleros Court 인사이트', 'Kleros Court Insights')}</h4>
                <p class="lang-ko">Kleros v2 Court에서 {acc_kleros.get("total_disputes", 0)}건의 분쟁 중 {acc_kleros.get("resolved_count", 0)}건({acc_kleros.get("resolution_rate", 0)}%)이 판결 완료되었습니다.
                Ruling 2가 다수({kleros_ruling_dist.get("Ruling 2", 0)}건)이며, 평균 합의율은 {kleros_consensus.get("avg_consensus", 0):.1%}입니다.
                전체 {kleros_voter_stats.get("total_unique_voters", 0)}명의 고유 투표자 중 {kleros_voter_stats.get("repeat_voters", 0)}명({kleros_voter_stats.get("repeat_voter_ratio", 0)}%)이 복수 분쟁에 참여하여
                소수의 전문 배심원이 분쟁 해결을 주도하고 있습니다.</p>
                <p class="lang-en">In Kleros v2 Court, {acc_kleros.get("resolved_count", 0)} of {acc_kleros.get("total_disputes", 0)} disputes ({acc_kleros.get("resolution_rate", 0)}%) have been resolved.
                Ruling 2 dominates ({kleros_ruling_dist.get("Ruling 2", 0)} cases), with average consensus at {kleros_consensus.get("avg_consensus", 0):.1%}.
                Of {kleros_voter_stats.get("total_unique_voters", 0)} unique voters, {kleros_voter_stats.get("repeat_voters", 0)} ({kleros_voter_stats.get("repeat_voter_ratio", 0)}%) participated in multiple disputes,
                showing that a small group of professional jurors drives dispute resolution.</p>
            </div>

            {"" if acc_kleros.get("unresolved_count", 0) == 0 else f'''
            <h3 style="margin-top: 50px;">{t('⏳ 미해결(Unresolved) 분쟁 상세', '⏳ Unresolved Disputes Details')}</h3>
            <div class="insight-box" style="background: linear-gradient(135deg, rgba(100, 200, 255, 0.15), rgba(255, 165, 0, 0.15));">
                <h4 style="color: #64c8ff;">{t('왜 아직 해결되지 않았는가?', 'Why Still Unresolved?')}</h4>
                <p class="lang-ko">{acc_kleros.get("total_disputes", 0)}건 중 {acc_kleros.get("unresolved_count", 0)}건({acc_kleros.get("unresolved_count", 0)/max(acc_kleros.get("total_disputes", 1), 1)*100:.1f}%)이 아직 판결이 내려지지 않았습니다.
                주요 원인: 배심원 선발 진행중, 투표 기간 대기중, 항소 절차 진행중, 시스템 지연.</p>
                <p class="lang-en">{acc_kleros.get("unresolved_count", 0)} of {acc_kleros.get("total_disputes", 0)} disputes ({acc_kleros.get("unresolved_count", 0)/max(acc_kleros.get("total_disputes", 1), 1)*100:.1f}%) remain unresolved.
                Main causes: juror selection in progress, awaiting voting period, under appeal, system delays.</p>
            </div>

            <table>
                <thead>
                    <tr>
                        <th>Dispute ID</th>
                        <th>{t('Arbitrable 주소', 'Arbitrable')}</th>
                        <th>{t('생성일', 'Created')}</th>
                        <th>{t('배심원', 'Jurors')}</th>
                        <th>{t('투표', 'Votes')}</th>
                        <th>{t('항소', 'Appeals')}</th>
                        <th>{t('이유', 'Reason')}</th>
                        <th>{t('링크', 'Link')}</th>
                    </tr>
                </thead>
                <tbody>
                    {"".join(f"""
                    <tr>
                        <td>{case.get("dispute_id", 0)}</td>
                        <td class="address"><a href="https://arbiscan.io/address/{case.get('arbitrable', '')}" target="_blank" style="color: #6cb6ff; text-decoration: none;">{case.get("arbitrable", "?")[:10]}...{case.get("arbitrable", "")[-8:]}</a></td>
                        <td>{case.get("created_date", "?")}</td>
                        <td>{case.get("num_jurors", 0)}</td>
                        <td>{case.get("num_votes", 0)}</td>
                        <td>{case.get("num_appeals", 0)}</td>
                        <td style="max-width: 200px; font-size: 0.85rem; color: #64c8ff;">{case.get("reason", "Unknown")}</td>
                        <td><a href="{case.get("link", "#")}" target="_blank" style="color: #6cb6ff;">🔗</a></td>
                    </tr>""" for case in acc_kleros.get("unresolved_cases", []))}
                </tbody>
            </table>
            '''}

            <div class="download-links">
                <a href="uma_decoded_requests.csv" download>📥 {t('UMA 디코딩 요청', 'UMA Decoded Requests')}</a>
                <a href="kleros_decoded_disputes.csv" download>📥 {t('Kleros 디코딩 분쟁', 'Kleros Decoded Disputes')}</a>
            </div>
        </section>

        {"" if not cal else f'''
        <!-- 6. 가격 ≠ 확률: 예측 편차 분석 (Calibration) -->
        <section class="section">
            <h2><span class="section-number">6</span> {t("가격 ≠ 확률: 예측 편차 분석", "Price ≠ Probability: Prediction Deviation Analysis")}</h2>
            <p style="color: #888; font-size: 0.9rem; margin-bottom: 20px;">
                {t(f'Polymarket 2023+ Yes/No 마켓 가격 시계열 기반 | 데이터 기간: {cal_period.get("start", "?")} ~ {cal_period.get("end", "?")}',
                   f'Based on Polymarket 2023+ Yes/No market price history | Period: {cal_period.get("start", "?")} ~ {cal_period.get("end", "?")}')}
            </p>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{cal_total:,}</div>
                    <div class="stat-label">{t("분석 마켓 수", "Markets Analyzed")}</div>
                </div>
                <div class="stat-card" style="border-left: 3px solid {"#ff6b6b" if cal_mid_dev_pp < 0 else "#4ecdc4"};">
                    <div class="stat-value" style="color: {"#ff6b6b" if cal_mid_dev_pp < 0 else "#4ecdc4"};">{"+" if cal_mid_dev_pp > 0 else ""}{cal_mid_dev_pp}pp</div>
                    <div class="stat-label">{t('"반반" 구간(35-65%) 평균 편차', '"Toss-up" Range (35-65%) Avg Deviation')}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{cal_brier.get("t7d", 0):.4f}</div>
                    <div class="stat-label">{t("Brier Score (T-7d)", "Brier Score (T-7d)")}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{cal_yes_rate:.1%}</div>
                    <div class="stat-label">{t("Yes 해결 비율", "Yes Resolution Rate")}</div>
                </div>
            </div>

            <div class="oracle-grid">
                <div class="chart-container">
                    <div class="chart-title">{t("Calibration Curve: 예측 확률 vs 실제 결과", "Calibration Curve: Predicted vs Actual")}</div>
                    <canvas id="calibrationCurveChart" height="250"></canvas>
                </div>
                <div class="chart-container">
                    <div class="chart-title">{t("가격 vs 실제 확률 편차 (T-7d)", "Price vs Actual Probability Deviation (T-7d)")}</div>
                    <canvas id="deviationBarChart" height="250"></canvas>
                </div>
            </div>

            <div class="chart-container" style="max-width: 600px;">
                <div class="chart-title">{t("거래량 티어별 Brier Score (T-7d)", "Volume Tier Brier Score (T-7d)")}</div>
                <canvas id="volumeTierBrierChart" height="200"></canvas>
            </div>

            <div class="insight-box">
                <h4>{t("핵심 발견: 가격 ≠ 확률", "Key Finding: Price ≠ Probability")}</h4>
                <p class="lang-ko">Polymarket의 {cal_total:,}개 마켓에서 <strong>가격이 실제 확률을 체계적으로 왜곡</strong>하고 있습니다.
                "반반" 구간(35-65%) 마켓의 가격은 실제 발생률 대비 평균 <strong>{abs(cal_mid_dev_pp)}pp {"과대추정" if cal_mid_dev_pp < 0 else "과소추정"}</strong>합니다 ({cal_mid_dev_count}건).
                즉, 가격 50%인 마켓이 실제로는 ~{50 + cal_mid_dev_pp:.0f}%만 Yes로 해결됩니다.
                반면 높은 가격 구간(75-95%)은 실제 발생률이 가격보다 높아 <strong>과소추정</strong> 경향이 있습니다.
                Brier Score {cal_brier.get("t7d", 0):.4f}(T-7d)은 전체적으로 양호하지만,
                이 수치가 구간별 체계적 편향을 감추고 있습니다.</p>
                <p class="lang-en">Analysis of {cal_total:,} Polymarket markets reveals <strong>systematic price-probability deviation</strong>.
                In the "toss-up" range (35-65%), prices <strong>{"overestimate" if cal_mid_dev_pp < 0 else "underestimate"} actual outcomes by {abs(cal_mid_dev_pp)}pp</strong> on average ({cal_mid_dev_count} markets).
                A market priced at 50% actually resolves Yes only ~{50 + cal_mid_dev_pp:.0f}% of the time.
                Conversely, high-priced markets (75-95%) tend to <strong>underestimate</strong> actual outcomes.
                While the overall Brier Score of {cal_brier.get("t7d", 0):.4f} (T-7d) appears decent,
                it masks these systematic range-specific biases.</p>
            </div>

            <div class="download-links">
                <a href="calibration_snapshots.csv" download>{t("Calibration 스냅샷 (CSV)", "Calibration Snapshots (CSV)")}</a>
            </div>
        </section>
        '''}

        <footer>
            <p>{t('데이터 수집일', 'Data collected')}: {pd.Timestamp.now().strftime("%Y-%m-%d")}</p>
            <p>{t('Polymarket API &amp; Etherscan API 기반', 'Based on Polymarket API &amp; Etherscan API')}</p>
            <div class="download-links" style="justify-content: center; margin-top: 15px;">
                <a href="data.json" download>📥 {t('전체 데이터 (JSON)', 'Full Data (JSON)')}</a>
            </div>
        </footer>
    </div>

    <script>
        // === Language toggle ===
        const CHART_TR = {{
            ko: {{
                volumeShare: '거래량 점유율 (%)',
                liquidityShare: '유동성 점유율 (%)',
                markets: '마켓 수',
                nakamoto: '나카모토 계수',
                gini: '지니 계수',
                hhiDiv: 'HHI (÷1000)',
                oneMinusEntropy: '1-엔트로피',
                oracleSubtitle: '값이 높을수록 집중도 높음 (나카모토 계수 제외)',
                events: '이벤트 수',
                klerosFunnel: ['DisputeCreation', 'Draw (배심원)', 'VoteCast (투표)', 'Ruling (판결)', 'Appeal (항소)'],
                title: '예측시장 구조적 리스크 분석',
                tokenShare: '토큰 점유율 %',
                consensus: '합의율 %',
                votes: '투표 수',
                disputes: '분쟁 수'
            }},
            en: {{
                volumeShare: 'Volume Share (%)',
                liquidityShare: 'Liquidity Share (%)',
                markets: 'Markets',
                nakamoto: 'Nakamoto Coeff.',
                gini: 'Gini Coeff.',
                hhiDiv: 'HHI (÷1000)',
                oneMinusEntropy: '1-Entropy',
                oracleSubtitle: 'Higher = more concentrated (except Nakamoto)',
                events: 'Events',
                klerosFunnel: ['DisputeCreation', 'Draw (Juror)', 'VoteCast (Vote)', 'Ruling', 'Appeal'],
                title: 'Prediction Market Structural Risk Analysis',
                tokenShare: 'Token Share %',
                consensus: 'Consensus %',
                votes: 'Votes',
                disputes: 'Disputes'
            }}
        }};

        function detectLang() {{
            var saved = localStorage.getItem('lang');
            if (saved) return saved;
            return navigator.language.startsWith('ko') ? 'ko' : 'en';
        }}

        function updateChartLabels(lang) {{
            var tr = CHART_TR[lang];
            chartConcentration.data.datasets[0].label = tr.volumeShare;
            chartConcentration.data.datasets[1].label = tr.liquidityShare;
            chartConcentration.update();

            chartDistribution.data.datasets[0].label = tr.markets;
            chartDistribution.update();

            chartOracleCompare.data.labels = [tr.nakamoto, tr.gini, tr.hhiDiv, tr.oneMinusEntropy];
            chartOracleCompare.options.plugins.title.text = tr.oracleSubtitle;
            chartOracleCompare.update();

            chartUmaFunnel.data.datasets[0].label = tr.events;
            chartUmaFunnel.update();

            chartKlerosFunnel.data.labels = tr.klerosFunnel;
            chartKlerosFunnel.data.datasets[0].label = tr.events;
            chartKlerosFunnel.update();

            // Section 5 charts
            if (typeof chartUmaConsensus !== 'undefined') {{
                chartUmaConsensus.data.datasets[0].label = tr.consensus;
                chartUmaConsensus.update();
            }}
            if (typeof chartUmaVoterPower !== 'undefined') {{
                chartUmaVoterPower.data.datasets[0].label = tr.tokenShare;
                chartUmaVoterPower.update();
            }}
            if (typeof chartKlerosJuror !== 'undefined') {{
                chartKlerosJuror.data.datasets[0].label = tr.votes;
                chartKlerosJuror.data.datasets[1].label = tr.disputes;
                chartKlerosJuror.update();
            }}

            document.title = tr.title;
            document.documentElement.lang = lang;
        }}

        function setLang(lang) {{
            document.body.className = 'lang-' + lang;
            localStorage.setItem('lang', lang);
            document.getElementById('langToggle').textContent = lang === 'ko' ? 'EN' : '한국어';
            updateChartLabels(lang);
        }}

        function toggleLang() {{
            setLang(document.body.classList.contains('lang-ko') ? 'en' : 'ko');
        }}

        // 유동성 집중도 차트
        const concentrationData = {json.dumps(data["liquidity_concentration"])};
        const chartConcentration = new Chart(document.getElementById('concentrationChart'), {{
            type: 'bar',
            data: {{
                labels: concentrationData.map(d => 'Top ' + d.top_n),
                datasets: [{{
                    label: '거래량 점유율 (%)',
                    data: concentrationData.map(d => d.volume_share),
                    backgroundColor: 'rgba(255, 165, 0, 0.7)',
                    borderWidth: 0
                }}, {{
                    label: '유동성 점유율 (%)',
                    data: concentrationData.map(d => d.liquidity_share),
                    backgroundColor: 'rgba(255, 107, 107, 0.7)',
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, max: 100, grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }},
                    x: {{ grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }}
                }},
                plugins: {{ legend: {{ labels: {{ color: '#ccc' }} }} }}
            }}
        }});

        // 유동성 분포 차트
        const distData = {json.dumps(data["liquidity_distribution"])};
        const chartDistribution = new Chart(document.getElementById('distributionChart'), {{
            type: 'bar',
            data: {{
                labels: distData.map(d => d.bucket),
                datasets: [{{
                    label: '마켓 수',
                    data: distData.map(d => d.count),
                    backgroundColor: 'rgba(100, 200, 255, 0.7)',
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }},
                    x: {{ grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }}
                }},
                plugins: {{ legend: {{ labels: {{ color: '#ccc' }} }} }}
            }}
        }});

        // 오라클 비교 차트
        const chartOracleCompare = new Chart(document.getElementById('oracleCompareChart'), {{
            type: 'bar',
            data: {{
                labels: ['나카모토 계수', '지니 계수', 'HHI (÷1000)', '1-엔트로피'],
                datasets: [{{
                    label: 'UMA',
                    data: [
                        {data["uma_holders"]["metrics"]["nakamoto"]},
                        {data["uma_holders"]["metrics"]["gini"]},
                        {data["uma_holders"]["metrics"]["hhi"] / 1000:.2f},
                        {1 - data["uma_holders"]["metrics"]["normalized_entropy"]:.2f}
                    ],
                    backgroundColor: 'rgba(255, 107, 107, 0.8)',
                    borderWidth: 0
                }}, {{
                    label: 'Kleros (Arbitrum)',
                    data: [
                        {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)},
                        {data["kleros"]["arbitrum"]["metrics"].get("gini", 0)},
                        {data["kleros"]["arbitrum"]["metrics"].get("hhi", 0) / 1000:.2f},
                        {1 - data["kleros"]["arbitrum"]["metrics"].get("normalized_entropy", 0):.2f}
                    ],
                    backgroundColor: 'rgba(255, 165, 0, 0.8)',
                    borderWidth: 0
                }}, {{
                    label: 'Kleros (Ethereum)',
                    data: [
                        {data["kleros"]["ethereum"]["metrics"].get("nakamoto", 0)},
                        {data["kleros"]["ethereum"]["metrics"].get("gini", 0)},
                        {data["kleros"]["ethereum"]["metrics"].get("hhi", 0) / 1000:.2f},
                        {1 - data["kleros"]["ethereum"]["metrics"].get("normalized_entropy", 0):.2f}
                    ],
                    backgroundColor: 'rgba(100, 200, 255, 0.8)',
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }},
                    x: {{ grid: {{ color: '#333' }}, ticks: {{ color: '#ccc' }} }}
                }},
                plugins: {{
                    legend: {{ labels: {{ color: '#ccc' }} }},
                    title: {{ display: true, text: '값이 높을수록 집중도 높음 (나카모토 계수 제외)', color: '#666' }}
                }}
            }}
        }});

        // UMA 이벤트 유형 도넛 차트
        const chartUmaEvents = new Chart(document.getElementById('umaEventsChart'), {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(list(uma_by_type.keys()))},
                datasets: [{{
                    data: {json.dumps(list(uma_by_type.values()))},
                    backgroundColor: [
                        'rgba(255, 107, 107, 0.8)',
                        'rgba(255, 165, 0, 0.8)',
                        'rgba(100, 200, 255, 0.8)',
                        'rgba(144, 238, 144, 0.8)',
                        'rgba(186, 147, 255, 0.8)',
                        'rgba(255, 218, 121, 0.8)',
                        'rgba(150, 150, 150, 0.8)'
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ position: 'right', labels: {{ color: '#ccc', font: {{ size: 11 }} }} }}
                }}
            }}
        }});

        // UMA 투표 파이프라인 차트
        const chartUmaFunnel = new Chart(document.getElementById('umaFunnelChart'), {{
            type: 'bar',
            data: {{
                labels: ['PriceRequest', 'VoteCommitted', 'EncryptedVote', 'VoteRevealed', 'PriceResolved', 'RewardsRetrieved'],
                datasets: [{{
                    label: '이벤트 수',
                    data: [
                        {uma_price_req},
                        {uma_vote_committed},
                        {uma_encrypted_vote},
                        {uma_vote_revealed},
                        {uma_price_resolved},
                        {uma_rewards}
                    ],
                    backgroundColor: [
                        'rgba(186, 147, 255, 0.8)',
                        'rgba(255, 107, 107, 0.8)',
                        'rgba(255, 165, 0, 0.8)',
                        'rgba(100, 200, 255, 0.8)',
                        'rgba(144, 238, 144, 0.8)',
                        'rgba(255, 218, 121, 0.8)'
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                scales: {{
                    x: {{ beginAtZero: true, grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }},
                    y: {{ grid: {{ display: false }}, ticks: {{ color: '#ccc' }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});

        // Kleros 이벤트 유형 도넛 차트
        const chartKlerosEvents = new Chart(document.getElementById('klerosEventsChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['DisputeCreation', 'Draw', 'VoteCast', 'NewPeriod', 'Ruling', 'AppealPossible', 'TokenAndETHShift'],
                datasets: [{{
                    data: [
                        {kc_disputes},
                        {kc_draws},
                        {kc_votes},
                        {kc_new_period},
                        {kc_rulings},
                        {kc_appeals},
                        {kc_shifts}
                    ],
                    backgroundColor: [
                        'rgba(255, 107, 107, 0.8)',
                        'rgba(255, 165, 0, 0.8)',
                        'rgba(100, 200, 255, 0.8)',
                        'rgba(186, 147, 255, 0.8)',
                        'rgba(144, 238, 144, 0.8)',
                        'rgba(255, 218, 121, 0.8)',
                        'rgba(150, 150, 150, 0.8)'
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ position: 'right', labels: {{ color: '#ccc', font: {{ size: 11 }} }} }}
                }}
            }}
        }});

        // Kleros 분쟁 파이프라인 차트
        const chartKlerosFunnel = new Chart(document.getElementById('klerosFunnelChart'), {{
            type: 'bar',
            data: {{
                labels: ['DisputeCreation', 'Draw (배심원)', 'VoteCast (투표)', 'Ruling (판결)', 'Appeal (항소)'],
                datasets: [{{
                    label: '이벤트 수',
                    data: [
                        {kc_disputes},
                        {kc_draws},
                        {kc_votes},
                        {kc_rulings},
                        {kc_appeals}
                    ],
                    backgroundColor: [
                        'rgba(255, 107, 107, 0.8)',
                        'rgba(255, 165, 0, 0.8)',
                        'rgba(100, 200, 255, 0.8)',
                        'rgba(144, 238, 144, 0.8)',
                        'rgba(255, 218, 121, 0.8)'
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                indexAxis: 'y',
                responsive: true,
                scales: {{
                    x: {{ beginAtZero: true, grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }},
                    y: {{ grid: {{ display: false }}, ticks: {{ color: '#ccc' }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});

        // === Section 5: Oracle Accuracy Charts ===

        // UMA Identifier Category Chart
        const umaIdentCatData = {json.dumps(acc_uma_overall.get("identifier_categories", {}))};
        const chartUmaIdentCat = new Chart(document.getElementById('umaIdentCatChart'), {{
            type: 'doughnut',
            data: {{
                labels: Object.keys(umaIdentCatData),
                datasets: [{{
                    data: Object.values(umaIdentCatData),
                    backgroundColor: [
                        'rgba(255, 107, 107, 0.8)',
                        'rgba(255, 165, 0, 0.8)',
                        'rgba(100, 200, 255, 0.8)',
                        'rgba(144, 238, 144, 0.8)',
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ position: 'right', labels: {{ color: '#ccc', font: {{ size: 11 }} }} }}
                }}
            }}
        }});

        // UMA YES_OR_NO_QUERY Resolution Donut
        const yesnoResData = {json.dumps(yesno_res_dist)};
        const yesnoColors = {{
            'Yes': 'rgba(144, 238, 144, 0.8)',
            'No': 'rgba(255, 107, 107, 0.8)',
            'Indeterminate': 'rgba(255, 165, 0, 0.8)',
            'Unresolvable': 'rgba(150, 150, 150, 0.8)',
        }};
        const chartUmaYesNo = new Chart(document.getElementById('umaYesNoChart'), {{
            type: 'doughnut',
            data: {{
                labels: Object.keys(yesnoResData),
                datasets: [{{
                    data: Object.values(yesnoResData),
                    backgroundColor: Object.keys(yesnoResData).map(k => yesnoColors[k] || 'rgba(186, 147, 255, 0.8)'),
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ position: 'right', labels: {{ color: '#ccc', font: {{ size: 11 }} }} }}
                }}
            }}
        }});

        // UMA YES_OR_NO_QUERY Consensus Bar Chart
        const yesnoDetails = {json.dumps(yesno_details)};
        const chartUmaConsensus = new Chart(document.getElementById('umaConsensusChart'), {{
            type: 'bar',
            data: {{
                labels: yesnoDetails.map(d => 'R' + d.round_id),
                datasets: [{{
                    label: 'Consensus %',
                    data: yesnoDetails.map(d => Math.round(d.consensus * 100)),
                    backgroundColor: yesnoDetails.map(d => {{
                        if (d.resolution === 'Yes') return 'rgba(144, 238, 144, 0.8)';
                        if (d.resolution === 'No') return 'rgba(255, 107, 107, 0.8)';
                        if (d.resolution === 'Unresolvable') return 'rgba(150, 150, 150, 0.8)';
                        return 'rgba(255, 165, 0, 0.8)';
                    }}),
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, max: 100, grid: {{ color: '#333' }}, ticks: {{ color: '#888', callback: v => v + '%' }} }},
                    x: {{ grid: {{ display: false }}, ticks: {{ color: '#888', font: {{ size: 9 }}, maxRotation: 90 }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});

        // UMA Voter Power Concentration
        const umaTopVoters = {json.dumps(acc_uma_overall.get("top_voters", []))};
        const chartUmaVoterPower = new Chart(document.getElementById('umaVoterPowerChart'), {{
            type: 'bar',
            data: {{
                labels: umaTopVoters.map(v => v.address.slice(0, 8) + '...'),
                datasets: [{{
                    label: 'Token Share %',
                    data: umaTopVoters.map(v => v.token_share),
                    backgroundColor: umaTopVoters.map((v, i) => i < 5 ? 'rgba(255, 107, 107, 0.8)' : 'rgba(255, 165, 0, 0.8)'),
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, grid: {{ color: '#333' }}, ticks: {{ color: '#888', callback: v => v + '%' }} }},
                    x: {{ grid: {{ display: false }}, ticks: {{ color: '#888', font: {{ size: 9 }}, maxRotation: 45 }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});

        // Kleros Ruling Distribution Donut
        const klerosRulingData = {json.dumps(kleros_ruling_dist)};
        const chartKlerosRuling = new Chart(document.getElementById('klerosRulingChart'), {{
            type: 'doughnut',
            data: {{
                labels: Object.keys(klerosRulingData),
                datasets: [{{
                    data: Object.values(klerosRulingData),
                    backgroundColor: [
                        'rgba(255, 107, 107, 0.8)',
                        'rgba(100, 200, 255, 0.8)',
                        'rgba(255, 165, 0, 0.8)',
                        'rgba(144, 238, 144, 0.8)',
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ position: 'right', labels: {{ color: '#ccc', font: {{ size: 11 }} }} }}
                }}
            }}
        }});

        // Kleros Juror Participation
        const klerosTopJurors = {json.dumps(kleros_voter_stats.get("top_jurors", []))};
        const chartKlerosJuror = new Chart(document.getElementById('klerosJurorChart'), {{
            type: 'bar',
            data: {{
                labels: klerosTopJurors.map(j => j.address.slice(0, 8) + '...'),
                datasets: [{{
                    label: 'Votes',
                    data: klerosTopJurors.map(j => j.total_votes),
                    backgroundColor: 'rgba(100, 200, 255, 0.7)',
                    borderWidth: 0
                }}, {{
                    label: 'Disputes',
                    data: klerosTopJurors.map(j => j.disputes_participated),
                    backgroundColor: 'rgba(255, 165, 0, 0.7)',
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ beginAtZero: true, grid: {{ color: '#333' }}, ticks: {{ color: '#888' }} }},
                    x: {{ grid: {{ display: false }}, ticks: {{ color: '#888', font: {{ size: 9 }}, maxRotation: 45 }} }}
                }},
                plugins: {{ legend: {{ labels: {{ color: '#ccc' }} }} }}
            }}
        }});

        // === Section 6: Calibration Charts ===
        const calCurves = {json.dumps(cal_curves)};
        const calBrier = {json.dumps(cal_brier)};
        const calVolTier = {json.dumps(cal_vol_tier)};
        const calDevSummary = {json.dumps(cal_dev_summary)};

        // Calibration Curve (multi-line)
        if (document.getElementById('calibrationCurveChart') && Object.keys(calCurves).length > 0) {{
            const curveColors = {{
                't0': 'rgba(255, 107, 107, 0.9)',
                't1d': 'rgba(255, 165, 0, 0.9)',
                't7d': 'rgba(100, 200, 255, 0.9)',
                't30d': 'rgba(144, 238, 144, 0.9)',
            }};
            const curveLabels = {{ 't0': 'T-0', 't1d': 'T-1d', 't7d': 'T-7d', 't30d': 'T-30d' }};
            const datasets = [];

            // Perfect calibration diagonal
            datasets.push({{
                label: 'Perfect',
                data: [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
                borderColor: 'rgba(255, 255, 255, 0.3)',
                borderDash: [5, 5],
                borderWidth: 1,
                pointRadius: 0,
                fill: false,
            }});

            for (const [key, curve] of Object.entries(calCurves)) {{
                const pts = curve.filter(c => c.actual_rate !== null);
                datasets.push({{
                    label: curveLabels[key] || key,
                    data: pts.map(c => ({{ x: c.bin_mid, y: c.actual_rate }})),
                    borderColor: curveColors[key] || '#ccc',
                    backgroundColor: curveColors[key] || '#ccc',
                    borderWidth: 2,
                    pointRadius: 4,
                    fill: false,
                    tension: 0.1,
                }});
            }}

            new Chart(document.getElementById('calibrationCurveChart'), {{
                type: 'line',
                data: {{
                    labels: ['0%', '10%', '20%', '30%', '40%', '50%', '60%', '70%', '80%', '90%', '100%'],
                    datasets: datasets,
                }},
                options: {{
                    responsive: true,
                    scales: {{
                        x: {{
                            type: 'linear',
                            min: 0, max: 1,
                            title: {{ display: true, text: 'Predicted Probability', color: '#888' }},
                            grid: {{ color: '#333' }},
                            ticks: {{ color: '#888', callback: v => (v * 100) + '%' }}
                        }},
                        y: {{
                            min: 0, max: 1,
                            title: {{ display: true, text: 'Actual Rate', color: '#888' }},
                            grid: {{ color: '#333' }},
                            ticks: {{ color: '#888', callback: v => (v * 100) + '%' }}
                        }}
                    }},
                    plugins: {{
                        legend: {{ labels: {{ color: '#ccc' }} }},
                        tooltip: {{
                            callbacks: {{
                                label: ctx => ctx.dataset.label + ': ' + (ctx.parsed.y * 100).toFixed(1) + '%'
                            }}
                        }}
                    }}
                }}
            }});
        }}

        // Price vs Actual Deviation bar chart (T-7d)
        if (document.getElementById('deviationBarChart') && calDevSummary['t7d']) {{
            const devData = calDevSummary['t7d'].filter(b => b.deviation !== null && b.count > 0);
            const devValues = devData.map(b => b.deviation * 100);  // convert to pp
            const devColors = devValues.map(v => v < 0 ? 'rgba(255, 107, 107, 0.8)' : 'rgba(78, 205, 196, 0.8)');

            new Chart(document.getElementById('deviationBarChart'), {{
                type: 'bar',
                data: {{
                    labels: devData.map(b => b.bin_label),
                    datasets: [{{
                        label: getLang() === 'ko' ? '편차 (pp)' : 'Deviation (pp)',
                        data: devValues,
                        backgroundColor: devColors,
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    scales: {{
                        y: {{
                            grid: {{ color: '#333' }},
                            ticks: {{ color: '#888', callback: v => (v > 0 ? '+' : '') + v.toFixed(1) + 'pp' }},
                            title: {{ display: true, text: getLang() === 'ko' ? '편차 (음수 = 과대추정)' : 'Deviation (negative = overestimated)', color: '#888' }}
                        }},
                        x: {{
                            grid: {{ display: false }},
                            ticks: {{ color: '#888' }},
                            title: {{ display: true, text: getLang() === 'ko' ? '가격 구간' : 'Price Bin', color: '#888' }}
                        }}
                    }},
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{ callbacks: {{
                            label: ctx => {{
                                const bin = devData[ctx.dataIndex];
                                const v = ctx.parsed.y;
                                const sign = v > 0 ? '+' : '';
                                return sign + v.toFixed(1) + 'pp (' + bin.count + (getLang() === 'ko' ? '건)' : ' markets)');
                            }}
                        }} }},
                        annotation: {{
                            annotations: {{
                                zeroLine: {{
                                    type: 'line',
                                    yMin: 0, yMax: 0,
                                    borderColor: 'rgba(255, 255, 255, 0.4)',
                                    borderWidth: 1,
                                    borderDash: [4, 4]
                                }}
                            }}
                        }}
                    }}
                }}
            }});
        }}

        // Volume Tier Brier Score (bar chart)
        if (document.getElementById('volumeTierBrierChart') && Object.keys(calVolTier).length > 0) {{
            const tierOrder = ['1M+', '100K+', '10K+', '< 10K'];
            const validTiers = tierOrder.filter(t => calVolTier[t] && calVolTier[t]['t7d'] !== undefined);

            new Chart(document.getElementById('volumeTierBrierChart'), {{
                type: 'bar',
                data: {{
                    labels: validTiers.map(t => t + ' ($' + (calVolTier[t]?.count || 0) + ')'),
                    datasets: [{{
                        label: 'Brier Score (T-7d)',
                        data: validTiers.map(t => calVolTier[t]['t7d']),
                        backgroundColor: [
                            'rgba(255, 107, 107, 0.7)',
                            'rgba(255, 165, 0, 0.7)',
                            'rgba(100, 200, 255, 0.7)',
                            'rgba(144, 238, 144, 0.7)',
                        ],
                        borderWidth: 0
                    }}]
                }},
                options: {{
                    responsive: true,
                    scales: {{
                        y: {{ beginAtZero: true, grid: {{ color: '#333' }}, ticks: {{ color: '#888' }},
                              title: {{ display: true, text: 'Brier Score (lower = better)', color: '#888' }} }},
                        x: {{ grid: {{ display: false }}, ticks: {{ color: '#888' }} }}
                    }},
                    plugins: {{
                        legend: {{ display: false }},
                        tooltip: {{ callbacks: {{ label: ctx => 'Brier: ' + ctx.parsed.y.toFixed(4) }} }}
                    }}
                }}
            }});
        }}

        // Initialize language
        setLang(detectLang());
    </script>
</body>
</html>'''

    return html


def main():
    print("데이터 로드 중...")
    data = load_data()

    print("HTML 생성 중...")
    html = build_html(data)

    output_path = SITE_DIR / "index.html"
    output_path.write_text(html, encoding="utf-8")
    print(f"생성 완료: {output_path}")

    # JSON 데이터도 저장
    json_path = SITE_DIR / "data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"데이터 저장: {json_path}")


if __name__ == "__main__":
    main()
