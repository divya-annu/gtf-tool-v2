import os
import zipfile
import pandas as pd
import numpy as np
from datetime import datetime

def institutional_gtf_engine(zip_file_path):
    if not os.path.exists(zip_file_path):
        raise FileNotFoundError(f"❌ Zip File Missing: {zip_file_path}")
        
    with zipfile.ZipFile(zip_file_path, 'r') as z:
        csv_files = [f for f in z.namelist() if f.endswith('.csv')]
        if not csv_files: raise ValueError("❌ No CSV inside Zip.")
        with z.open(csv_files[0]) as f:
            df = pd.read_csv(f)
            
    df.columns = [col.strip().upper() for col in df.columns]
    df = df[df['SYMBOL'] == 'NIFTY']
    if df.empty: return None, None

    rename_dict = {
        'STRIKE_PRICE': 'STRIKE_PR', 'OPTION_TYPE': 'OPTION_TYP',
        'OPEN_INTEREST': 'OPEN_INT', 'CHANGE_IN_OI': 'CHG_IN_OI', 'LTP': 'CLOSE'
    }
    df.rename(columns={k: v for k, v in rename_dict.items() if k in df.columns}, inplace=True)

    ce_df = df[df['OPTION_TYP'] == 'CE'].copy()
    pe_df = df[df['OPTION_TYP'] == 'PE'].copy()
    
    chain = pd.merge(
        ce_df[['STRIKE_PR', 'OPEN_INT', 'CHG_IN_OI', 'CLOSE', 'UNDERLYING']],
        pe_df[['STRIKE_PR', 'OPEN_INT', 'CHG_IN_OI', 'CLOSE']],
        on='STRIKE_PR', suffixes=('_CE', '_PE')
    )
    
    chain.sort_values(by='STRIKE_PR', inplace=True)
    chain.reset_index(drop=True, inplace=True)
    
    spot_price = chain['UNDERLYING_CE'].iloc[0] if 'UNDERLYING_CE' in chain.columns else chain['STRIKE_PR'].median()
    
    # GTF Logic 
    atm_strike = chain.iloc[(chain['STRIKE_PR'] - spot_price).abs().argsort()[:1]]
    atm_straddle_premium = atm_strike['CLOSE_CE'].values[0] + atm_strike['CLOSE_PE'].values[0]
    implied_buffer = atm_straddle_premium * 0.15
    
    chain['GTF_CALL_SELLER_SL'] = np.where(chain['OPEN_INT_CE'] > 0, chain['STRIKE_PR'] + chain['CLOSE_CE'] + implied_buffer, 0)
    chain['GTF_PUT_SELLER_SL'] = np.where(chain['OPEN_INT_PE'] > 0, chain['STRIKE_PR'] - chain['CLOSE_PE'] - implied_buffer, 0)
    
    chain['CALL_TRAP'] = np.where((spot_price >= chain['GTF_CALL_SELLER_SL']) & (chain['CHG_IN_OI_CE'] < 0), '🚨 CRITICAL TRAP', np.where(spot_price >= chain['STRIKE_PR'] + chain['CLOSE_CE'], '⚠️ PRESSURE', '✅ SAFE'))
    chain['PUT_TRAP'] = np.where((spot_price <= chain['GTF_PUT_SELLER_SL']) & (chain['CHG_IN_OI_PE'] < 0), '🚨 CRITICAL TRAP', np.where(spot_price <= chain['STRIKE_PR'] - chain['CLOSE_PE'], '⚠️ PRESSURE', '✅ SAFE'))
    
    # Filter ATM range (+/- 400 points)
    chain = chain[(chain['STRIKE_PR'] >= spot_price - 400) & (chain['STRIKE_PR'] <= spot_price + 400)]
    
    display_columns = [
        'STRIKE_PR', 'OPEN_INT_CE', 'CHG_IN_OI_CE', 'CLOSE_CE', 'GTF_CALL_SELLER_SL', 'CALL_TRAP',
        'OPEN_INT_PE', 'CHG_IN_OI_PE', 'CLOSE_PE', 'GTF_PUT_SELLER_SL', 'PUT_TRAP'
    ]
    return chain[display_columns], spot_price

