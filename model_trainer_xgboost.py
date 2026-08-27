# model_trainer.py

import pandas as pd
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier # <-- Use XGBoost again
from sklearn.metrics import accuracy_score, classification_report
# from sklearn.preprocessing import LabelEncoder # <-- REMOVE LabelEncoder
import joblib
import numpy as np

print("--- AIM-Lift BINARY Model Trainer ---") # Updated title

# --- Configuration ---
DATASET_PATH = 'final_training_dataset.csv'
MODEL_SAVE_PATH = 'lift_failure_model.pkl'
# ENCODER_SAVE_PATH = 'lift_failure_encoder.pkl' # <-- REMOVE Encoder path
TEST_SIZE = 0.2
RANDOM_STATE = 42

# --- Define Features ---
FEATURE_COLUMNS = [
    'feature_p1',
    'feature_p2',
    'feature_p3',
    'feature_s1',
    'feature_s2',
    'feature_s3',
    'vibration',
    'vertical_acceleration_mps2',
    'acoustic_db'
]
TARGET_COLUMN = 'failure_type_binary' # <-- Use a new name for clarity

# --- Load Data ---
try:
    df = pd.read_csv(DATASET_PATH)
    print(f"[SUCCESS] Final training dataset loaded ({len(df)} rows).")
except FileNotFoundError:
    print(f"[ERROR] Dataset not found at {DATASET_PATH}. Run dataset_generator.py first.")
    exit()
except Exception as e:
    print(f"[ERROR] Failed to load dataset: {e}")
    exit()

# --- Prepare Data ---
print("Preparing data for BINARY classification...")

# --- RE-ADD Binary Conversion ---
# Create binary target column: 1 if any failure, 0 otherwise
df[TARGET_COLUMN] = df['failure_type'].apply(lambda x: 0 if x == 'No failure' else 1)
# --- End of Binary Conversion ---

# --- REMOVE LabelEncoder ---
# encoder = LabelEncoder()
# df[TARGET_COLUMN] = encoder.fit_transform(df['failure_type'])
# joblib.dump(encoder, ENCODER_SAVE_PATH)
# print(f"[SUCCESS] Label encoder saved...")
# --- End of REMOVE LabelEncoder ---

# Separate features (X) and target (y)
try:
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN] # <-- This is now binary (0 or 1)
    print(f"Features selected for training: {FEATURE_COLUMNS}")
    print(f"Target value counts (binary):\n{y.value_counts()}")
except KeyError as e:
    print(f"[ERROR] Feature column '{e}' not found.")
    exit()

# --- Split Data ---
try:
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y
    )
    print(f"Splitting into {len(X_train)} training and {len(X_test)} testing rows.")
except ValueError as e:
    print(f"[ERROR] Error during train_test_split: {e}")
    exit()

# --- Train Model ---
print("Training the XGBoost BINARY model...")
try:
    # Calculate scale_pos_weight for binary classification
    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum() if (y_train == 1).sum() > 0 else 1

    # Initialize the XGBoost model for BINARY classification
    model = XGBClassifier(
        n_estimators=100,
        random_state=RANDOM_STATE,
        objective='binary:logistic', # <-- Set objective for binary
        scale_pos_weight=scale_pos_weight # Handle imbalance
        # num_class is not needed for binary
    )

    # Train the model
    model.fit(X_train, y_train)
    print("[SUCCESS] Model training complete.")
except Exception as e:
    print(f"[ERROR] An error occurred during model training: {e}")
    exit()

# --- Evaluate Model ---
print("Evaluating model performance...")
try:
    y_pred = model.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    print(f"Model Accuracy on test data: {accuracy*100:.2f}%")

    print("--- Classification Report ---")
    # Adjust target names for binary
    target_names_binary = ['No failure', 'Failure']
    report = classification_report(
        y_test,
        y_pred,
        labels=[0, 1], # Binary labels
        target_names=target_names_binary,
        zero_division=0
    )
    print(report)
except Exception as e:
    print(f"[ERROR] An error occurred during model evaluation: {e}")

# --- Save Model ---
try:
    joblib.dump(model, MODEL_SAVE_PATH)
    print(f"[SUCCESS] Trained model has been saved as '{MODEL_SAVE_PATH}'.")
except Exception as e:
    print(f"[ERROR] Failed to save the model: {e}")