import os
from flask_sqlalchemy import SQLAlchemy

# Initialize SQLAlchemy without binding to an app
db = SQLAlchemy()

def init_db(app):
    """Initialize the database with the given Flask app"""
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    
    db.init_app(app)
    
    with app.app_context():
        import models  # Import models after db is initialized
        db.create_all()