def generate_html_dashboard(df, spot):
    now_str = datetime.now().strftime('%d-%b-%Y %I:%M %p')
    
    # HTML and CSS for Dark-Themed Professional UI
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>GTF Algorithmic Option Chain</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #121824; color: #e2e8f0; margin: 0; padding: 20px; }}
            .container {{ max-width: 1400px; margin: 0 auto; }}
            .header {{ text-align: center; padding: 20px; background: #1e293b; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid #3b82f6; }}
            h1 {{ margin: 0; color: #3b82f6; font-size: 24px; }}
            .meta {{ margin-top: 10px; font-size: 14px; color: #94a3b8; }}
            .spot-box {{ font-size: 22px; font-weight: bold; color: #10b981; background: #064e3b; display: inline-block; padding: 10px 20px; border-radius: 5px; margin-top: 10px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 10px; background: #1e293b; border-radius: 8px; overflow: hidden; font-size: 13px; }}
            th {{ background-color: #0f172a; color: #3b82f6; padding: 12px; text-align: center; border: 1px solid #334155; }}
            th.pe-header {{ color: #ec4899; }}
            td {{ padding: 10px; text-align: center; border: 1px solid #334155; font-weight: 500; }}
            .strike-cell {{ background-color: #0f172a; font-weight: bold; color: #f59e0b; font-size: 15px; }}
            .trap-critical {{ background-color: #7f1d1d !important; color: #fca5a5; font-weight: bold; animation: blink 1.5s infinite; }}
            .trap-pressure {{ background-color: #78350f !important; color: #fde68a; }}
            .safe {{ color: #10b981; }}
            tr:hover {{ background-color: #2d3748; }}
            @keyframes blink {{ 0% {{ opacity: 0.7; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.7; }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 GTF INSTITUTIONAL ALGORITHMIC ENGINE</h1>
                <div class="meta">Last Synced Data: {now_str} (IST)</div>
                <div class="spot-box">NIFTY SPOT: {spot}</div>
            </div>
            <table>
                <thead>
                    <tr>
                        <th colspan="5">CALL SELLERS ZONE (CE)</th>
                        <th>CENTER</th>
                        <th colspan="5">PUT SELLERS ZONE (PE)</th>
                    </tr>
                    <tr>
                        <th>OI</th>
                        <th>Chg OI</th>
                        <th>LTP (CE)</th>
                        <th>Seller SL</th>
                        <th>Status</th>
                        <th>STRIKE</th>
                        <th>OI</th>
                        <th>Chg OI</th>
                        <th>LTP (PE)</th>
                        <th>Seller SL</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for _, row in df.iterrows():
        # Dynamic Row Styling based on traps
        c_trap_class = "trap-critical" if "CRITICAL" in row['CALL_TRAP'] else ("trap-pressure" if "PRESSURE" in row['CALL_TRAP'] else "safe")
        p_trap_class = "trap-critical" if "CRITICAL" in row['PUT_TRAP'] else ("trap-pressure" if "PRESSURE" in row['PUT_TRAP'] else "safe")
        
        html_content += f"""
                    <tr>
                        <td>{int(row['OPEN_INT_CE'])}</td>
                        <td>{int(row['CHG_IN_OI_CE'])}</td>
                        <td>{row['CLOSE_CE']:.2f}</td>
                        <td>{row['GTF_CALL_SELLER_SL']:.2f}</td>
                        <td class="{c_trap_class}">{row['CALL_TRAP']}</td>
                        
                        <td class="strike-cell">{int(row['STRIKE_PR'])}</td>
                        
                        <td>{int(row['OPEN_INT_PE'])}</td>
                        <td>{int(row['CHG_IN_OI_PE'])}</td>
                        <td>{row['CLOSE_PE']:.2f}</td>
                        <td>{row['GTF_PUT_SELLER_SL']:.2f}</td>
                        <td class="{p_trap_class}">{row['PUT_TRAP']}</td>
                    </tr>
        """
        
    html_content += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("🖥️ Dashboard HTML (index.html) built successfully!")

if __name__ == "__main__":
    zip_name = "fo_bhavcopy.zip" 
    df_result, spot = institutional_gtf_engine(zip_name)
    if df_result is not None:
        generate_html_dashboard(df_result, spot)
