"""Thread management utilities for OpenAI conversation threads."""
import logging
from datetime import datetime, timedelta
from app import db
from models import SessionThread

logger = logging.getLogger(__name__)

class ThreadManager:
    """Manages OpenAI conversation threads."""
    
    @staticmethod
    def get_or_create_thread(session_id):
        """Get an existing thread or create a new one for the session."""
        try:
            # Check for existing active thread
            thread = SessionThread.query.filter_by(
                session_id=session_id,
                is_active=True
            ).first()
            
            if thread:
                # Update last activity
                thread.touch()
                db.session.commit()
                logger.info(f"Retrieved existing thread for session {session_id}")
                return thread.thread_id
            
            # Create new thread
            from openai import OpenAI
            client = OpenAI()
            response = client.beta.threads.create()
            thread_id = response.id
            
            # Store new thread
            thread = SessionThread(
                session_id=session_id,
                thread_id=thread_id
            )
            db.session.add(thread)
            db.session.commit()
            
            logger.info(f"Created new thread for session {session_id}")
            return thread_id
            
        except Exception as e:
            logger.error(f"Error managing thread for session {session_id}: {str(e)}")
            db.session.rollback()
            raise
    
    @staticmethod
    def cleanup_inactive_threads(max_age_hours=24):
        """Clean up threads that have been inactive for the specified period."""
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
            
            # Find inactive threads
            inactive_threads = SessionThread.query.filter(
                SessionThread.last_activity < cutoff_time,
                SessionThread.is_active == True
            ).all()
            
            # Mark threads as inactive
            for thread in inactive_threads:
                thread.is_active = False
                logger.info(f"Marking thread {thread.thread_id} as inactive due to age")
            
            db.session.commit()
            return len(inactive_threads)
            
        except Exception as e:
            logger.error(f"Error cleaning up inactive threads: {str(e)}")
            db.session.rollback()
            raise
    
    @staticmethod
    def get_thread_info(session_id):
        """Get information about a session's thread."""
        thread = SessionThread.query.filter_by(session_id=session_id).first()
        if not thread:
            return None
            
        return {
            'thread_id': thread.thread_id,
            'created_at': thread.created_at,
            'last_activity': thread.last_activity,
            'is_active': thread.is_active
        }
