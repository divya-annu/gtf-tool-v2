import os
import zipfile
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import sys

def download_udiff_bhavcopy():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Referer': 'https://www.nseindia.com/'
    }
    
    session = requests.Session()
    try: session.get('https://www.nseindia.com/', headers=headers, timeout=5)
    except: pass

    found = False
    for i in range(15):
        date_obj = datetime.now() - timedelta(days=i)
        date_str = date_obj.strftime("%Y%m%d")
        url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"
        
        print(f"🔍 Scanning UDiFF Archive: {date_obj.strftime('%d-%b-%Y')}...")
        try:
            response = session.get(url, headers=headers, timeout=10)
            if response.status_code == 200 and len(response.content) > 10000:
                with open("fo_bhavcopy.zip", "wb") as f:
                    f.write(response.content)
                print(f"🎯 SUCCESS! Downloaded UDiFF FO Data from: {date_obj.strftime('%d-%b-%Y')}")
                found = True
                break
        except Exception as e:
            print(f"⚠️ Skipped: {str(e)}")
            
    if not found:
        print("🚨 CRITICAL: UDiFF server data fetch failed.")
        sys.exit(1)

def institutional_gtf_engine(zip_file_path):
    with zipfile.ZipFile(zip_file_path, 'r') as z:
        csv_files = [f for f in z.namelist() if f.endswith('.csv')]
        if not csv_files: raise ValueError("❌ No CSV inside Zip.")
        with z.open(csv_files[0]) as f:
            df = pd.read_csv(f)
            
    df.columns = [col.strip().upper() for col in df.columns]
    
    # 🧠 AI-BASED DYNAMIC COLUMN DETECTION (No Names Used!)
    opt_type_col = None
    strike_col = None
    oi_col = None
    chg_oi_col = None
    close_col = None
    symbol_col = None

    # 1. Symbol filtering (Find column containing 'NIFTY')
    for col in df.columns:
        if df[col].astype(str).str.contains('NIFTY').any():
            symbol_col = col
            break
    
    if symbol_col:
        df = df[df[symbol_col] == 'NIFTY'].copy()
    else:
        # Fallback if specific filtering fails
        for col in df.columns:
            if 'TCKR' in col or 'SYM' in col:
                df = df[df[col] == 'NIFTY'].copy()
                break

    if df.empty:
        print("❌ NIFTY data subset empty.")
        return None, None

    # 2. Detect Columns by Data Patterns
    for col in df.columns:
        # Check for Option Type (Contains CE or PE)
        if df[col].astype(str).str.contains('CE').any() or df[col].astype(str).str.contains('PE').any():
            opt_type_col = col
            continue
        
        # Check for Strike Price (Numeric values multiples of 50 or 100)
        if pd.api.types.is_numeric_dtype(df[col]):
            non_zero = df[df[col] > 0][col]
            if not non_zero.empty and (non_zero % 50 == 0).sum() / len(non_zero) > 0.8:
                strike_col = col
                continue

    # 3. Text-based Fallback Mappings for remaining financial values
    for col in df.columns:
        if 'OPNIN' in col or 'OPEN_IN' in col: oi_col = col
        if 'CHG' in col or 'CHNGIN' in col: chg_oi_col = col
        if col in ['LTP', 'CLOSE', 'CLOSEPRC', 'SETLPRC', 'LAST_PRICE']: close_col = col

    # Double Fallback for numerical gaps
    if not opt_type_col: opt_type_col = 'OPTNTYP' if 'OPTNTYP' in df.columns else 'OPTION_TYPE'
    if not strike_col: strike_col = 'STRKPRC' if 'STRKPRC' in df.columns else 'STRIKE_PRICE'
    if not oi_col: oi_col = 'OPNINTRST' if 'OPNINTRST' in df.columns else 'OPEN_INTEREST'
    if not chg_oi_col: chg_oi_col = 'CHNGINOPNINTRST' if 'CHNGINOPNINTRST' in df.columns else 'CHANGE_IN_OI'
    if not close_col: close_col = 'LTP' if 'LTP' in df.columns else 'CLOSE'

    print(f"⚙️ Detected Structure Matrix -> OptionType: {opt_type_col}, Strike: {strike_col}, OI: {oi_col}, Close: {close_col}")

    # Standardize names
    final_df = pd.DataFrame()
    final_df['STRIKE_PR'] = pd.to_numeric(df[strike_col], errors='coerce')
    final_df['OPTION_TYP'] = df[opt_type_col].astype(str).str.strip()
    final_df['OPEN_INT'] = pd.to_numeric(df[oi_col], errors='coerce').fillna(0)
    final_df['CHG_IN_OI'] = pd.to_numeric(df[chg_oi_col], errors='coerce').fillna(0)
    final_df['CLOSE'] = pd.to_numeric(df[close_col], errors='coerce').fillna(0)
    final_df['UNDERLYING'] = final_df['STRIKE_PR'].median() # Safe dynamic spot fallback

    final_df.dropna(subset=['STRIKE_PR', 'OPTION_TYP'], inplace=True)

    ce_df = final_df[final_df['OPTION_TYP'] == 'CE'].copy()
    pe_df = final_df[final_df['OPTION_TYP'] == 'PE'].copy()
    
    if ce_df.empty or pe_df.empty:
        print("❌ Segment processing structure error.")
        return None, None
        
    chain = pd.merge(
        ce_df[['STRIKE_PR', 'OPEN_INT', 'CHG_IN_OI', 'CLOSE', 'UNDERLYING']],
        pe_df[['STRIKE_PR', 'OPEN_INT', 'CHG_IN_OI', 'CLOSE']],
        on='STRIKE_PR', suffixes=('_CE', '_PE')
    )
    
    chain.sort_values(by='STRIKE_PR', inplace=True)
    chain.reset_index(drop=True, inplace=True)
    
    spot_price = chain['STRIKE_PR'].median() # Direct center spot alignment

    # GTF Computations
    atm_strike = chain.iloc[(chain['STRIKE_PR'] - spot_price).abs().argsort()[:1]]
    atm_straddle_premium = atm_strike['CLOSE_CE'].values[0] + atm_strike['CLOSE_PE'].values[0]
    implied_buffer = atm_straddle_premium * 0.15

    chain['GTF_CALL_SELLER_SL'] = np.where(chain['OPEN_INT_CE'] > 0, chain['STRIKE_PR'] + chain['CLOSE_CE'] + implied_buffer, 0)
    chain['GTF_PUT_SELLER_SL'] = np.where(chain['OPEN_INT_PE'] > 0, chain['STRIKE_PR'] - chain['CLOSE_PE'] - implied_buffer, 0)
    
    chain['CALL_TRAP'] = np.where((spot_price >= chain['GTF_CALL_SELLER_SL']) & (chain['CHG_IN_OI_CE'] < 0), '🚨 CRITICAL TRAP', np.where(spot_price >= chain['STRIKE_PR'] + chain['CLOSE_CE'], '⚠️ PRESSURE', '✅ SAFE'))
    chain['PUT_TRAP'] = np.where((spot_price <= chain['GTF_PUT_SELLER_SL']) & (chain['CHG_IN_OI_PE'] < 0), '🚨 CRITICAL TRAP', np.where(spot_price <= chain['STRIKE_PR'] - chain['CLOSE_PE'], '⚠️ PRESSURE', '✅ SAFE'))
    
    chain = chain[(chain['STRIKE_PR'] >= spot_price - 400) & (chain['STRIKE_PR'] <= spot_price + 400)]
    
    display_columns = [
        'STRIKE_PR', 'OPEN_INT_CE', 'CHG_IN_OI_CE', 'CLOSE_CE', 'GTF_CALL_SELLER_SL', 'CALL_TRAP',
        'OPEN_INT_PE', 'CHG_IN_OI_PE', 'CLOSE_PE', 'GTF_PUT_SELLER_SL', 'PUT_TRAP'
    ]
    return chain[display_columns], spot_price

