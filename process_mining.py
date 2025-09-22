import pm4py, json
import pandas as pd
from datetime import datetime

# Read the event log directly as a DataFrame
df = pd.read_csv("temp/event_log.csv")

# Convert to pm4py event log format
log = pm4py.format_dataframe(df, case_id='case_id', activity_key='event_label', timestamp_key='start_time')

# 1) Variant probabilities
variants = pm4py.get_variants(log)
total = sum(variants.values())
variant_probs = {str(v): cnt/total for v,cnt in variants.items()}

# 2) Activity durations - calculate from the event log
activities = df['event_label'].unique()
print("Activities found:", activities)

# Calculate mean and std for each activity from the actual data
mean_sec = {}
std_sec = {}

for activity in activities:
    activity_rows = df[df['event_label'] == activity].copy()
    if len(activity_rows) > 0:
        # Convert timestamps to datetime
        activity_rows['start_time'] = pd.to_datetime(activity_rows['start_time'])
        activity_rows['completion_time'] = pd.to_datetime(activity_rows['completion_time'])
        
        # Calculate duration in seconds
        durations = (activity_rows['completion_time'] - activity_rows['start_time']).dt.total_seconds()
        
        # Calculate mean and standard deviation
        mean_sec[activity] = float(durations.mean()) if not durations.isna().all() else 3600
        std_sec[activity] = float(durations.std()) if not durations.isna().all() else 1800
        
        print(f"Activity {activity}: mean={mean_sec[activity]:.0f}s, std={std_sec[activity]:.0f}s")

with open("pm_params.json","w") as f:
    json.dump({
      "variant_probs": variant_probs,
      "mean_sec": mean_sec,
      "std_sec": std_sec
    }, f, indent=2)
print("→ pm_params.json written")