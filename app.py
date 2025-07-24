import os
from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from utils.data_analyzer import analyze_data
from utils.guide_generator import get_weak_topics, extract_text_from_pdf, create_study_guide_text, create_pdf_from_text
import pandas as pd

load_dotenv() # Load the .env file at the start

# Configuration
UPLOAD_FOLDER = 'uploads'
GENERATED_FOLDER = 'generated'
ALLOWED_EXTENSIONS = {'csv'}

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['GENERATED_FOLDER'] = GENERATED_FOLDER
app.secret_key = 'your_very_secret_key'

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GENERATED_FOLDER, exist_ok=True)

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
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            study_guides_df, predictions_df, plot_b64 = analyze_data(file_path)
          
            if study_guides_df is None and predictions_df is None and plot_b64 is None:
                flash('Upload failed. Make sure you are uploading the correct file.')
                return redirect(request.url)

            # --- MODIFICATION START: Add Student Names using External Student ID ---
            try:
                # Load the original CSV to map student IDs to names.
                # We use 'External Student ID' as the unique integer identifier.
                df_names = pd.read_csv(file_path)
                
                required_cols = ['External Student ID', 'First Name', 'Last Name']
                if all(col in df_names.columns for col in required_cols):
                    # Create the name map
                    name_map = df_names[required_cols].copy()
                    name_map.dropna(subset=['External Student ID', 'First Name', 'Last Name'], inplace=True)
                    name_map['Student Name'] = name_map['First Name'] + ' ' + name_map['Last Name']
                    
                    # Ensure the ID is an integer before setting it as the index
                    name_map['External Student ID'] = name_map['External Student ID'].astype(int)
                    name_map = name_map[['External Student ID', 'Student Name']].drop_duplicates().set_index('External Student ID')

                    # Add names to the predictions table
                    if predictions_df is not None and not predictions_df.empty:
                        # Merge on the index, which is the student ID
                        predictions_df = predictions_df.merge(name_map, how='left', left_index=True, right_index=True)
                        if 'Student Name' in predictions_df.columns:
                            cols = ['Student Name'] + [col for col in predictions_df.columns if col != 'Student Name']
                            predictions_df = predictions_df[cols]

                    # Add names to the study guides table
                    if study_guides_df is not None and not study_guides_df.empty:
                        # Also merge on the index here
                        study_guides_df = study_guides_df.merge(name_map, how='left', left_index=True, right_index=True)
                        if 'Student Name' in study_guides_df.columns:
                            # Reorder columns to place 'Student Name' first (after the index)
                            cols = ['Student Name'] + [col for col in study_guides_df.columns if col != 'Student Name']
                            study_guides_df = study_guides_df[cols]
                else:
                    flash("Could not find 'External Student ID', 'First Name', or 'Last Name' columns in the uploaded file.")
            except Exception as e:
                print(f"Error during name mapping: {e}")
                flash(f"An error occurred while adding student names: {e}")
            # --- MODIFICATION END ---

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
        return jsonify({'error': 'Server configuration error: API key is missing or invalid.'}), 500
  
    student_id = request.form.get('student_id')
    csv_filename = request.form.get('csv_filename')
    if 'ced_file' not in request.files:
        return jsonify({'error': 'No Course and Exam Description file provided.'}), 400
  
    ced_file = request.files['ced_file']
    if ced_file.filename == '' or not ced_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'Please upload a valid PDF file.'}), 400

    try:
        csv_path = os.path.join(app.config['UPLOAD_FOLDER'], csv_filename)
        # --- MODIFIED: Now captures the subject from the CSV ---
        weak_topics, subject = get_weak_topics(int(student_id), csv_path)
        
        if not weak_topics:
            return jsonify({'error': f'No topics requiring review found for student {student_id}.'}), 404

        ced_text = extract_text_from_pdf(ced_file.stream)
        if not ced_text:
            return jsonify({'error': 'Could not read content from the provided PDF.'}), 500

        # --- MODIFIED: Passes the dynamic subject to the guide generator ---
        guide_text = create_study_guide_text(weak_topics, ced_text, api_key, subject)

        output_filename = f"study_guide_{student_id}.pdf"
        output_path = os.path.join(app.config['GENERATED_FOLDER'], output_filename)
        create_pdf_from_text(guide_text, output_path)

        return jsonify({
            'success': True,
            'download_url': url_for('download_guide', filename=output_filename)
        })

    except Exception as e:
        print(f"An error occurred during guide generation: {e}")
        return jsonify({'error': f'An internal server error occurred: {e}'}), 500

@app.route('/download/<filename>')
def download_guide(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename, as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True)