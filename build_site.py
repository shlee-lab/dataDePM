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

    # UMA 투표 이벤트
    events_df = pd.read_parquet(DATA_DIR / "uma_voting_events.parquet")
    data["uma_events"] = {
        "total_events": len(events_df),
    }

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

    return data


def build_html(data):
    """HTML 페이지 생성"""

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>예측시장 구조적 리스크 분석</title>
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
    <div class="container">
        <header>
            <h1>예측시장 구조적 리스크 분석</h1>
            <p class="subtitle">Polymarket, UMA & Kleros Oracle 데이터 기반</p>
            <div class="download-links" style="justify-content: center; margin-top: 20px;">
                <a href="polymarket_markets.csv" download>📥 Polymarket 마켓 데이터</a>
                <a href="uma_holders.csv" download>📥 UMA 홀더 데이터</a>
                <a href="kleros_holders.csv" download>📥 Kleros 홀더 데이터</a>
            </div>
        </header>

        <!-- 지표 설명 -->
        <section class="section">
            <h2>📖 사용된 집중도 지표 설명</h2>
            <dl class="metric-explanation">
                <dt>지니 계수 (Gini Coefficient)</dt>
                <dd>0~1 사이 값. 0은 완전 평등, 1은 완전 불평등. 경제학에서 소득 불평등 측정에 표준으로 사용됨. 0.4 이상이면 높은 불평등으로 간주.</dd>

                <dt>HHI (Herfindahl-Hirschman Index)</dt>
                <dd>0~10,000 사이 값. 시장 집중도 측정에 사용되며, 미국 법무부가 독점 심사에 활용. 1,500 미만 = 경쟁적, 1,500~2,500 = 중간 집중, 2,500 이상 = 고도 집중.</dd>

                <dt>나카모토 계수 (Nakamoto Coefficient)</dt>
                <dd>시스템의 51%를 장악하는 데 필요한 최소 엔티티 수. 블록체인 탈중앙화 측정의 표준 지표. 값이 낮을수록 중앙화됨 (1 = 사실상 중앙화).</dd>

                <dt>정규화 엔트로피 (Normalized Entropy)</dt>
                <dd>0~1 사이 값. 정보이론의 섀넌 엔트로피를 정규화한 것. 1에 가까울수록 분산됨, 0에 가까울수록 집중됨.</dd>
            </dl>
        </section>

        <!-- 1. 유동성 리스크 -->
        <section class="section">
            <h2><span class="section-number">1</span> 유동성 리스크</h2>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value">{data["polymarket_markets"]["total"]:,}</div>
                    <div class="stat-label">전체 마켓 수</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{data["polymarket_markets"]["liquid_10k"]:,}</div>
                    <div class="stat-label">유동성 $10K+ 마켓</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{data["polymarket_markets"]["liquid_10k"] / data["polymarket_markets"]["total"] * 100:.1f}%</div>
                    <div class="stat-label">$10K+ 비율</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${data["polymarket_markets"]["total_liquidity"]/1e6:.1f}M</div>
                    <div class="stat-label">총 유동성</div>
                </div>
            </div>

            <div class="chart-container">
                <div class="chart-title">유동성 집중도: 상위 N개 마켓 점유율</div>
                <canvas id="concentrationChart" height="100"></canvas>
            </div>

            <div class="chart-container">
                <div class="chart-title">유동성 분포 (마켓 수)</div>
                <canvas id="distributionChart" height="100"></canvas>
            </div>

            <div class="insight-box">
                <h4>핵심 인사이트</h4>
                <p>전체 {data["polymarket_markets"]["total"]:,}개 마켓 중 유동성 $10K 이상인 마켓은 {data["polymarket_markets"]["liquid_10k"]:,}개 ({data["polymarket_markets"]["liquid_10k"] / data["polymarket_markets"]["total"] * 100:.1f}%)에 불과합니다.
                상위 10개 마켓이 전체 거래량의 {data["liquidity_concentration"][1]["volume_share"]}%를 차지하며, 대부분의 마켓에서는 원하는 가격에 베팅하기 어렵습니다.</p>
            </div>
        </section>

        <!-- 2. 시장 조작 리스크 -->
        <section class="section">
            <h2><span class="section-number">2</span> 시장 조작 리스크</h2>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value danger">{100 - data["polymarket_markets"]["liquid_10k"] / data["polymarket_markets"]["total"] * 100:.1f}%</div>
                    <div class="stat-label">조작 취약 마켓 비율</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{data["liquidity_concentration"][0]["volume_share"]}%</div>
                    <div class="stat-label">상위 5개 거래량 점유율</div>
                </div>
            </div>

            <div class="insight-box">
                <h4>유동성-조작 연결고리</h4>
                <p>유동성이 낮은 마켓({100 - data["polymarket_markets"]["liquid_10k"] / data["polymarket_markets"]["total"] * 100:.1f}%)은 소액으로도 가격 조작이 가능합니다.
                이는 wash trading, 자전거래 등의 조작에 취약하며, 조작이 의심되면 참여자가 줄어 유동성이 더 낮아지는 악순환이 발생합니다.</p>
            </div>

            <h3>거래량 상위 20개 마켓</h3>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>마켓</th>
                        <th>거래량</th>
                        <th>유동성</th>
                        <th>카테고리</th>
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
            <h2><span class="section-number">3</span> 오라클/결정 메커니즘 리스크</h2>

            <div class="chart-container">
                <div class="chart-title">오라클 집중도 비교</div>
                <canvas id="oracleCompareChart" height="100"></canvas>
            </div>

            <div class="oracle-grid">
                <!-- UMA -->
                <div class="oracle-card">
                    <h4>
                        UMA Oracle
                        <a class="contract-link" href="{CONTRACTS['uma_token']['explorer']}" target="_blank">
                            📄 컨트랙트
                        </a>
                    </h4>
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-value danger">{data["uma_holders"]["metrics"]["nakamoto"]}</div>
                            <div class="metric-name">나카모토 계수</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value danger">{data["uma_holders"]["metrics"]["gini"]}</div>
                            <div class="metric-name">지니 계수</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value warning">{data["uma_holders"]["metrics"]["hhi"]:,.0f}</div>
                            <div class="metric-name">HHI</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["uma_holders"]["metrics"]["normalized_entropy"]}</div>
                            <div class="metric-name">정규화 엔트로피</div>
                        </div>
                    </div>
                    <p style="color: #888; font-size: 0.85rem;">
                        나카모토 계수 {data["uma_holders"]["metrics"]["nakamoto"]} = 단 {data["uma_holders"]["metrics"]["nakamoto"]}명이 51% 이상 보유.<br>
                        HHI {data["uma_holders"]["metrics"]["hhi"]:,.0f} = 고도 집중 (>2,500)
                    </p>
                </div>

                <!-- Kleros Arbitrum -->
                <div class="oracle-card">
                    <h4>
                        Kleros v2 (Arbitrum)
                        <a class="contract-link" href="{CONTRACTS['kleros_arbitrum']['explorer']}" target="_blank">
                            📄 컨트랙트
                        </a>
                    </h4>
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-value danger">{data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}</div>
                            <div class="metric-name">나카모토 계수</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value danger">{data["kleros"]["arbitrum"]["metrics"].get("gini", 0)}</div>
                            <div class="metric-name">지니 계수</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value warning">{data["kleros"]["arbitrum"]["metrics"].get("hhi", 0):,.0f}</div>
                            <div class="metric-name">HHI</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["kleros"]["arbitrum"]["metrics"].get("normalized_entropy", 0)}</div>
                            <div class="metric-name">정규화 엔트로피</div>
                        </div>
                    </div>
                    <p style="color: #888; font-size: 0.85rem;">
                        나카모토 계수 {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)} = {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}명이면 51% 장악 가능.<br>
                        HHI {data["kleros"]["arbitrum"]["metrics"].get("hhi", 0):,.0f} = 중간 집중 (1,500~2,500)
                    </p>
                </div>

                <!-- Kleros Ethereum -->
                <div class="oracle-card">
                    <h4>
                        Kleros (Ethereum)
                        <a class="contract-link" href="{CONTRACTS['kleros_ethereum']['explorer']}" target="_blank">
                            📄 컨트랙트
                        </a>
                    </h4>
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-value warning">{data["kleros"]["ethereum"]["metrics"].get("nakamoto", 0)}</div>
                            <div class="metric-name">나카모토 계수</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value warning">{data["kleros"]["ethereum"]["metrics"].get("gini", 0)}</div>
                            <div class="metric-name">지니 계수</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["kleros"]["ethereum"]["metrics"].get("hhi", 0):,.0f}</div>
                            <div class="metric-name">HHI</div>
                        </div>
                        <div class="metric">
                            <div class="metric-value">{data["kleros"]["ethereum"]["metrics"].get("normalized_entropy", 0)}</div>
                            <div class="metric-name">정규화 엔트로피</div>
                        </div>
                    </div>
                    <p style="color: #888; font-size: 0.85rem;">
                        Ethereum 메인넷의 PNK 토큰 분포.<br>
                        실제 Court는 Arbitrum에서 운영됨.
                    </p>
                </div>
            </div>

            <div class="insight-box">
                <h4>오라클 신뢰 문제</h4>
                <p><strong>UMA의 나카모토 계수가 {data["uma_holders"]["metrics"]["nakamoto"]}</strong>이라는 것은 단 {data["uma_holders"]["metrics"]["nakamoto"]}명이 전체 투표권의 과반을 보유하고 있어 사실상 결과를 좌우할 수 있다는 의미입니다.
                Kleros v2(Arbitrum)도 나카모토 계수 {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}로, {data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}명이면 51%를 장악할 수 있습니다.
                두 오라클 모두 지니 계수 0.9 이상으로 극단적 불평등 상태입니다.</p>
            </div>

            <h3>UMA 토큰 상위 10개 주소</h3>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>주소</th>
                        <th>잔액 (UMA)</th>
                        <th>점유율</th>
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

            <h3 style="margin-top: 40px;">Kleros (Arbitrum) 토큰 상위 10개 주소</h3>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>주소</th>
                        <th>잔액 (PNK)</th>
                        <th>점유율</th>
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

        <footer>
            <p>데이터 수집일: {pd.Timestamp.now().strftime("%Y-%m-%d")}</p>
            <p>Polymarket API & Etherscan API 기반</p>
            <div class="download-links" style="justify-content: center; margin-top: 15px;">
                <a href="data.json" download>📥 전체 데이터 (JSON)</a>
            </div>
        </footer>
    </div>

    <script>
        // 유동성 집중도 차트
        const concentrationData = {json.dumps(data["liquidity_concentration"])};
        new Chart(document.getElementById('concentrationChart'), {{
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
        new Chart(document.getElementById('distributionChart'), {{
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
        new Chart(document.getElementById('oracleCompareChart'), {{
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
