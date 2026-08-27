# dataset_generator.py

import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timedelta
import random # Ensure random is imported

print("--- AIM-Lift Dataset Generator ---")

# --- Configuration ---
KAGGLE_DATASET_PATH = 'maintenance-failure-prediction-dataset.csv'
DB_PATH = 'db.sqlite3'
OUTPUT_DATASET_PATH = 'final_training_dataset.csv'
NUM_ROWS_TARGET = 5000
FAILURE_PERCENTAGE = 0.40 # Target percentage of failure data (e.g., 40%)

# Define the sensor columns we want to keep/simulate
SIMULATED_SENSOR_COLUMNS = [
    'vibration',
    'vertical_acceleration_mps2',
    'acoustic_db'
]

# Rename columns for consistency (lowercase, underscores)
# *** UPDATED TO USE COLUMNS FROM THE PROVIDED CSV ***
COLUMN_RENAME_MAP = {
    'p1': 'feature_p1',
    'p2': 'feature_p2',
    'p3': 'feature_p3',
    's1': 'feature_s1',
    's2': 'feature_s2',
    's3': 'feature_s3',
    'failure type': 'failure_type' # Corrected key to lowercase 'failure type'
}

# --- Database Interaction (Optional) ---
print(f"Connecting to database: {DB_PATH}...")
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT lift_identifier FROM lifts_lift")
    lift_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    print(f"[SUCCESS] Extracted {len(lift_ids)} lifts.")
    if not lift_ids:
        print("[WARNING] No lifts found in the database.")
        lift_ids = ['SIMULATED_LIFT_1']
except Exception as e:
    print(f"[ERROR] Could not connect to or query database: {e}")
    lift_ids = ['SIMULATED_LIFT_1']


# --- Load and Prepare Kaggle Data ---
print(f"Loading Kaggle sensor data from: {KAGGLE_DATASET_PATH}...")
try:
    # Read CSV more robustly and explicitly
    df_kaggle = pd.read_csv(KAGGLE_DATASET_PATH, sep=',', engine='python')

    # Print columns exactly as read by pandas
    print("\nColumns read by pandas:")
    print(list(df_kaggle.columns))
    print("-" * 20 + "\n")

    # Verify the failure type column exists using the expected lowercase name
    actual_failure_col_name = 'failure type' # Confirmed from pandas output
    if actual_failure_col_name not in df_kaggle.columns:
         raise KeyError(f"Column '{actual_failure_col_name}' not found in CSV columns read by pandas: {list(df_kaggle.columns)}")

    print(f"Using failure column: '{actual_failure_col_name}'")


    # Keep only relevant columns + Failure Type
    columns_to_keep = list(COLUMN_RENAME_MAP.keys())
    # Check if all required columns exist in the dataframe
    missing_cols = [col for col in columns_to_keep if col not in df_kaggle.columns]
    if missing_cols:
        # This error should not trigger now if COLUMN_RENAME_MAP is correct
        raise ValueError(f"Missing required columns in CSV: {missing_cols}")

    df_kaggle_filtered = df_kaggle[columns_to_keep].copy()

    # Rename columns using the map
    df_kaggle_filtered.rename(columns=COLUMN_RENAME_MAP, inplace=True)

    # Separate normal and failure data (using the renamed 'failure_type' column)
    df_normal = df_kaggle_filtered[df_kaggle_filtered['failure_type'] == 'No failure'].copy()
    df_failure = df_kaggle_filtered[df_kaggle_filtered['failure_type'] != 'No failure'].copy()

    print(f"[SUCCESS] Loaded {len(df_normal)} normal and {len(df_failure)} failure readings.")

    if df_failure.empty:
        print("[ERROR] No failure data found in the Kaggle dataset after filtering/renaming. Cannot generate balanced dataset.")
        exit()
    if df_normal.empty:
        print("[ERROR] No normal data found in the Kaggle dataset after filtering/renaming.")
        exit()

except FileNotFoundError:
    print(f"[ERROR] Kaggle dataset not found at {KAGGLE_DATASET_PATH}")
    exit()
except (KeyError, ValueError) as e:
    # Catch specific errors related to column names
    print(f"[ERROR] {e}")
    exit()
except Exception as e:
    print(f"[ERROR] Failed to load or process Kaggle data: {e}")
    exit()

# --- Simulate Additional Sensor Data ---
# (Keep the simulate_extra_sensors function and its calls as they were)
print("Simulating additional sensor data (vibration, acceleration, acoustic)...")

def simulate_extra_sensors(df, is_failure_data=False):
    num_rows = len(df)
    if is_failure_data:
        df['vibration'] = np.random.uniform(20, 50, num_rows)
        df['vertical_acceleration_mps2'] = np.random.uniform(0.5, 2.0, num_rows)
        df['acoustic_db'] = np.random.uniform(80, 100, num_rows)
    else:
        df['vibration'] = np.random.uniform(0.1, 5.0, num_rows)
        df['vertical_acceleration_mps2'] = np.random.uniform(0.01, 0.2, num_rows)
        df['acoustic_db'] = np.random.uniform(55, 65, num_rows)
    return df

df_normal = simulate_extra_sensors(df_normal, is_failure_data=False)
df_failure = simulate_extra_sensors(df_failure, is_failure_data=True)


# --- Generate Final Dataset ---
# (Keep the sampling and combining logic as it was)
print("Generating new dataset...")

num_failure_target = int(NUM_ROWS_TARGET * FAILURE_PERCENTAGE)
num_normal_target = NUM_ROWS_TARGET - num_failure_target

df_failure_sampled = df_failure.sample(n=num_failure_target, replace=len(df_failure) < num_failure_target, random_state=42)
df_normal_sampled = df_normal.sample(n=num_normal_target, replace=len(df_normal) < num_normal_target, random_state=42)

df_final = pd.concat([df_normal_sampled, df_failure_sampled], ignore_index=True)


# Add lift identifiers
if lift_ids:
    df_final['lift_identifier'] = [random.choice(lift_ids) for _ in range(len(df_final))]
else:
    df_final['lift_identifier'] = 'UNKNOWN_LIFT'

# Add Timestamps
end_time = datetime.now()
start_time = end_time - timedelta(days=30)
total_seconds = int((end_time - start_time).total_seconds())
random_seconds = np.random.randint(0, total_seconds, len(df_final))
df_final['timestamp'] = [start_time + timedelta(seconds=int(s)) for s in random_seconds]
df_final.sort_values(by='timestamp', inplace=True)

# Select final columns - ONLY sensor data, timestamp, lift_id, and target
# Get the renamed sensor columns dynamically from the map's values
final_sensor_columns = [col for col in COLUMN_RENAME_MAP.values() if col != 'failure_type']
final_sensor_columns += SIMULATED_SENSOR_COLUMNS # Add simulated cols

final_columns = final_sensor_columns + ['timestamp', 'lift_identifier', 'failure_type'] # Metadata and target

# Ensure only existing columns are selected
final_columns = [col for col in final_columns if col in df_final.columns]
df_final = df_final[final_columns]


# --- Save Final Dataset ---
# (Keep the saving logic as it was)
try:
    df_final.to_csv(OUTPUT_DATASET_PATH, index=False)
    print(f"[SUCCESS] Complete dataset with {len(df_final)} rows ({len(df_failure_sampled)} failure examples) has been saved to '{OUTPUT_DATASET_PATH}'.")
    print("This dataset is now ready for training your model.")
except Exception as e:
    print(f"[ERROR] Failed to save the final dataset: {e}")