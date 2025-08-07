import os
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, send_file, session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from utils.data_analyzer import analyze_data
from utils.guide_generator import get_weak_topics_and_subject, extract_text_from_pdf, create_study_guide_text, create_pdf_from_text
import pandas as pd
import io
import uuid # <-- Import for generating unique IDs

load_dotenv()

ALLOWED_EXTENSIONS = {'csv'}

app = Flask(__name__)
app.secret_key = 'your_very_secret_key' # Make sure this is set!

# --- SOLUTION: A simple in-memory cache ---
# This dictionary will store the CSV data on the server temporarily.
# The key will be a unique ID that we store in the user's session cookie.
CACHE = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            csv_data_bytes = file.read()
            csv_data_stream = io.BytesIO(csv_data_bytes)
            
            study_guides_df, predictions_df, plot_b64 = analyze_data(csv_data_stream)
          
            if study_guides_df is None and predictions_df is None and plot_b64 is None:
                flash('Upload failed. Make sure you are uploading the correct file with the required columns.')
                return redirect(request.url)

            # --- MODIFICATION: The name mapping now also uses the in-memory data ---
            try:
                csv_data_stream.seek(0) 
                df_names = pd.read_csv(csv_data_stream)
                
                required_cols = ['External Student ID', 'First Name', 'Last Name']
                if all(col in df_names.columns for col in required_cols):
                    name_map = df_names[required_cols].copy()
                    name_map.dropna(subset=['External Student ID', 'First Name', 'Last Name'], inplace=True)
                    name_map['Student Name'] = name_map['First Name'] + ' ' + name_map['Last Name']
                    name_map['External Student ID'] = name_map['External Student ID'].astype(int)
                    name_map = name_map[['External Student ID', 'Student Name']].drop_duplicates().set_index('External Student ID')

                    if predictions_df is not None and not predictions_df.empty:
                        predictions_df = predictions_df.merge(name_map, how='left', left_index=True, right_index=True)
                        if 'Student Name' in predictions_df.columns:
                            cols = ['Student Name'] + [col for col in predictions_df.columns if col != 'Student Name']
                            predictions_df = predictions_df[cols]

                    if study_guides_df is not None and not study_guides_df.empty:
                        study_guides_df = study_guides_df.merge(name_map, how='left', left_index=True, right_index=True)
                        if 'Student Name' in study_guides_df.columns:
                            cols = ['Student Name'] + [col for col in study_guides_df.columns if col != 'Student Name']
                            study_guides_df = study_guides_df[cols]
                else:
                    flash("Could not find 'External Student ID', 'First Name', or 'Last Name' columns.")
            except Exception as e:
                print(f"Error during name mapping: {e}")
                flash(f"An error occurred while adding student names: {e}")

            # --- SOLUTION: Store the large data in the server-side CACHE ---
            # 1. Generate a unique ID for this data
            cache_id = str(uuid.uuid4())
            # 2. Store the actual CSV bytes in our global CACHE dictionary
            CACHE[cache_id] = csv_data_bytes
            # 3. Store ONLY the small, unique ID in the session cookie
            session['csv_cache_id'] = cache_id

            study_guides_html = study_guides_df.to_html(na_rep='', border=0, justify='center') if isinstance(study_guides_df, pd.DataFrame) and not study_guides_df.empty else None
            predictions_html = predictions_df.to_html(na_rep='N/A', border=0, index=True, justify='center', escape=False) if isinstance(predictions_df, pd.DataFrame) and not predictions_df.empty else None

            return render_template('results.html',
                                   study_guides_html=study_guides_html,
                                   predictions_html=predictions_html,
                                   plot_b64=plot_b64,
                                   csv_filename=filename)
        else:
            flash('Invalid file type. Please upload a CSV file.')
            return redirect(request.url)
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_guide_route():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not api_key.strip():
        return jsonify({'error': 'Server configuration error: API key is missing.'}), 500
    
    # --- SOLUTION: Retrieve the data from the server-side CACHE ---
    # 1. Get the unique ID from the session cookie
    cache_id = session.get('csv_cache_id')
    if not cache_id:
        return jsonify({'error': 'Session expired or data not found. Please upload the CSV again.'}), 400
    
    # 2. Use the ID to get the data from our CACHE dictionary
    csv_data_bytes = CACHE.get(cache_id)
    if not csv_data_bytes:
        return jsonify({'error': 'Cached data has expired. Please upload the CSV again.'}), 400

    csv_data_stream = io.BytesIO(csv_data_bytes)

    student_id = request.form.get('student_id')
    if 'ced_file' not in request.files:
        return jsonify({'error': 'No Course and Exam Description file provided.'}), 400
  
    ced_file = request.files['ced_file']
    if ced_file.filename == '' or not ced_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a valid PDF file.'}), 400

    try:
        weak_topics, subject = get_weak_topics_and_subject(int(student_id), csv_data_stream)
        
        if not weak_topics:
            return jsonify({'error': f'No topics requiring review found for student {student_id}.'}), 404

        ced_text = extract_text_from_pdf(ced_file.stream)
        if not ced_text:
            return jsonify({'error': 'Could not read content from the provided PDF.'}), 500

        guide_text = create_study_guide_text(weak_topics, ced_text, api_key, subject)

        pdf_bytes = create_pdf_from_text(guide_text)
        pdf_stream = io.BytesIO(pdf_bytes)
        
        output_filename = f"study_guide_{student_id}.pdf"

        # Optional: Clean up the cache after use to save memory
        # CACHE.pop(cache_id, None)

        return send_file(
            pdf_stream,
            as_attachment=True,
            download_name=output_filename,
            mimetype='application/pdf'
        )

    except Exception as e:
        print(f"An error occurred during guide generation: {e}")
        return jsonify({'error': f'An internal server error occurred: {e}'}), 500

if __name__ == '__main__':
    app.run(debug=True)