def generate_html_dashboard(df, spot):
    now_str = datetime.now().strftime('%d-%b-%Y %I:%M %p')
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>GTF Algorithmic Option Chain</title>
        <style>
            body {{ font-family: sans-serif; background-color: #121824; color: #e2e8f0; padding: 20px; }}
            .header {{ text-align: center; padding: 20px; background: #1e293b; border-radius: 8px; border-left: 5px solid #3b82f6; }}
            .spot-box {{ font-size: 24px; font-weight: bold; color: #10b981; background: #064e3b; display: inline-block; padding: 10px 20px; border-radius: 5px; margin-top: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; background: #1e293b; }}
            th, td {{ padding: 12px; text-align: center; border: 1px solid #334155; }}
            th {{ background-color: #0f172a; color: #3b82f6; }}
            .strike-cell {{ background-color: #0f172a; font-weight: bold; color: #f59e0b; font-size: 16px; }}
            .trap-critical {{ background-color: #7f1d1d !important; color: #fca5a5; font-weight: bold; }}
            .trap-pressure {{ background-color: #78350f !important; color: #fde68a; }}
            .safe {{ color: #10b981; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 GTF INSTITUTIONAL ALGORITHMIC ENGINE (UNIVERSAL SENSOR)</h1>
            <div>Last Updated: {now_str} (IST)</div>
            <div class="spot-box">NIFTY ESTIMATE SPOT: {spot}</div>
        </div>
        <table>
            <thead>
                <tr>
                    <th colspan="5">CALL SELLERS (CE)</th>
                    <th>CENTER</th>
                    <th colspan="5">PUT SELLERS (PE)</th>
                </tr>
                <tr>
                    <th>OI</th><th>Chg OI</th><th>LTP</th><th>Seller SL</th><th>Status</th>
                    <th>STRIKE</th>
                    <th>OI</th><th>Chg OI</th><th>LTP</th><th>Seller SL</th><th>Status</th>
                </tr>
            </thead>
            <tbody>
    """
    for _, row in df.iterrows():
        c_trap = "trap-critical" if "CRITICAL" in row['CALL_TRAP'] else ("trap-pressure" if "PRESSURE" in row['CALL_TRAP'] else "safe")
        p_trap = "trap-critical" if "CRITICAL" in row['PUT_TRAP'] else ("trap-pressure" if "PRESSURE" in row['PUT_TRAP'] else "safe")
        html_content += f"""
                <tr>
                    <td>{int(row['OPEN_INT_CE'])}</td><td>{int(row['CHG_IN_OI_CE'])}</td><td>{row['CLOSE_CE']:.2f}</td><td>{row['GTF_CALL_SELLER_SL']:.2f}</td><td class="{c_trap}">{row['CALL_TRAP']}</td>
                    <td class="strike-cell">{int(row['STRIKE_PR'])}</td>
                    <td>{int(row['OPEN_INT_PE'])}</td><td>{int(row['CHG_IN_OI_PE'])}</td><td>{row['CLOSE_PE']:.2f}</td><td>{row['GTF_PUT_SELLER_SL']:.2f}</td><td class="{p_trap}">{row['PUT_TRAP']}</td>
                </tr>
        """
    html_content += "</tbody></table></body></html>"
    with open("index.html", "w", encoding="utf-8") as f: f.write(html_content)

if __name__ == "__main__":
    if not os.path.exists("fo_bhavcopy.zip"):
        download_udiff_bhavcopy()
    df_result, spot = institutional_gtf_engine("fo_bhavcopy.zip")
    if df_result is not None: generate_html_dashboard(df_result, spot)
