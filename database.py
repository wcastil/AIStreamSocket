import os
from flask_sqlalchemy import SQLAlchemy
import logging

logger = logging.getLogger(__name__)

# Initialize SQLAlchemy without binding to an app
db = SQLAlchemy()

def init_db(app):
    """Initialize the database with the given Flask app"""
    try:
        app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_recycle": 300,
            "pool_pre_ping": True,
        }

        logger.info("Initializing database connection...")
        db.init_app(app)

        with app.app_context():
            # Import models here to avoid circular imports
            from models import Conversation, Message, InterviewData, PersonModel

            logger.info("Creating database tables...")
            db.create_all()
            logger.info("Database initialization completed successfully")

    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}", exc_info=True)
        raise