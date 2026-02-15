import json
import requests
from datetime import datetime, timedelta

# 파일 저장 설정
DATA_FILE = 'data.json'

# === Cash Cost 모델 파라미터 ===
# HW 감가상각 제외 — 순수 전기료 + 운영비 기준
# 채굴자가 "돌릴지 말지" 결정하는 실질 손익분기점

# 1. 전기료 ($/kWh) — 밴드: $0.05–$0.07
ELECTRICITY_LOW = 0.05
ELECTRICITY_HIGH = 0.07

# 2. 네트워크 평균 효율 (J/TH)
#    2023 초: S19 주력 ~36 J/TH
#    2026 현재: S19 XP + S21 혼합 ~25 J/TH
EFFICIENCY_PAST = 36.0
EFFICIENCY_NOW = 25.0

# 3. 오버헤드: 순수 Electrical Cost (Charles Edwards 모델 기준)
#    TradingView BTC:Electrical Cost와 동일한 방식
OVERHEAD_FACTOR = 1.0

# 4. 트랜잭션 수수료 비율
TX_FEE_RATIO_PAST = 0.05   # 반감기 전
TX_FEE_RATIO_NOW = 0.08    # 반감기 후

# 반감기 날짜
HALVING_DATE = datetime(2024, 4, 20)


def get_dynamic_efficiency(date):
    """네트워크 평균 효율 선형 보간"""
    start = datetime.now() - timedelta(days=1095)
    end = datetime.now()
    if date <= start: return EFFICIENCY_PAST
    if date >= end: return EFFICIENCY_NOW
    r = (date - start).days / (end - start).days
    return EFFICIENCY_PAST + (EFFICIENCY_NOW - EFFICIENCY_PAST) * r


def get_tx_fee_ratio(date):
    """트랜잭션 수수료 비율 (반감기 후 6개월에 걸쳐 점진 증가)"""
    if date < HALVING_DATE: return TX_FEE_RATIO_PAST
    d = (date - HALVING_DATE).days
    return TX_FEE_RATIO_PAST + (TX_FEE_RATIO_NOW - TX_FEE_RATIO_PAST) * min(d / 180, 1.0)


def get_block_reward(date):
    return 3.125 if date >= HALVING_DATE else 6.25


def calculate_cash_cost(hashrate_th_s, block_reward, electricity_price, date):
    """
    BTC당 Cash Cost = 전기료 / 일일 BTC 생산량
    
    HW 감가상각 제외 — 채굴기를 가동할지 말지 결정하는 기준점.
    blockchain.info API는 해시레이트를 TH/s 단위로 반환.
    """
    efficiency = get_dynamic_efficiency(date)
    tx_fee_ratio = get_tx_fee_ratio(date)
    
    daily_btc = 144 * block_reward * (1 + tx_fee_ratio)
    daily_energy_kwh = (hashrate_th_s * efficiency * 86400) / 3_600_000
    daily_electricity = daily_energy_kwh * electricity_price * OVERHEAD_FACTOR
    
    return daily_electricity / daily_btc


def fetch_data(url_path):
    url = f"https://api.blockchain.info/charts/{url_path}"
    params = {'timespan': '3years', 'format': 'json', 'sampled': 'true'}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()['values']
    except Exception as e:
        print(f"Error fetching {url_path}: {e}")
        return None


def main():
    print("🚀 Cash Cost 데이터 생성 시작...")
    
    hash_data = fetch_data('hash-rate')
    price_data = fetch_data('market-price')
    
    if not hash_data or not price_data:
        print("❌ API 데이터를 가져올 수 없습니다.")
        return

    hash_dict = {datetime.utcfromtimestamp(i['x']).strftime('%Y-%m-%d'): i['y'] for i in hash_data}
    price_dict = {datetime.utcfromtimestamp(i['x']).strftime('%Y-%m-%d'): i['y'] for i in price_data}
    
    common_dates = sorted(set(hash_dict.keys()) & set(price_dict.keys()))
    
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

    # 14일 이동평균으로 스무딩 (변동성 감소)
    def smooth(arr, window=14):
        result = []
        for i in range(len(arr)):
            start = max(0, i - window + 1)
            result.append(round(sum(arr[start:i+1]) / (i - start + 1), 2))
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
    
    print(f"✅ 완료! {DATA_FILE}")
    print(f"BTC Price: ${results['current_price']:,.0f}")
    print(f"Cash Cost: ${results['current_cost_mid']:,.0f} ({results['current_cost_low']:,.0f} — {results['current_cost_high']:,.0f})")

if __name__ == '__main__':
    main()
