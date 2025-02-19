import os
import logging
import time
from flask import Flask, render_template, request, jsonify, Response, current_app
from flask_cors import CORS
import json
from database import db, init_db
from session_evaluator import SessionEvaluator

# Update the logging configuration for better visibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add version identifier
SERVER_VERSION = "v2.0-2024-02-15"
logger.info(f"Starting interview server {SERVER_VERSION}")

# Global session management
class SessionManager:
    def __init__(self):
        self.current_session = os.urandom(16).hex()
        logger.info(f"Initialized SessionManager with session ID: {self.current_session}")

    def get_session(self):
        return self.current_session

    def increment_session(self):
        old_session = self.current_session
        self.current_session = os.urandom(16).hex()
        logger.info(f"Incremented session ID from {old_session} to {self.current_session}")
        return self.current_session

session_manager = SessionManager()

try:
    # Initialize Flask
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    app.secret_key = os.environ.get("SESSION_SECRET")

    # Configure CORS for all routes and origins
    CORS(app, resources={
        r"/*": {
            "origins": "*",
            "supports_credentials": True,
            "allow_headers": ["*"],
            "expose_headers": ["*"],
            "methods": ["GET", "POST", "OPTIONS"]
        }
    })

    # Initialize database with proper configuration
    init_db(app)
    logger.info("Database connection initialized")

    # Import models after db initialization to avoid circular imports
    from models import Conversation, Message, InterviewData, PersonModel

    # Create all tables within app context - only if they don't exist
    with app.app_context():
        db.create_all()
        logger.info("Database tables verified")

    # Import assistant after db and model initialization
    from openai_assistant import OpenAIAssistant

    logger.info("Flask application initialized successfully")
except Exception as e:
    logger.error(f"Error initializing Flask application: {str(e)}", exc_info=True)
    raise

# Add shutdown handler
def shutdown_handler(exception=None):
    if exception:
        logger.warning(f"Context teardown due to error: {str(exception)}")
    else:
        logger.debug("Request context cleanup initiated")
    try:
        # Cleanup database connections
        db.session.remove()
        logger.debug("Database connections cleaned up")
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}", exc_info=True)

# Register shutdown handler
app.teardown_appcontext(shutdown_handler)

@app.after_request
def after_request(response):
    """Modify response headers for better webview compatibility"""
    # Allow webview to properly render content
    host = request.headers.get('Host', '')
    logger.info(f"Setting security headers for request from {host}")

    # Set headers to allow embedding in Replit's webview
    response.headers['X-Frame-Options'] = 'ALLOW-FROM *'
    response.headers['Content-Security-Policy'] = "frame-ancestors * https://*.replit.dev https://*.replit.com"
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = '*'
    return response

# Add admin endpoint to control session
@app.route('/admin/session', methods=['POST'])
def admin_session():
    """Admin endpoint to control session ID"""
    action = request.args.get('action')

    if action == 'increment':
        new_session = session_manager.increment_session()
        return jsonify({
            "message": "Session ID incremented",
            "old_session": session_manager.current_session,
            "new_session": new_session
        })
    else:
        return jsonify({
            "message": "Current session ID",
            "session": session_manager.get_session()
        })

@app.before_request
def before_request():
    """Log incoming request details for debugging"""
    logger.info(f"Received request: {request.method} {request.path}")
    logger.info(f"Request headers: {dict(request.headers)}")
    return None

@app.route('/', methods=['GET'])
def index():
    """Render the chat interface"""
    try:
        logger.info("Serving index page")
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return "Error loading chat interface", 500

