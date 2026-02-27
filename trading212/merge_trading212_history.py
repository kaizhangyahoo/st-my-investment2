import pandas as pd
import os

def merge_trading212_history(path: str) -> pd.DataFrame:
    files = [f for f in os.listdir(path) if f.endswith('.csv') and f.startswith("from")]
    if not files:
        print(f"No matching CSV files found in {path}")
        return pd.DataFrame()
    
    df = pd.concat([pd.read_csv(os.path.join(path, f)) for f in files])
    
    # Convert Time to datetime to allow min() and max() to work correctly
    df['Time'] = pd.to_datetime(df['Time'])
    
    df_trading212 = df.drop_duplicates(subset=['ID'], keep='first')
    
    # Sort by Time for consistency
    df_trading212 = df_trading212.sort_values(by='Time')
    
    min_date = df_trading212['Time'].min().strftime('%Y-%m-%d')
    max_date = df_trading212['Time'].max().strftime('%Y-%m-%d')
    filename = f"from_{min_date}_to_{max_date}_trading212.csv"
    
    output_path = os.path.join(path, filename)
    df_trading212.to_csv(output_path, index=False)
    print(f"Merged history saved to {output_path}")
    return df_trading212

if __name__ == "__main__":
    # Use the directory where the script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    df_trading212 = merge_trading212_history(script_dir)
    
    if not df_trading212.empty:
        print(df_trading212.head())
        print(df_trading212.tail())
        print(f"Total records: {len(df_trading212)}")