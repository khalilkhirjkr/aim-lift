# model_trainer.py

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
import joblib
import numpy as np # Import numpy for checking labels

print("--- AIM-Lift Model Trainer ---")

# --- Configuration ---
DATASET_PATH = 'final_training_dataset.csv'
MODEL_SAVE_PATH = 'lift_failure_model.pkl'
TEST_SIZE = 0.2 # 20% for testing
RANDOM_STATE = 42

# --- Define Features ---
# *** UPDATED TO MATCH OUTPUT OF dataset_generator.py ***
# These are the renamed columns from p1-s3 + the simulated ones
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
TARGET_COLUMN = 'failure_type' # The binary 0/1 column we will create

# --- Load Data ---
try:
    df = pd.read_csv(DATASET_PATH)
    print("[SUCCESS] Final training dataset loaded successfully.")
    print(f"Dataset has {len(df)} rows.")
except FileNotFoundError:
    print(f"[ERROR] Dataset not found at {DATASET_PATH}. Run dataset_generator.py first.")
    exit()
except Exception as e:
    print(f"[ERROR] Failed to load dataset: {e}")
    exit()

# --- Prepare Data ---
print("Preparing data...")
# Create binary target column: 1 if any failure, 0 otherwise
df[TARGET_COLUMN] = df['failure_type'].apply(lambda x: 0 if x == 'No failure' else 1)

# Separate features (X) and target (y)
try:
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]
    print(f"Features selected for training: {FEATURE_COLUMNS}")
    print(f"Target value counts:\n{y.value_counts()}") # Show class distribution
except KeyError as e:
    # This error should now be fixed if FEATURE_COLUMNS is correct
    print(f"[ERROR] Feature column '{e}' not found in the dataset. Check FEATURE_COLUMNS list and {DATASET_PATH}.")
    exit()
except Exception as e:
     print(f"[ERROR] An unexpected error occurred during data preparation: {e}")
     exit()

# --- Split Data ---
try:
    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y # Ensure balanced split for training/testing
    )
    print(f"Splitting into {len(X_train)} training rows and {len(X_test)} testing rows.")
    print(f"Test set target value counts:\n{y_test.value_counts()}") # Verify test set distribution
except ValueError as e:
    print(f"[ERROR] Error during train_test_split: {e}")
    print("This can happen if there are too few samples of one class.")
    exit()

# --- Train Model ---
print("Training the Random Forest model...")
try:
    # Initialize the model
    model = RandomForestClassifier(n_estimators=100, random_state=RANDOM_STATE, class_weight='balanced')

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

    # Calculate accuracy
    accuracy = accuracy_score(y_test, y_pred)
    print(f"Model Accuracy on test data: {accuracy*100:.2f}%")

    # Generate classification report
    print("--- Classification Report ---")

    # Check unique labels present in y_test
    unique_labels = np.unique(y_test)
    present_labels = [label for label in [0, 1] if label in unique_labels]
    target_names_present = ['No failure' if label == 0 else 'Failure' for label in present_labels]

    if len(present_labels) > 0:
        report = classification_report(y_test, y_pred, labels=present_labels, target_names=target_names_present, zero_division=0)
        print(report)
    else:
        print("[WARNING] Test set contained no labels. Cannot generate classification report.")

except Exception as e:
    print(f"[ERROR] An error occurred during model evaluation: {e}")


# --- Save Model ---
try:
    joblib.dump(model, MODEL_SAVE_PATH)
    print(f"[SUCCESS] Trained model has been saved as '{MODEL_SAVE_PATH}'.")
    # Store feature names with the model if possible (good practice, though joblib doesn't do it by default easily)
    # print("Feature columns saved with model:", FEATURE_COLUMNS)
    print("This file can now be used for making real-time predictions.")
except Exception as e:
    print(f"[ERROR] Failed to save the model: {e}")