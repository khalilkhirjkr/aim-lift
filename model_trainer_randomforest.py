# model_trainer.py

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import LabelEncoder # <-- Import LabelEncoder
import joblib
import numpy as np

print("--- AIM-Lift Multi-Class Model Trainer ---")

# --- Configuration ---
DATASET_PATH = 'final_training_dataset.csv'
MODEL_SAVE_PATH = 'lift_failure_model.pkl'
ENCODER_SAVE_PATH = 'lift_failure_encoder.pkl' # <-- Path to save the new encoder
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
TARGET_COLUMN = 'failure_type' # <-- We now train directly on this string column

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
print("Preparing data for multi-class classification...")

# 1. Initialize and fit the LabelEncoder
encoder = LabelEncoder()
df[TARGET_COLUMN] = encoder.fit_transform(df['failure_type'])

# --- This binary conversion is REMOVED ---
# df[TARGET_COLUMN] = df['failure_type'].apply(lambda x: 0 if x == 'No failure' else 1)

# 2. Save the fitted encoder to disk
try:
    joblib.dump(encoder, ENCODER_SAVE_PATH)
    print(f"[SUCCESS] Label encoder saved to '{ENCODER_SAVE_PATH}'")
    print(f"Classes learned by encoder: {encoder.classes_}")
except Exception as e:
    print(f"[ERROR] Failed to save label encoder: {e}")
    exit()

# 3. Separate features (X) and target (y)
try:
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN] # <-- This is now multi-class (0, 1, 2, 3...)
    print(f"Features selected for training: {FEATURE_COLUMNS}")
    print(f"Target value counts (encoded):\n{y.value_counts()}")
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
print("Training the Random Forest multi-class model...") # Update print statement
try:
    # Initialize the Random Forest model for multi-class
    # RandomForest handles multi-class automatically and uses class_weight
    model = RandomForestClassifier(
        n_estimators=100,
        random_state=RANDOM_STATE,
        class_weight='balanced' # Good for potentially imbalanced classes
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
    report = classification_report(
        y_test, 
        y_pred, 
        labels=encoder.transform(encoder.classes_), 
        target_names=encoder.classes_,
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