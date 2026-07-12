import os
import sys

# Make the `app` package importable when running pytest from backend/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
