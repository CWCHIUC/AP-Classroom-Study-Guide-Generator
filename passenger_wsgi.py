import os
import sys

# Add the project directory to the Python path
# This ensures that the server can find your 'app.py' and 'utils' folder
project_directory = os.path.dirname(__file__)
sys.path.insert(0, project_directory)

# Import your Flask app instance
from app import app as application