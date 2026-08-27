# Predictive Maintenance Data Analyzer
# This script is for running on your computer to analyze the dataset.
# It is NOT for Django or the ESP32.

# First, you need to install the necessary Python libraries.
# Open your command prompt (with your venv activated) and run:
# pip install pandas scikit-learn matplotlib

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import matplotlib.pyplot as plt

print("--- AIM-Lift Predictive Maintenance Data Analyzer ---")

# --- Step 1: Load and Explore the Data ---
try:
    # Load the dataset from the CSV file
    df = pd.read_csv('predictive-maintenance-dataset.csv')
    print("\n[SUCCESS] Dataset loaded successfully.")
    print("Dataset has {} rows and {} columns.".format(df.shape[0], df.shape[1]))

    # Display the first 5 rows to see what the data looks like
    print("\nFirst 5 rows of data:")
    print(df.head())

    # Display summary statistics (like mean, std, etc.) for each column
    print("\nSummary statistics:")
    print(df.describe())

except FileNotFoundError:
    print("\n[ERROR] 'predictive-maintenance-dataset.csv' not found.")
    print("Please make sure the CSV file is in the same folder as this script.")
    exit()


# --- Step 2: Define a "Failure" Condition ---
# The dataset does not have a "failure" column. We will create one.
# For this example, let's assume a "failure" happens if vibration is unusually high.
# We'll set a simple threshold. In a real project, this would be more complex.
VIBRATION_FAILURE_THRESHOLD = 22 

# Create a new 'failure' column. It will be 1 if vibration > threshold, otherwise 0.
df['failure'] = (df['vibration'] > VIBRATION_FAILURE_THRESHOLD).astype(int)

failure_count = df['failure'].sum()
print(f"\nDefined a 'failure' condition: vibration > {VIBRATION_FAILURE_THRESHOLD} g")
print(f"Found {failure_count} instances of failure in the dataset.")


# --- Step 3: Prepare Data for Training ---
# We will use sensor readings to predict the 'failure' column.
features = ['revolutions', 'humidity', 'vibration', 'x1', 'x2', 'x3', 'x4', 'x5']
target = 'failure'

X = df[features]
y = df[target]

# Split the data: 80% for training the model, 20% for testing it
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

print(f"\nSplitting data: {len(X_train)} rows for training, {len(X_test)} for testing.")


# --- Step 4: Train a Simple Machine Learning Model ---
# We use a RandomForestClassifier, which is good for this type of problem.
print("\nTraining the Random Forest model...")
model = RandomForestClassifier(n_estimators=50, random_state=42, n_jobs=-1)
model.fit(X_train, y_train)
print("[SUCCESS] Model training complete.")


# --- Step 5: Test the Model's Accuracy ---
# Let's see how well our model performs on the test data it has never seen before.
y_pred = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)

print(f"\nModel Accuracy on test data: {accuracy * 100:.2f}%")


# --- Step 6: Simulate a Prediction ---
# This is what would happen on the ESP32.
# Let's create two new "live" sensor readings.

# A reading that looks normal
normal_reading = [[
    93,  # revolutions
    74,  # humidity
    18,  # vibration
    167, 19, 1.2, 8787, 5475 # x1-x5
]]

# A reading that looks like a potential failure
failure_reading = [[
    110, # revolutions are high
    78,  # humidity is high
    23,  # VIBRATION IS ABOVE OUR THRESHOLD
    180, 22, 1.5, 9500, 5800 # x1-x5
]]

# Use our trained model to make predictions
normal_prediction = model.predict(normal_reading)
failure_prediction = model.predict(failure_reading)

print("\n--- Simulating Real-Time Predictions ---")
print(f"Prediction for normal reading: {'Failure Imminent' if normal_prediction[0] == 1 else 'Normal'}")
print(f"Prediction for high-vibration reading: {'Failure Imminent' if failure_prediction[0] == 1 else 'Normal'}")


# --- Step 7: Visualize Feature Importance ---
# Let's see which sensor reading was most important to the model's decisions.
print("\nGenerating feature importance plot...")
importances = model.feature_importances_
feature_names = X.columns
plt.figure(figsize=(10, 6))
plt.bar(feature_names, importances)
plt.title('Feature Importance for Predicting Failures')
plt.ylabel('Importance')
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig('feature_importance.png')
print("Plot saved as 'feature_importance.png'.")
