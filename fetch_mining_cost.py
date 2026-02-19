import json
import csv
import requests
from datetime import datetime, timedelta
import os

# 파일 저장 설정
DATA_FILE = 'data.json'
BTC_HISTORY_FILE = 'btc_history.json'
BTC_CSV_FILE = 'BTC_USD.csv'

# === Cash Cost 모델 파라미터 ===
ELECTRICITY_LOW = 0.05
ELECTRICITY_HIGH = 0.07

# 네트워크 평균 효율 (J/TH) - 연도별 모델
# 실제 채굴기 세대별 효율 반영
EFFICIENCY_TABLE = [
    # (date, J/TH)
    ('2009-01-01', 9000),   # CPU mining
    ('2011-01-01', 5000),   # GPU mining
    ('2013-01-01', 1000),   # Early ASIC
    ('2014-01-01', 500),    # Antminer S1/S3
    ('2015-01-01', 340),    # Antminer S5
    ('2016-01-01', 250),    # Antminer S7
    ('2017-01-01', 100),    # Antminer S9
    ('2018-01-01', 95),     # Antminer S9 dominant
    ('2019-01-01', 70),     # S9 + S15/S17 mix
    ('2020-01-01', 55),     # S17/S19 mix
    ('2021-01-01', 45),     # S19 dominant
    ('2022-01-01', 38),     # S19 Pro/XP
    ('2023-01-01', 34),     # S19 XP + S21 early
    ('2024-01-01', 28),     # S21 rollout
    ('2025-01-01', 25),     # S21 dominant
    ('2026-01-01', 24),     # S21+ / next gen
]

# 오버헤드: 순수 Electrical Cost (Charles Edwards 모델 기준)
OVERHEAD_FACTOR = 1.0

TX_FEE_RATIO_PAST = 0.05
TX_FEE_RATIO_NOW = 0.08

# 반감기 목록
HALVINGS = [
    datetime(2012, 11, 28),  # 50 -> 25
    datetime(2016, 7, 9),    # 25 -> 12.5
    datetime(2020, 5, 11),   # 12.5 -> 6.25
    datetime(2024, 4, 20),   # 6.25 -> 3.125
]


def get_dynamic_efficiency(date):
    """연도별 효율 테이블에서 선형 보간"""
    table = [(datetime.strptime(d, '%Y-%m-%d'), v) for d, v in EFFICIENCY_TABLE]

    if date <= table[0][0]:
        return table[0][1]
    if date >= table[-1][0]:
        return table[-1][1]

    for i in range(len(table) - 1):
        if table[i][0] <= date < table[i + 1][0]:
            days_total = (table[i + 1][0] - table[i][0]).days
            days_elapsed = (date - table[i][0]).days
            ratio = days_elapsed / days_total if days_total > 0 else 0
            return table[i][1] + (table[i + 1][1] - table[i][1]) * ratio

    return table[-1][1]


def get_tx_fee_ratio(date):
    """트랜잭션 수수료 비율"""
    latest_halving = HALVINGS[-1]
    if date < latest_halving:
        return TX_FEE_RATIO_PAST
    d = (date - latest_halving).days
    return TX_FEE_RATIO_PAST + (TX_FEE_RATIO_NOW - TX_FEE_RATIO_PAST) * min(d / 180, 1.0)


def get_block_reward(date):
    """반감기별 블록 보상"""
    reward = 50.0
    for h in HALVINGS:
        if date >= h:
            reward /= 2
        else:
            break
    return reward


def calculate_cash_cost(hashrate_th_s, block_reward, electricity_price, date):
    """BTC당 Cash Cost = 전기료 / 일일 BTC 생산량"""
    efficiency = get_dynamic_efficiency(date)
    tx_fee_ratio = get_tx_fee_ratio(date)

    daily_btc = 144 * block_reward * (1 + tx_fee_ratio)
    daily_energy_kwh = (hashrate_th_s * efficiency * 86400) / 3_600_000
    daily_electricity = daily_energy_kwh * electricity_price * OVERHEAD_FACTOR

    return daily_electricity / daily_btc


