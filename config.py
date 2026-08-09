import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'handshake-secret-key-2026')
    
    # ============================================================
    # HANDSHAKE MANAGER - NEW PROJECT
    # ============================================================
    # REPLACE with your actual values from Supabase
    HS_SUPABASE_URL = os.environ.get('HS_SUPABASE_URL', 'https://YOUR_PROJECT_ID.supabase.co')
    HS_SUPABASE_KEY = os.environ.get('HS_SUPABASE_KEY', 'your-anon-key-here')
    HS_SUPABASE_SERVICE_KEY = os.environ.get('HS_SUPABASE_SERVICE_KEY', 'your-service-key-here')
    
    # App Settings
    APP_NAME = 'Handshake Manager'
    APP_VERSION = '1.0.0'
    
    # Upload Settings
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}
    
    # Pagination
    PER_PAGE = 20
    
    # Default Settings
    DEFAULT_COMMISSION_PERCENT = 25
    DEFAULT_EXCHANGE_RATE = 150