@app.route('/v1/chat/completions', methods=['POST'])
def vapi_chat():
    """VAPI LLM endpoint for chat completions"""
    try:
        data = request.get_json()
        logger.info(f"🚀 [{SERVER_VERSION}] Processing VAPI request from {request.remote_addr}")

        if not data or 'messages' not in data:
            logger.warning("Invalid VAPI request - missing messages field")
            return jsonify({
                "error": {
                    "message": "Invalid request format - 'messages' field is required",
                    "type": "invalid_request_error"
                }
            }), 400

        # Get the last user message as the current query
        last_message = next((msg['content'] for msg in reversed(data['messages'])
                            if msg['role'] == 'user'), None)

        if not last_message:
            logger.warning("No user message found in VAPI conversation")
            return jsonify({
                "error": {
                    "message": "No user message found in conversation",
                    "type": "invalid_request_error"
                }
            }), 400

        # Use managed session ID
        session_id = session_manager.get_session()
        logger.info(f"🔹 Using managed session ID: {session_id}")

        def generate():
            # Create a new application context for the generator
            ctx = app.app_context()
            ctx.push()
            try:
                assistant = OpenAIAssistant()
                logger.info(f"Processing VAPI request through assistant with session {session_id}")

                # Process through the assistant with session tracking
                try:
                    # First stream all responses
                    for response in assistant.stream_response(last_message, session_id=session_id):
                        content = response if isinstance(response, str) else response.get("content", "")
                        chunk_data = {
                            "id": f"chatcmpl-{os.urandom(12).hex()}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": "custom-assistant",
                            "session_id": session_id,
                            "choices": [{
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "content": content
                                },
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(chunk_data)}\n\n"

                    # Send completion message
                    completion_data = {
                        "id": f"chatcmpl-{os.urandom(12).hex()}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "custom-assistant",
                        "session_id": session_id,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop"
                        }]
                    }
                    logger.info(f"VAPI response completed for session {session_id}")
                    yield f"data: {json.dumps(completion_data)}\n\n"

                    # Schedule evaluation to run after stream is closed, but only if appropriate
                    def run_evaluation():
                        with app.app_context():
                            try:
                                assistant = OpenAIAssistant()
                                conversation = Conversation.query.filter_by(session_id=session_id).first()
                                if conversation and assistant._can_run_evaluation(session_id, conversation.id):
                                    logger.info(f"Running evaluation for completed session {session_id}")
                                    evaluator = SessionEvaluator()
                                    result = evaluator.analyze_conversation(session_id)
                                    if result['success']:
                                        logger.info(f"Successfully evaluated session {session_id}")
                                    else:
                                        logger.error(f"Failed to evaluate session {session_id}: {result.get('error')}")
                                else:
                                    logger.debug(f"Skipping evaluation for session {session_id} - conditions not met")
                            except Exception as e:
                                logger.error(f"Error during evaluation: {str(e)}", exc_info=True)

                    # Use gevent to run evaluation after response with proper context
                    from gevent import spawn_later
                    # Delay evaluation by 5 seconds to prioritize voice interaction
                    spawn_later(5, run_evaluation)

                except Exception as e:
                    logger.error(f"Error in response streaming: {str(e)}", exc_info=True)
                    error_data = {
                        "error": {
                            "message": str(e),
                            "type": "streaming_error"
                        },
                        "session_id": session_id
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"
                    error_completion = {
                        "id": f"chatcmpl-{os.urandom(12).hex()}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "custom-assistant",
                        "session_id": session_id,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "error"
                        }]
                    }
                    yield f"data: {json.dumps(error_completion)}\n\n"

            except Exception as e:
                logger.error(f"Fatal error in VAPI generator: {str(e)}", exc_info=True)
                error_data = json.dumps({
                    "error": {
                        "message": str(e),
                        "type": "fatal_error"
                    },
                    "session_id": session_id
                })
                yield f"data: {error_data}\n\n"
            finally:
                ctx.pop()

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
                'X-Session-ID': session_id
            }
        )

    except Exception as e:
        logger.error(f"Error in VAPI endpoint: {str(e)}", exc_info=True)
        current_session = session_manager.get_session()
        return jsonify({
            "error": {
                "message": str(e),
                "type": "api_error"
            },
            "session_id": current_session
        }), 500

@app.route('/stream', methods=['POST'])
def stream():
    """SSE endpoint for streaming responses"""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()
    message = data.get('message')

    if not message:
        return jsonify({"error": "Message field is required"}), 400

    # Use the global session manager
    session_id = session_manager.get_session()
    logger.info(f"Using managed session ID for stream: {session_id}")

    return Response(
        stream_openai_response(message, session_id),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'X-Session-ID': session_id
        }
    )

