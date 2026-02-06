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
    kleros_stats_df = pd.read_parquet(DATA_DIR / "kleros_holder_stats.parquet")

    # Ethereum과 Arbitrum 분리
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

    return data


def build_html(data):
    """HTML 페이지 생성"""

    html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>예측시장 구조적 리스크 분석</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0a;
            color: #e0e0e0;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 40px 20px;
        }}
        header {{
            text-align: center;
            margin-bottom: 60px;
            padding: 40px 0;
            border-bottom: 1px solid #333;
        }}
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(135deg, #ff6b6b, #ffa500);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .subtitle {{
            color: #888;
            font-size: 1.1rem;
        }}
        .section {{
            margin-bottom: 60px;
        }}
        h2 {{
            font-size: 1.8rem;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #333;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .section-number {{
            background: linear-gradient(135deg, #ff6b6b, #ffa500);
            color: #000;
            width: 36px;
            height: 36px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
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
        .stat-value {{
            font-size: 2rem;
            font-weight: bold;
            color: #fff;
        }}
        .stat-value.danger {{
            color: #ff6b6b;
        }}
        .stat-value.warning {{
            color: #ffa500;
        }}
        .stat-label {{
            color: #888;
            font-size: 0.9rem;
            margin-top: 5px;
        }}
        .chart-container {{
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        .chart-title {{
            font-size: 1.1rem;
            margin-bottom: 15px;
            color: #ccc;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #1a1a1a;
            border-radius: 12px;
            overflow: hidden;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #333;
        }}
        th {{
            background: #252525;
            font-weight: 600;
            color: #ccc;
        }}
        tr:hover {{
            background: #252525;
        }}
        .address {{
            font-family: monospace;
            font-size: 0.85rem;
            color: #888;
        }}
        .risk-indicator {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
        }}
        .risk-high {{
            background: rgba(255, 107, 107, 0.2);
            color: #ff6b6b;
        }}
        .risk-medium {{
            background: rgba(255, 165, 0, 0.2);
            color: #ffa500;
        }}
        .insight-box {{
            background: linear-gradient(135deg, rgba(255, 107, 107, 0.1), rgba(255, 165, 0, 0.1));
            border: 1px solid #333;
            border-radius: 12px;
            padding: 20px;
            margin: 20px 0;
        }}
        .insight-box h4 {{
            color: #ffa500;
            margin-bottom: 10px;
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
        </header>

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

            <h3 style="margin: 30px 0 15px; color: #ccc;">거래량 상위 20개 마켓</h3>
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

            <h3 style="margin: 20px 0 15px; color: #fff; font-size: 1.4rem;">UMA Oracle</h3>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value danger">{data["uma_holders"]["metrics"]["nakamoto"]}</div>
                    <div class="stat-label">나카모토 계수 (51% 장악 필요 수)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value danger">{data["uma_holders"]["metrics"]["gini"]}</div>
                    <div class="stat-label">지니 계수 (0=평등, 1=불평등)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{data["uma_holders"]["metrics"]["hhi"]:,.0f}</div>
                    <div class="stat-label">HHI (>2500 = 고도 집중)</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{data["uma_holders"]["metrics"]["normalized_entropy"]}</div>
                    <div class="stat-label">정규화 엔트로피 (1=분산)</div>
                </div>
            </div>

            <div class="chart-container">
                <div class="chart-title">UMA 토큰 홀더 집중도</div>
                <canvas id="umaChart" height="100"></canvas>
            </div>

            <div class="insight-box">
                <h4>UMA 오라클 - 사실상 중앙화</h4>
                <p><strong>나카모토 계수가 {data["uma_holders"]["metrics"]["nakamoto"]}</strong>입니다. 이는 단 {data["uma_holders"]["metrics"]["nakamoto"]}명이 전체 투표권의 51% 이상을 보유하고 있어 사실상 결과를 좌우할 수 있다는 의미입니다.
                지니 계수 {data["uma_holders"]["metrics"]["gini"]}은 극단적 불평등을, HHI {data["uma_holders"]["metrics"]["hhi"]:,.0f}는 고도 집중(>2500)을 나타냅니다.</p>
            </div>

            <h3 style="margin: 30px 0 15px; color: #ccc;">UMA 토큰 상위 10개 주소</h3>
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
                        <td class="address">{h["address"][:10]}...{h["address"][-8:]}</td>
                        <td>{h["balance"]:,.0f}</td>
                        <td>{h["balance"]/data["uma_holders"]["total_balance"]*100:.1f}%</td>
                    </tr>''' for i, h in enumerate(data["uma_holders"]["top_holders"]))}
                </tbody>
            </table>

            <!-- Kleros 섹션 -->
            <h3 style="margin: 50px 0 20px; color: #fff; font-size: 1.4rem;">Kleros (PNK) 오라클</h3>

            <div class="stat-grid">
                <div class="stat-card">
                    <div class="stat-value danger">{data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}</div>
                    <div class="stat-label">Arbitrum 나카모토 계수</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value danger">{data["kleros"]["arbitrum"]["metrics"].get("gini", 0)}</div>
                    <div class="stat-label">Arbitrum 지니 계수</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value warning">{data["kleros"]["arbitrum"]["metrics"].get("hhi", 0):,.0f}</div>
                    <div class="stat-label">Arbitrum HHI</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{data["kleros"]["ethereum"]["metrics"].get("nakamoto", 0)}</div>
                    <div class="stat-label">Ethereum 나카모토 계수</div>
                </div>
            </div>

            <div class="chart-container">
                <div class="chart-title">오라클 집중도 비교 (학술 지표)</div>
                <canvas id="oracleCompareChart" height="120"></canvas>
            </div>

            <div class="insight-box">
                <h4>Kleros vs UMA 비교</h4>
                <p>Kleros v2(Arbitrum)의 나카모토 계수는 <strong>{data["kleros"]["arbitrum"]["metrics"].get("nakamoto", 0)}</strong>로, UMA({data["uma_holders"]["metrics"]["nakamoto"]})보다 소폭 나은 수준이지만 여전히 2명이면 51%를 장악할 수 있습니다.
                지니 계수 {data["kleros"]["arbitrum"]["metrics"].get("gini", 0)}와 HHI {data["kleros"]["arbitrum"]["metrics"].get("hhi", 0):,.0f}는 UMA와 유사한 수준의 높은 집중도를 보여줍니다.</p>
            </div>

            <h3 style="margin: 30px 0 15px; color: #ccc;">Kleros (Arbitrum v2) 상위 10개 주소</h3>
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
                        <td class="address">{h["address"][:10]}...{h["address"][-8:]}</td>
                        <td>{h["balance"]:,.0f}</td>
                        <td>{h["balance"]/data["kleros"]["arbitrum"]["total_balance"]*100:.1f}%</td>
                    </tr>''' for i, h in enumerate(data["kleros"]["arbitrum"]["top_holders"]))}
                </tbody>
            </table>
        </section>

        <footer>
            <p>데이터 수집일: {pd.Timestamp.now().strftime("%Y-%m-%d")}</p>
            <p>Polymarket API & Etherscan API 기반</p>
        </footer>
    </div>

    <script>
        // 집중도 차트
        const concentrationData = {json.dumps(data["liquidity_concentration"])};
        new Chart(document.getElementById('concentrationChart'), {{
            type: 'bar',
            data: {{
                labels: concentrationData.map(d => 'Top ' + d.top_n),
                datasets: [{{
                    label: '거래량 점유율 (%)',
                    data: concentrationData.map(d => d.volume_share),
                    backgroundColor: 'rgba(255, 165, 0, 0.7)',
                    borderColor: 'rgba(255, 165, 0, 1)',
                    borderWidth: 1
                }}, {{
                    label: '유동성 점유율 (%)',
                    data: concentrationData.map(d => d.liquidity_share),
                    backgroundColor: 'rgba(255, 107, 107, 0.7)',
                    borderColor: 'rgba(255, 107, 107, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 100,
                        grid: {{ color: '#333' }},
                        ticks: {{ color: '#888' }}
                    }},
                    x: {{
                        grid: {{ color: '#333' }},
                        ticks: {{ color: '#888' }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        labels: {{ color: '#ccc' }}
                    }}
                }}
            }}
        }});

        // 분포 차트
        const distData = {json.dumps(data["liquidity_distribution"])};
        new Chart(document.getElementById('distributionChart'), {{
            type: 'bar',
            data: {{
                labels: distData.map(d => d.bucket),
                datasets: [{{
                    label: '마켓 수',
                    data: distData.map(d => d.count),
                    backgroundColor: 'rgba(100, 200, 255, 0.7)',
                    borderColor: 'rgba(100, 200, 255, 1)',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{
                        beginAtZero: true,
                        grid: {{ color: '#333' }},
                        ticks: {{ color: '#888' }}
                    }},
                    x: {{
                        grid: {{ color: '#333' }},
                        ticks: {{ color: '#888' }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        labels: {{ color: '#ccc' }}
                    }}
                }}
            }}
        }});

        // UMA 차트
        const umaConc = {json.dumps(data["uma_holders"]["concentration"])};
        new Chart(document.getElementById('umaChart'), {{
            type: 'doughnut',
            data: {{
                labels: ['상위 5명', '6-10위', '11-20위', '나머지'],
                datasets: [{{
                    data: [
                        umaConc.top5,
                        umaConc.top10 - umaConc.top5,
                        umaConc.top20 - umaConc.top10,
                        100 - umaConc.top20
                    ],
                    backgroundColor: [
                        'rgba(255, 107, 107, 0.8)',
                        'rgba(255, 165, 0, 0.8)',
                        'rgba(100, 200, 255, 0.8)',
                        'rgba(100, 100, 100, 0.8)'
                    ],
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{
                        position: 'right',
                        labels: {{ color: '#ccc' }}
                    }}
                }}
            }}
        }});

        // 오라클 비교 차트 - 학술 지표
        new Chart(document.getElementById('oracleCompareChart'), {{
            type: 'bar',
            data: {{
                labels: ['UMA', 'Kleros (Ethereum)', 'Kleros v2 (Arbitrum)'],
                datasets: [{{
                    label: '지니 계수',
                    data: [{data["uma_holders"]["metrics"]["gini"]}, {data["kleros"]["ethereum"]["metrics"].get("gini", 0)}, {data["kleros"]["arbitrum"]["metrics"].get("gini", 0)}],
                    backgroundColor: 'rgba(255, 107, 107, 0.8)',
                    borderWidth: 0
                }}, {{
                    label: '정규화 엔트로피 (역전)',
                    data: [{1 - data["uma_holders"]["metrics"]["normalized_entropy"]}, {1 - data["kleros"]["ethereum"]["metrics"].get("normalized_entropy", 0)}, {1 - data["kleros"]["arbitrum"]["metrics"].get("normalized_entropy", 0)}],
                    backgroundColor: 'rgba(255, 165, 0, 0.8)',
                    borderWidth: 0
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{
                        beginAtZero: true,
                        max: 1,
                        grid: {{ color: '#333' }},
                        ticks: {{ color: '#888' }}
                    }},
                    x: {{
                        grid: {{ color: '#333' }},
                        ticks: {{ color: '#ccc' }}
                    }}
                }},
                plugins: {{
                    legend: {{
                        labels: {{ color: '#ccc' }}
                    }},
                    title: {{
                        display: true,
                        text: '값이 높을수록 집중도 높음',
                        color: '#666'
                    }}
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

    # JSON 데이터도 저장 (디버깅용)
    json_path = SITE_DIR / "data.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"데이터 저장: {json_path}")


if __name__ == "__main__":
    main()
