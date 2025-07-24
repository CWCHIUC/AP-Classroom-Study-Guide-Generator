# utils/data_analyzer.py
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import io 
import base64 

import matplotlib
matplotlib.use('Agg')

def analyze_data(file_path):
    try:
        df = pd.read_csv(file_path)

        # --- NEW: Add a check for required columns ---
        required_cols = ['Assessment Name', 'Percent Correct (teacher scored)', 'External Student ID']
        if not all(col in df.columns for col in required_cols):
            missing = [col for col in required_cols if col not in df.columns]
            print(f"Error: The uploaded CSV is missing the following required columns: {missing}")
            # Return the tuple that your app.py expects for an error condition
            return None, None, None

    except Exception as e:
        print(f"Error reading or validating CSV: {e}")
        return None, None, None

    # --- The rest of your function logic remains the same ---
    # Common preprocessing
    df_filtered = df[df["Assessment Name"].str.contains("Quiz|Assessment", case=False, na=False)].copy()

    df_filtered.loc[:, "Percent Correct"] = pd.to_numeric(
        df_filtered["Percent Correct (teacher scored)"].astype(str).str.replace('%', '', regex=False),
        errors='coerce'
    )

    df_filtered.dropna(subset=["Percent Correct"], inplace=True)

    if df_filtered.empty:
        print("No valid quiz/assessment data found after filtering.")
        return pd.DataFrame(), pd.DataFrame(), None

    df_scores = df_filtered.pivot_table(
        index="External Student ID",
        columns="Assessment Name",
        values="Percent Correct",
        aggfunc="mean"
    )

    df_scores["Average Score"] = df_scores.mean(axis=1)

    # --- Logic from Script 1: Personalized Study Guide ---
    threshold = 70
    student_weaknesses = df_scores.drop(columns=["Average Score"], errors='ignore') < threshold
    study_guides_df = df_scores.drop(columns=["Average Score"], errors='ignore').copy()
    study_guides_df = study_guides_df.where(student_weaknesses, "")

    # --- Logic from Script 2: Visualization and Prediction ---
    plot_base64_string = None
    try:
        plt.figure(figsize=(10, 6))
        sns.histplot(df_scores["Average Score"], bins=10, kde=True, color='skyblue')
        plt.axvline(70, color='red', linestyle='--', label='Threshold for AP 3-5 Prediction (70%)')
        plt.title("Distribution of Average Quiz/Assessment Scores")
        plt.xlabel("Average Score (%)")
        plt.ylabel("Number of Students")
        plt.legend()
        plt.tight_layout()

        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', bbox_inches='tight')
        img_buffer.seek(0)

        plot_base64_string = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
        img_buffer.close()

    except Exception as e:
        print(f"Error generating or encoding plot: {e}")
    finally:
        plt.close()

    df_scores["Likely 3-5"] = (df_scores["Average Score"] >= 70).map({True: 'Pass', False: 'Review'})
    predictions_df = df_scores[["Average Score", "Likely 3-5"]].copy()

    if "Average Score" in predictions_df:
        predictions_df["Average Score"] = predictions_df["Average Score"].round(1)

    predictions_df['Actions'] = '<button class="btn-generate">Study Guide</button>'
    
    return study_guides_df, predictions_df, plot_base64_string