# lifts/predictor.py

import joblib
import pandas as pd
import numpy as np  # <-- Make sure numpy is imported
import os
from django.conf import settings

# --- Paths for BOTH model and encoder ---
MODEL_FILE = os.path.join(settings.BASE_DIR, 'lift_failure_model.pkl')
ENCODER_FILE = os.path.join(settings.BASE_DIR, 'lift_failure_encoder.pkl')

print("Attempting to load model and encoder...")
model = None
encoder = None

# --- Load Model ---
try:
    model = joblib.load(MODEL_FILE)
    print("[SUCCESS] Predictive model loaded successfully.")
except FileNotFoundError:
    print(f"[ERROR] Model file not found at '{MODEL_FILE}'.")
except Exception as e:
     print(f"[ERROR] Failed to load predictive model: {e}")

# --- Load Encoder ---
try:
    encoder = joblib.load(ENCODER_FILE)
    print(f"[SUCCESS] Label encoder loaded successfully. Classes: {encoder.classes_}")
except FileNotFoundError:
    print(f"[ERROR] Encoder file not found at '{ENCODER_FILE}'.")
except Exception as e:
     print(f"[ERROR] Failed to load label encoder: {e}")

# Features expected by the model
EXPECTED_FEATURES = [
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

def predict_lift_health(sensor_data):
    """
    Predicts the specific failure type and confidence.
    """
    if model is None:
        return "Model Not Loaded", 0.0
    if encoder is None:
        return "Encoder Not Loaded", 0.0

    try:
        # 1. Prepare input data from the dictionary
        input_data_prepared = {}
        for feature in EXPECTED_FEATURES:
            # Get the value from the original dictionary, default to 0.0
            input_data_prepared[feature] = sensor_data.get(feature, 0.0) 
        
        # 2. Create the DataFrame
        input_df = pd.DataFrame([input_data_prepared], columns=EXPECTED_FEATURES)
        
        # 3. --- THIS IS THE FIX ---
        # Explicitly cast all columns to float, as XGBoost requires it
        input_df = input_df.astype(float)
        # --- END OF FIX ---

        
        # 4. Get probabilities for all classes
        probabilities = model.predict_proba(input_df)[0] 
        
        # 5. Get the *highest* probability as the confidence
        confidence = np.max(probabilities)
        
        # 6. Get the *index* of that highest probability
        prediction_index = np.argmax(probabilities)
        
        # 7. Get the label for that index from the encoder
        prediction_label = encoder.classes_[prediction_index]

        # 8. Return the label and the confidence
        return prediction_label, confidence

    except Exception as e:
        print(f"[ERROR] An unexpected error occurred during prediction: {e}")
        return "Prediction Error", 0.0