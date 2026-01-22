"""
Bitcoin Mining Cost Calculator
Fetches hashrate data from blockchain.com and calculates mining cost over 2 years.
"""

import json
import requests
from datetime import datetime, timedelta

# Configuration
DATA_FILE = 'data.json'

# Mining parameters
EFFICIENCY_J_PER_TH = 25  # Joules per Terahash (industry average for modern miners)
ELECTRICITY_LOW = 0.05    # $/kWh (efficient miners)
ELECTRICITY_MID = 0.06    # $/kWh (average)
ELECTRICITY_HIGH = 0.07   # $/kWh (less efficient)

# Halving date - block reward changed from 6.25 to 3.125
HALVING_DATE = datetime(2024, 4, 20)


def get_block_reward(date):
    """Get block reward based on date (accounting for halving)"""
    if date >= HALVING_DATE:
        return 3.125
    else:
        return 6.25


def calculate_mining_cost(hashrate_th_s, block_reward, electricity_price):
    """
    Calculate the cost to mine 1 BTC.
    
    Args:
        hashrate_th_s: Network hashrate in TH/s
        block_reward: BTC reward per block
        electricity_price: Cost per kWh in USD
    
    Returns:
        Cost to mine 1 BTC in USD
    """
    # Daily BTC produced by the network
    blocks_per_day = 144
    daily_btc = blocks_per_day * block_reward
    
    # Daily energy consumption (kWh)
    # Hashrate (TH/s) × Efficiency (J/TH) × seconds_per_day / 1,000,000 (J to kWh)
    seconds_per_day = 86400
    joules_per_day = hashrate_th_s * EFFICIENCY_J_PER_TH * seconds_per_day
    kwh_per_day = joules_per_day / 3_600_000  # 1 kWh = 3,600,000 J
    
    # Daily electricity cost
    daily_cost = kwh_per_day * electricity_price
    
    # Cost per BTC
    cost_per_btc = daily_cost / daily_btc
    
    return cost_per_btc


def fetch_hashrate_data():
    """Fetch 2 years of hashrate data from blockchain.com"""
    print("📡 Fetching hashrate data from blockchain.com...")
    
    url = "https://api.blockchain.info/charts/hash-rate"
    params = {
        'timespan': '2years',
        'format': 'json',
        'sampled': 'true'  # Reduces data points for performance
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        print(f"   ✅ Got {len(data['values'])} data points")
        return data['values']
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None


def fetch_btc_price_data():
    """Fetch 2 years of BTC price data from blockchain.com"""
    print("📡 Fetching BTC price data from blockchain.com...")
    
    url = "https://api.blockchain.info/charts/market-price"
    params = {
        'timespan': '2years',
        'format': 'json',
        'sampled': 'true'
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        print(f"   ✅ Got {len(data['values'])} data points")
        return data['values']
    
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return None


def align_data(hashrate_data, price_data):
    """Align hashrate and price data by date"""
    print("🔄 Aligning data...")
    
    # Convert to dictionaries keyed by date
    hashrate_by_date = {}
    for item in hashrate_data:
        date = datetime.utcfromtimestamp(item['x']).strftime('%Y-%m-%d')
        hashrate_by_date[date] = item['y']
    
    price_by_date = {}
    for item in price_data:
        date = datetime.utcfromtimestamp(item['x']).strftime('%Y-%m-%d')
        price_by_date[date] = item['y']
    
    # Find common dates
    common_dates = sorted(set(hashrate_by_date.keys()) & set(price_by_date.keys()))
    
    print(f"   ✅ {len(common_dates)} common dates")
    
    return common_dates, hashrate_by_date, price_by_date


def main():
    print("🚀 Starting Bitcoin Mining Cost calculation...\n")
    
    # Fetch data
    hashrate_data = fetch_hashrate_data()
    price_data = fetch_btc_price_data()
    
    if not hashrate_data or not price_data:
        print("❌ Failed to fetch data")
        return
    
    # Align data
    dates, hashrate_by_date, price_by_date = align_data(hashrate_data, price_data)
    
    # Calculate mining costs
    print("\n💰 Calculating mining costs...")
    
    results = {
        'dates': [],
        'btc_prices': [],
        'mining_cost_low': [],
        'mining_cost_mid': [],
        'mining_cost_high': [],
        'hashrates': []
    }
    
    for date_str in dates:
        date = datetime.strptime(date_str, '%Y-%m-%d')
        hashrate = hashrate_by_date[date_str]
        price = price_by_date[date_str]
        block_reward = get_block_reward(date)
        
        # Calculate costs for different electricity prices
        cost_low = calculate_mining_cost(hashrate, block_reward, ELECTRICITY_LOW)
        cost_mid = calculate_mining_cost(hashrate, block_reward, ELECTRICITY_MID)
        cost_high = calculate_mining_cost(hashrate, block_reward, ELECTRICITY_HIGH)
        
        results['dates'].append(date_str)
        results['btc_prices'].append(round(price, 2))
        results['mining_cost_low'].append(round(cost_low, 2))
        results['mining_cost_mid'].append(round(cost_mid, 2))
        results['mining_cost_high'].append(round(cost_high, 2))
        results['hashrates'].append(round(hashrate, 2))
    
    # Get current values
    current_price = results['btc_prices'][-1]
    current_cost = results['mining_cost_mid'][-1]
    current_hashrate = results['hashrates'][-1]
    
    print(f"\n📊 Current Stats:")
    print(f"   BTC Price: ${current_price:,.0f}")
    print(f"   Mining Cost (mid): ${current_cost:,.0f}")
    print(f"   Hashrate: {current_hashrate / 1e9:.2f} EH/s")
    print(f"   Margin: {((current_price - current_cost) / current_cost * 100):.1f}%")
    
    # Add metadata
    results['current_price'] = current_price
    results['current_cost_low'] = results['mining_cost_low'][-1]
    results['current_cost_mid'] = current_cost
    results['current_cost_high'] = results['mining_cost_high'][-1]
    results['current_hashrate_eh'] = round(current_hashrate / 1e9, 2)
    results['last_updated'] = datetime.utcnow().isoformat() + 'Z'
    results['parameters'] = {
        'efficiency_j_per_th': EFFICIENCY_J_PER_TH,
        'electricity_low': ELECTRICITY_LOW,
        'electricity_mid': ELECTRICITY_MID,
        'electricity_high': ELECTRICITY_HIGH
    }
    
    # Save to JSON
    with open(DATA_FILE, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n💾 Saved to {DATA_FILE}")


if __name__ == '__main__':
    main()
