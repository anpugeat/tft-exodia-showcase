"""
versions.py: Here we store daily analyses as 'versions' and track trending comps over time.

Each daily run of the analysis pipeline produces a snapshot at `data/analysis_YYYY-MM-DD.csv`.
This module looks back at `lookback_days` prior versions to calculate a 'trend_factor' for each comp.
"""

import pandas as pd
import hashlib
import ast
import os
import glob
from datetime import datetime
from scipy.stats import linregress


def comp_id(composition):
    """
    Creates a unique 10-char hash for a given composition. 
    This is so that we can track the same comp across different days for trend analysis.
    """
    try:
        units_tuple = ast.literal_eval(composition)
    except (ValueError, SyntaxError):
        units_tuple = composition
    # Sort first to ensure the same set of units produces the same ID regardless of input order.
    units = tuple(sorted(units_tuple))
    return hashlib.md5(str(units).encode()).hexdigest()[:10]

def compute_trend_factor(df, filepath='data', lookback_days=3):
    """
    Computes a trend factor and "is_new" flag for each composition in `df`.

    Looks at the last `lookback_days` versions to calculate a trend factor for each comp.
    - The trend factor is calculated as the slope of the line of best fit for the pick rate of the comp over time.
    - The is_new flag is a boolean flag indicating whether the comp is new to the dataset.
    """
    prior_files = sorted(glob.glob(os.path.join(filepath, 'analysis_*.csv')))
    today_str = datetime.now().strftime('%Y-%m-%d')
    prior_files = [f for f in prior_files if today_str not in os.path.basename(f)]
    prior_files = prior_files[-lookback_days:]

    if not prior_files:
        # No history at all — everything is new
        return df['pickRate'].copy(), pd.Series(True, index=df.index)

    history_rows = []
    for f in prior_files:
        date_str = os.path.basename(f).replace('analysis_', '').replace('.csv', '')
        run_date = pd.to_datetime(date_str)
        hist = pd.read_csv(f, usecols=['unique_id', 'pickRate'])
        hist['run_date'] = run_date
        history_rows.append(hist)

    history = pd.concat(history_rows, ignore_index=True)
    seen_ids = set(history['unique_id'].unique())

    today_df = pd.DataFrame({
        'unique_id': df['unique_id'].values,
        'pickRate': df['pickRate'].values,
        'run_date': pd.to_datetime(today_str),
    })
    history = pd.concat([history, today_df], ignore_index=True)

    def _slope(group):
        # Linear slope of pickRate over time (in days) for a single composition.
        if len(group) < 2:
            return None
        group = group.sort_values('run_date')
        days = (group['run_date'] - group['run_date'].min()).dt.days.values
        if days.max() == 0:
            return None
        if len(group) == 2:
            return (group['pickRate'].iloc[-1] - group['pickRate'].iloc[0]) / days[-1]
        return linregress(days, group['pickRate'].values).slope

    slopes = history.groupby('unique_id').apply(_slope)

    trend = df['unique_id'].map(slopes)
    trend = trend.fillna(df['pickRate'])
    is_new = ~df['unique_id'].isin(seen_ids)
    return trend, is_new


def version_manager(df, filepath='data', lookback_days=3, trending_quantile=0.9):
    """
    Main function to manage versioning and trending comps.
    - Adds a unique_id column to the dataframe for each composition.
    - Computes a trend factor and is_new flag for each composition.
    - Flags the top decile of trend_factor as trending.
    - Saves the dataframe to a CSV file.
    """
    df['unique_id'] = df['composition'].apply(comp_id)
    df['trend_factor'], df['is_new'] = compute_trend_factor(
        df, filepath=filepath, lookback_days=lookback_days
    )

    # Flag top decile of trend_factor as trending
    cutoff = df['trend_factor'].quantile(trending_quantile)
    df['trending'] = (df['trend_factor'] >= cutoff) & ~df['is_new']

    current_date = datetime.now().strftime('%Y-%m-%d')
    filename = f"analysis_{current_date}.csv"
    os.makedirs(filepath, exist_ok=True)
    full_path = os.path.join(filepath, filename)
    df.to_csv(full_path, index=False)

    print(f"Dataframe successfully saved to: {full_path}")
    return df
