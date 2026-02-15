import json
import requests
from datetime import datetime, timedelta

# 파일 저장 설정
DATA_FILE = 'data.json'

# --- 경제적 파라미터 (전문 차트 기준) ---
# 1. 전기료 ($/kWh): 글로벌 평균 채굴 비용은 보통 0.07$ 내외입니다.
ELECTRICITY_LOW = 0.05
ELECTRICITY_MID = 0.07
ELECTRICITY_HIGH = 0.09

# 2. 채굴기 효율성 (J/TH): 시간이 흐를수록 기술 발달로 낮아집니다.
EFFICIENCY_PAST = 38.0  # 2년 전 평균 (S19급)
EFFICIENCY_NOW = 22.0   # 현재 평균 (S19 XP, S21급 반영)

# 3. 추가 비용 계수: PUE(냉각/인프라) 1.1 + 풀 수수료 및 기타 1.05 = 약 1.15
OVERHEAD_FACTOR = 1.15

# 반감기 날짜 (보상 6.25 -> 3.125)
HALVING_DATE = datetime(2024, 4, 20)

def get_dynamic_efficiency(date):
    """날짜에 따라 네트워크 평균 채굴 효율(J/TH)을 선형적으로 추정"""
    start_date = datetime.now() - timedelta(days=730) # 2년 전
    end_date = datetime.now()
    
    if date <= start_date: return EFFICIENCY_PAST
    if date >= end_date: return EFFICIENCY_NOW
    
    total_days = (end_date - start_date).days
    elapsed_days = (date - start_date).days
    
    # 과거에서 현재로 올수록 J/TH 수치가 낮아짐 (효율 개선)
    efficiency = EFFICIENCY_PAST - ((EFFICIENCY_PAST - EFFICIENCY_NOW) * (elapsed_days / total_days))
    return efficiency

def get_block_reward(date):
    return 3.125 if date >= HALVING_DATE else 6.25

def calculate_mining_cost(hashrate_gh_s, block_reward, electricity_price, date):
    """
    채굴 원가 계산
    
    주의: blockchain.info API는 해시레이트를 GH/s 단위로 반환합니다.
    GH/s -> TH/s 변환: / 1,000
    """
    # 1. 단위 변환: API의 GH/s -> TH/s
    hashrate_th_s = hashrate_gh_s / 1_000
    
    # 2. 해당 날짜의 추정 효율성
    efficiency = get_dynamic_efficiency(date)
    
    # 3. 하루 생산량 및 소모 전력 계산
    # 일일 생산 BTC = 144 블록 * 블록 보상
    daily_btc_network = 144 * block_reward
    
    # 일일 전체 네트워크 에너지 소모량 (kWh)
    # (TH/s * J/TH * 86400초) / 3,600,000 (J -> kWh 변환)
    seconds_per_day = 86400
    daily_energy_kwh = (hashrate_th_s * efficiency * seconds_per_day) / 3_600_000
    
    # 4. 오버헤드 반영 및 최종 원가 계산
    total_daily_cost = daily_energy_kwh * electricity_price * OVERHEAD_FACTOR
    cost_per_btc = total_daily_cost / daily_btc_network
    
    return cost_per_btc

def fetch_data(url_path):
    url = f"https://api.blockchain.info/charts/{url_path}"
    params = {'timespan': '2years', 'format': 'json', 'sampled': 'true'}
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()
        return r.json()['values']
    except Exception as e:
        print(f"Error fetching {url_path}: {e}")
        return None

def main():
    print("🚀 데이터 분석 시작...")
    
    hash_data = fetch_data('hash-rate')
    price_data = fetch_data('market-price')
    
    if not hash_data or not price_data: return

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
        
        results['dates'].append(d_str)
        results['btc_prices'].append(round(price_dict[d_str], 2))
        results['mining_cost_low'].append(round(calculate_mining_cost(h_raw, reward, ELECTRICITY_LOW, date_obj), 2))
        results['mining_cost_mid'].append(round(calculate_mining_cost(h_raw, reward, ELECTRICITY_MID, date_obj), 2))
        results['mining_cost_high'].append(round(calculate_mining_cost(h_raw, reward, ELECTRICITY_HIGH, date_obj), 2))

    # 메타데이터 추가
    results['current_price'] = results['btc_prices'][-1]
    results['current_cost_mid'] = results['mining_cost_mid'][-1]
    results['current_cost_low'] = results['mining_cost_low'][-1]
    results['current_cost_high'] = results['mining_cost_high'][-1]
    results['last_updated'] = datetime.utcnow().isoformat() + 'Z'

    with open(DATA_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"✅ 완료! {DATA_FILE}이 생성되었습니다.")
    print(f"현재 비트코인 가격: ${results['current_price']:,}")
    print(f"현재 추정 채굴 원가: ${results['current_cost_mid']:,}")
    print(f"채굴 원가 범위: ${results['current_cost_low']:,} — ${results['current_cost_high']:,}")

if __name__ == '__main__':
    main()
