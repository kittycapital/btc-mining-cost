import json
import requests
from datetime import datetime, timedelta

# 파일 저장 설정
DATA_FILE = 'data.json'

# === 경제적 파라미터 ===

# 1. 전기료 ($/kWh) — 밴드를 $0.05–$0.07로 좁힘 (업계 컨센서스)
ELECTRICITY_LOW = 0.05
ELECTRICITY_HIGH = 0.07

# 2. 채굴기 효율성 (J/TH): 시간이 흐를수록 기술 발달로 낮아집니다.
EFFICIENCY_PAST = 38.0  # 2년 전 평균 (S19급)
EFFICIENCY_NOW = 22.0   # 현재 평균 (S19 XP, S21급 반영)

# 3. 오버헤드 계수: PUE(냉각/인프라) 1.1 + 풀 수수료 및 기타 1.05 = 약 1.15
OVERHEAD_FACTOR = 1.15

# 4. 하드웨어 감가상각 파라미터
#    - 네트워크 평균 ASIC 가격/성능 비율
#    - 과거: S19 Pro (110 TH/s, ~$3,000, 36개월 감가)
#    - 현재: S21 (200 TH/s, ~$5,000, 36개월 감가)
HW_COST_PER_TH_PAST = 3000 / 110   # $/TH (과거 ~$27.3/TH)
HW_COST_PER_TH_NOW = 5000 / 200    # $/TH (현재 ~$25.0/TH)
HW_DEPRECIATION_MONTHS = 36        # 감가상각 기간 (개월)

# 5. 트랜잭션 수수료 비율 (블록 보상 대비 추가 수익)
#    - 평상시 5~10%, 네트워크 혼잡 시 20%+
#    - 보수적으로 평균 8% 적용
TX_FEE_RATIO_PAST = 0.05    # 반감기 전 (수수료 비중 낮음)
TX_FEE_RATIO_NOW = 0.10     # 반감기 후 (보상 줄어 수수료 비중 증가)
HALVING_DATE = datetime(2024, 4, 20)


def get_dynamic_efficiency(date):
    """날짜에 따라 네트워크 평균 채굴 효율(J/TH)을 선형적으로 추정"""
    start_date = datetime.now() - timedelta(days=730)
    end_date = datetime.now()
    if date <= start_date: return EFFICIENCY_PAST
    if date >= end_date: return EFFICIENCY_NOW
    total_days = (end_date - start_date).days
    elapsed_days = (date - start_date).days
    return EFFICIENCY_PAST - ((EFFICIENCY_PAST - EFFICIENCY_NOW) * (elapsed_days / total_days))


def get_hw_cost_per_th(date):
    """날짜에 따라 네트워크 평균 $/TH 하드웨어 비용 추정"""
    start_date = datetime.now() - timedelta(days=730)
    end_date = datetime.now()
    if date <= start_date: return HW_COST_PER_TH_PAST
    if date >= end_date: return HW_COST_PER_TH_NOW
    total_days = (end_date - start_date).days
    elapsed_days = (date - start_date).days
    return HW_COST_PER_TH_PAST - ((HW_COST_PER_TH_PAST - HW_COST_PER_TH_NOW) * (elapsed_days / total_days))


def get_tx_fee_ratio(date):
    """날짜에 따라 트랜잭션 수수료 비율 추정 (반감기 전후 변화)"""
    if date < HALVING_DATE:
        return TX_FEE_RATIO_PAST
    # 반감기 이후 6개월에 걸쳐 5% -> 10%로 전환
    days_since = (date - HALVING_DATE).days
    ratio = TX_FEE_RATIO_PAST + (TX_FEE_RATIO_NOW - TX_FEE_RATIO_PAST) * min(days_since / 180, 1.0)
    return ratio


def get_block_reward(date):
    return 3.125 if date >= HALVING_DATE else 6.25


def calculate_mining_cost(hashrate_gh_s, block_reward, electricity_price, date):
    """
    채굴 원가 계산 (전기료 + 하드웨어 감가상각 - 수수료 수익)
    
    blockchain.info API는 해시레이트를 GH/s 단위로 반환합니다.
    """
    # 1. 단위 변환: API의 GH/s -> TH/s
    hashrate_th_s = hashrate_gh_s / 1_000
    
    # 2. 해당 날짜의 파라미터
    efficiency = get_dynamic_efficiency(date)
    tx_fee_ratio = get_tx_fee_ratio(date)
    hw_cost_per_th = get_hw_cost_per_th(date)
    
    # 3. 일일 네트워크 BTC 생산량 (블록보상 + 수수료)
    daily_btc_block_reward = 144 * block_reward
    daily_btc_total = daily_btc_block_reward * (1 + tx_fee_ratio)
    
    # 4. 전기료 원가
    seconds_per_day = 86400
    daily_energy_kwh = (hashrate_th_s * efficiency * seconds_per_day) / 3_600_000
    daily_electricity_cost = daily_energy_kwh * electricity_price * OVERHEAD_FACTOR
    
    # 5. 하드웨어 감가상각 원가 (일 단위)
    total_hw_value = hashrate_th_s * hw_cost_per_th
    daily_hw_depreciation = total_hw_value / (HW_DEPRECIATION_MONTHS * 30)
    
    # 6. BTC당 총 원가 = (전기료 + 감가상각) / 총 BTC 생산량
    total_daily_cost = daily_electricity_cost + daily_hw_depreciation
    cost_per_btc = total_daily_cost / daily_btc_total
    
    return cost_per_btc


def fetch_data(url_path):
    url = f"https://api.blockchain.info/charts/{url_path}"
    params = {'timespan': '2years', 'format': 'json', 'sampled': 'true'}
    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()['values']
    except Exception as e:
        print(f"Error fetching {url_path}: {e}")
        return None


def main():
    print("🚀 데이터 분석 시작...")
    
    hash_data = fetch_data('hash-rate')
    price_data = fetch_data('market-price')
    
    if not hash_data or not price_data:
        print("❌ API 데이터를 가져올 수 없습니다.")
        return

    # 날짜 기준 데이터 정렬
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
        
        cost_low = calculate_mining_cost(h_raw, reward, ELECTRICITY_LOW, date_obj)
        cost_high = calculate_mining_cost(h_raw, reward, ELECTRICITY_HIGH, date_obj)
        cost_mid = (cost_low + cost_high) / 2
        
        results['dates'].append(d_str)
        results['btc_prices'].append(round(price_dict[d_str], 2))
        results['mining_cost_low'].append(round(cost_low, 2))
        results['mining_cost_mid'].append(round(cost_mid, 2))
        results['mining_cost_high'].append(round(cost_high, 2))

    # 메타데이터 추가
    results['current_price'] = results['btc_prices'][-1]
    results['current_cost_mid'] = results['mining_cost_mid'][-1]
    results['current_cost_low'] = results['mining_cost_low'][-1]
    results['current_cost_high'] = results['mining_cost_high'][-1]
    results['last_updated'] = datetime.utcnow().isoformat() + 'Z'

    with open(DATA_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"✅ 완료! {DATA_FILE}이 생성되었습니다.")
    print(f"현재 비트코인 가격: ${results['current_price']:,.0f}")
    print(f"현재 추정 채굴 원가: ${results['current_cost_mid']:,.0f}")
    print(f"채굴 원가 범위: ${results['current_cost_low']:,.0f} — ${results['current_cost_high']:,.0f}")

if __name__ == '__main__':
    main()