def generate_btc_history_json():
    """Convert BTC_USD.csv to btc_history.json for frontend use"""
    if not os.path.exists(BTC_CSV_FILE):
        print(f"[INFO] {BTC_CSV_FILE} not found, skipping")
        return False

    print(f"[CSV] Reading {BTC_CSV_FILE}...")
    prices = {}
    with open(BTC_CSV_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row['Date'].strip()
            try:
                close = round(float(row['Close']), 2)
                prices[date] = close
            except (ValueError, KeyError):
                continue

    with open(BTC_HISTORY_FILE, 'w') as f:
        json.dump(prices, f)

    dates = sorted(prices.keys())
    print(f"   [OK] Generated {BTC_HISTORY_FILE}: {len(prices)} days ({dates[0]} ~ {dates[-1]})")
    return True


def fetch_data(url_path, timespan='all'):
    url = f"https://api.blockchain.info/charts/{url_path}"
    params = {'timespan': timespan, 'format': 'json'}
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()['values']
    except Exception as e:
        print(f"[ERR] Error fetching {url_path}: {e}")
        return None


def main():
    print("=== Bitcoin Mining Cost Data Fetch ===\n")

    # Generate btc_history.json from CSV
    generate_btc_history_json()

    # Fetch all available data from blockchain.info
    print("[API] Fetching hash-rate (all)...")
    hash_data = fetch_data('hash-rate', 'all')
    print("[API] Fetching market-price (all)...")
    price_data = fetch_data('market-price', 'all')

    if not hash_data or not price_data:
        print("[ERR] API data unavailable")
        return

    hash_dict = {datetime.utcfromtimestamp(i['x']).strftime('%Y-%m-%d'): i['y'] for i in hash_data}
    price_dict = {datetime.utcfromtimestamp(i['x']).strftime('%Y-%m-%d'): i['y'] for i in price_data}

    print(f"   [OK] Hash-rate: {len(hash_dict)} days")
    print(f"   [OK] Price: {len(price_dict)} days")

    common_dates = sorted(set(hash_dict.keys()) & set(price_dict.keys()))
    print(f"   [OK] Common dates: {len(common_dates)} ({common_dates[0]} ~ {common_dates[-1]})")

    results = {
        'dates': [], 'btc_prices': [], 'mining_cost_low': [],
        'mining_cost_mid': [], 'mining_cost_high': [], 'last_updated': ''
    }

    for d_str in common_dates:
        date_obj = datetime.strptime(d_str, '%Y-%m-%d')
        h_raw = hash_dict[d_str]
        reward = get_block_reward(date_obj)

        cost_low = calculate_cash_cost(h_raw, reward, ELECTRICITY_LOW, date_obj)
        cost_high = calculate_cash_cost(h_raw, reward, ELECTRICITY_HIGH, date_obj)
        cost_mid = (cost_low + cost_high) / 2

        results['dates'].append(d_str)
        results['btc_prices'].append(round(price_dict[d_str], 2))
        results['mining_cost_low'].append(round(cost_low, 2))
        results['mining_cost_mid'].append(round(cost_mid, 2))
        results['mining_cost_high'].append(round(cost_high, 2))

    # 14일 이동평균으로 스무딩
    def smooth(arr, window=14):
        result = []
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            result.append(round(sum(arr[start:i + 1]) / (i - start + 1), 2))
        return result

    results['mining_cost_low'] = smooth(results['mining_cost_low'])
    results['mining_cost_mid'] = smooth(results['mining_cost_mid'])
    results['mining_cost_high'] = smooth(results['mining_cost_high'])

    results['current_price'] = results['btc_prices'][-1]
    results['current_cost_mid'] = results['mining_cost_mid'][-1]
    results['current_cost_low'] = results['mining_cost_low'][-1]
    results['current_cost_high'] = results['mining_cost_high'][-1]
    results['last_updated'] = datetime.utcnow().isoformat() + 'Z'

    with open(DATA_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n[SAVE] Saved to {DATA_FILE}")
    print(f"   Date range: {results['dates'][0]} ~ {results['dates'][-1]}")
    print(f"   BTC Price: ${results['current_price']:,.0f}")
    print(f"   Cash Cost: ${results['current_cost_mid']:,.0f} "
          f"(${results['current_cost_low']:,.0f} - ${results['current_cost_high']:,.0f})")


if __name__ == '__main__':
    main()