def stream_openai_response(message, session_id=None):
    """Stream OpenAI responses using server-sent events"""
    try:
        # Initialize OpenAI Assistant within app context
        with app.app_context():
            assistant = OpenAIAssistant()
            logger.info(f"Processing message with session ID: {session_id}")

            # Stream responses with proper context management
            for response in assistant.stream_response(message, session_id=session_id):
                # Ensure response is treated as plain text
                if isinstance(response, str):
                    data = {
                        "type": "text",
                        "chunk": response,
                        "done": False,
                        "session_id": session_id
                    }
                else:
                    # Handle potential dictionary responses
                    data = {
                        "type": response.get("type", "text"),
                        "chunk": response.get("content", ""),
                        "done": False,
                        "session_id": session_id
                    }

                yield f"data: {json.dumps(data)}\n\n"

            # Send completion message
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'session_id': session_id})}\n\n"

    except Exception as e:
        logger.error(f"Error in stream_openai_response: {str(e)}", exc_info=True)
        error_data = json.dumps({"error": str(e), "session_id": session_id})
        yield f"data: {error_data}\n\n"

@app.route('/conversations', methods=['GET'])
def view_conversations():
    """View all conversations and their messages"""
    try:
        conversations = Conversation.query.order_by(Conversation.created_at.desc()).all()
        conversations_data = []

        for conv in conversations:
            messages = Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at).all()
            messages_data = [{
                'role': msg.role,
                'content': msg.content,
                'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
            } for msg in messages]

            conversations_data.append({
                'id': conv.id,
                'session_id': conv.session_id or 'No Session ID',
                'created_at': conv.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'message_count': len(messages_data),
                'first_pass_completed': conv.first_pass_completed,
                'messages': messages_data
            })

        return render_template('conversations.html', conversations=conversations_data)
    except Exception as e:
        logger.error(f"Error viewing conversations: {str(e)}")
        return str(e), 500

@app.route('/api/mark-pass-complete/<session_id>', methods=['POST'])
def mark_pass_complete(session_id):
    """Mark the first interview pass as complete"""
    try:
        conversation = Conversation.query.filter_by(session_id=session_id).first()
        if not conversation:
            return jsonify({
                "status": "error",
                "message": "Conversation not found"
            }), 404

        conversation.first_pass_completed = True
        db.session.commit()

        return jsonify({
            "status": "success",
            "message": "Interview pass 1 marked as complete"
        })

    except Exception as e:
        logger.error(f"Error marking pass complete: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/start-second-pass/<session_id>', methods=['POST'])
def start_second_pass(session_id):
    """Initialize second interview pass"""
    try:
        conversation = Conversation.query.filter_by(session_id=session_id).first()
        if not conversation:
            return jsonify({
                "status": "error",
                "message": "Conversation not found"
            }), 404

        if not conversation.first_pass_completed:
            return jsonify({
                "status": "error",
                "message": "First pass must be completed before starting second pass"
            }), 400

        person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
        if not person_model or not person_model.follow_up_questions:
            return jsonify({
                "status": "error",
                "message": "No follow-up questions available. Please run evaluation first."
            }), 400

        conversation.current_pass = 2
        db.session.commit()

        # Update the current session to the selected conversation
        session_manager.current_session = session_id

        return jsonify({
            "status": "success",
            "message": "Second pass initialized",
            "session_id": session_id
        })

    except Exception as e:
        logger.error(f"Error starting second pass: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/evaluation-results/<session_id>')
def view_evaluation_results(session_id):
    """View evaluation results for a specific session"""
    try:
        # Find conversation by session_id
        conversation = Conversation.query.filter_by(session_id=session_id).first()
        if not conversation:
            return "Session not found", 404

        # Get the person model data
        person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
        if not person_model:
            return "No evaluation data found for this session", 404

        return render_template('evaluation_results.html',
                             session_id=session_id,
                             evaluation_time=person_model.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                             person_model=person_model.data_model,
                             missing_topics=person_model.missing_topics,
                             follow_up_questions=person_model.follow_up_questions,
                             debug_info=person_model.debug_info or {})

    except Exception as e:
        logger.error(f"Error viewing evaluation results: {str(e)}")
        return str(e), 500

@app.errorhandler(404)
def not_found_error(error):
    logger.error("404 error: %s", error)
    return "Page not found", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error("500 error: %s", error)
    return "Internal server error", 500

if __name__ == '__main__':
    # Let main.py handle the server start
    pass