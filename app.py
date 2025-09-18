# app.py

import os
import json
from pathlib import Path
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, send_file, session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from utils.data_analyzer import analyze_data
from utils.guide_generator import get_weak_topics_and_subject, extract_text_from_pdf, create_study_guide_text, create_pdf_from_text
import pandas as pd
import io
import uuid
import threading  # <-- Import for background tasks

load_dotenv()

ALLOWED_EXTENSIONS = {'csv'}

app = Flask(__name__)
app.secret_key = 'your_very_secret_key'  # Make sure this is set!

# Define temporary directory for file-based persistence (based on your log path; adjust if needed)
TEMP_DIR = Path('/home/hasskigm/tmp_jobs')
TEMP_DIR.mkdir(exist_ok=True, parents=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_pdf_in_background(job_id, student_id, csv_data_bytes, ced_file_bytes, api_key):
    """
    This function runs in a separate thread, handling all data with file-based persistence.
    """
    status_file = TEMP_DIR / f"{job_id}.json"
    pdf_file = TEMP_DIR / f"study_guide_{student_id}_{job_id[:8]}.pdf"

    # Helper to update status with flush for immediate write
    def update_status(status_dict):
        with open(status_file, 'w') as f:
            json.dump(status_dict, f)
            f.flush()  # Ensure data is written immediately

    try:
        update_status({'status': 'processing', 'message': 'Analyzing student data...'})

        csv_stream = io.BytesIO(csv_data_bytes)
        weak_topics, subject = get_weak_topics_and_subject(int(student_id), csv_stream)

        if not weak_topics:
            raise ValueError(f'No topics requiring review found for student {student_id}.')

        update_status({'status': 'processing', 'message': 'Extracting text from course description...'})
        ced_stream = io.BytesIO(ced_file_bytes)
        ced_text = extract_text_from_pdf(ced_stream)

        if not ced_text:
            raise ValueError('Could not read content from the provided PDF.')

        update_status({'status': 'processing', 'message': 'Generating study guide content (this may take a moment)...'})
        guide_text = create_study_guide_text(weak_topics, ced_text, api_key, subject)

        update_status({'status': 'processing', 'message': 'Creating PDF document...'})
        pdf_bytes = create_pdf_from_text(guide_text)

        # Save PDF to file
        with open(pdf_file, 'wb') as f:
            f.write(pdf_bytes)

        # Signal completion
        update_status({'status': 'complete', 'filename': pdf_file.name})

    except Exception as e:
        print(f"Error in job {job_id}: {e}")
        update_status({'status': 'error', 'message': str(e)})

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

            # Save CSV to file for persistence
            cache_id = str(uuid.uuid4())
            cache_file = TEMP_DIR / f"{cache_id}.csv"
            with open(cache_file, 'wb') as f:
                f.write(csv_data_bytes)
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
    """
    This route now starts the background job and immediately returns a job ID.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not api_key.strip():
        return jsonify({'error': 'Server configuration error: API key is missing.'}), 500

    cache_id = session.get('csv_cache_id')
    cache_file = TEMP_DIR / f"{cache_id}.csv"
    if not cache_file.exists():
        return jsonify({'error': 'Session expired or data not found. Please upload the CSV again.'}), 400

    with open(cache_file, 'rb') as f:
        csv_data_bytes = f.read()

    student_id = request.form.get('student_id')

    if 'ced_file' not in request.files:
        return jsonify({'error': 'No Course and Exam Description file provided.'}), 400

    ced_file = request.files['ced_file']
    if ced_file.filename == '' or not ced_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a valid PDF file.'}), 400

    try:
        job_id = str(uuid.uuid4())

        # Read the uploaded file into memory
        ced_file_bytes = ced_file.read()

        # Set initial status file with flush
        status_file = TEMP_DIR / f"{job_id}.json"
        with open(status_file, 'w') as f:
            json.dump({'status': 'pending'}, f)
            f.flush()  # Ensure initial write is immediate

        # Create and start the background thread, passing the bytes
        thread = threading.Thread(
            target=generate_pdf_in_background,
            args=(job_id, student_id, csv_data_bytes, ced_file_bytes, api_key)
        )
        thread.start()

        # Immediately return the job_id to the client
        return jsonify({'status': 'processing', 'job_id': job_id})

    except Exception as e:
        print(f"Error starting job: {e}")
        return jsonify({'error': f'An internal server error occurred: {e}'}), 500

@app.route('/status/<job_id>')
def job_status(job_id):
    """
    Route for the frontend to poll for the job's status. Handles empty/invalid JSON gracefully.
    """
    status_file = TEMP_DIR / f"{job_id}.json"
    if not status_file.exists():
        return jsonify({'status': 'not_found'}), 404

    try:
        with open(status_file, 'r') as f:
            content = f.read().strip()  # Read and strip whitespace
            if not content:
                # If empty, treat as pending (race condition)
                return jsonify({'status': 'pending'})
            status_info = json.loads(content)
        if status_info.get('status') == 'complete':
            return jsonify({'status': 'complete'})
        return jsonify(status_info)
    except json.JSONDecodeError as e:
        # Log the error and return a safe response
        print(f"JSON decode error for job {job_id}: {e}")
        return jsonify({'status': 'pending', 'message': 'Status file is being updated...'})
    except Exception as e:
        print(f"Error reading status for job {job_id}: {e}")
        return jsonify({'status': 'error', 'message': 'Unable to read status.'}), 500

@app.route('/download/<job_id>')
def download_guide(job_id):
    """
    Sends the generated file from disk and then cleans up.
    """
    status_file = TEMP_DIR / f"{job_id}.json"
    if status_file.exists():
        with open(status_file, 'r') as f:
            job = json.load(f)
        if job.get('status') == 'complete':
            pdf_path = TEMP_DIR / job.get('filename')
            if pdf_path.exists():
                response = send_file(
                    pdf_path,
                    mimetype='application/pdf',
                    as_attachment=True,
                    download_name=job['filename']
                )
                # Cleanup files after response is sent
                def cleanup():
                    try:
                        status_file.unlink(missing_ok=True)
                        pdf_path.unlink(missing_ok=True)
                    except Exception as e:
                        print(f"Cleanup error for job {job_id}: {e}")
                response.call_on_close(cleanup)
                return response
    return jsonify({'status': 'error', 'message': 'Download not found or has expired.'}), 404

if __name__ == '__main__':
    app.run(debug=True)