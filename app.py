import os
import logging
import time
from flask import Flask, render_template, request, jsonify, Response, current_app
from flask_cors import CORS
import json
from database import db

# Update the logging configuration for better visibility
logging.basicConfig(
    level=logging.INFO,  # Change from DEBUG to INFO to reduce noise
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add version identifier
SERVER_VERSION = "v2.0-2024-02-15"
logger.info(f"Starting interview server {SERVER_VERSION}")

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

    # Configure SQLAlchemy
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize database first
    db.init_app(app)

    # Import models after db initialization
    from models import Conversation, Message, InterviewData

    # Create all tables within app context
    with app.app_context():
        logger.info("Creating database tables...")
        db.create_all()
        logger.info("Database tables created successfully")

    # Import assistant after db and model initialization
    from openai_assistant import OpenAIAssistant

    logger.info("Flask application initialized successfully")
except Exception as e:
    logger.error(f"Error initializing Flask application: {str(e)}", exc_info=True)
    raise

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

        # Extract session ID from request headers - now optional
        session_id = request.headers.get('X-Session-ID')
        if not session_id:
            logger.info("No session ID provided in VAPI request, creating a new conversation")
        else:
            logger.info(f"Using provided session ID: {session_id}")

        def generate():
            # Create a new application context for the generator
            ctx = app.app_context()
            ctx.push()
            try:
                assistant = OpenAIAssistant()
                logger.info(f"Processing VAPI request through assistant")

                # Process through the assistant with optional session tracking
                for response in assistant.stream_response(last_message, session_id=session_id):
                    # Handle string responses
                    content = response if isinstance(response, str) else response.get("content", "")

                    chunk_data = {
                        "id": f"chatcmpl-{os.urandom(12).hex()}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": "custom-assistant",
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

                # Send the completion message
                completion_data = {
                    "id": f"chatcmpl-{os.urandom(12).hex()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "custom-assistant",
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop"
                    }]
                }
                logger.info("VAPI response completed successfully")
                yield f"data: {json.dumps(completion_data)}\n\n"

            except Exception as e:
                logger.error(f"Streaming error in VAPI request: {str(e)}", exc_info=True)
                error_response = json.dumps({
                    "error": {
                        "message": str(e),
                        "type": "api_error"
                    }
                })
                yield f"data: {error_response}\n\n"
            finally:
                # Make sure to pop the context when done
                ctx.pop()

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        logger.error(f"Error in VAPI endpoint: {str(e)}", exc_info=True)
        return jsonify({
            "error": {
                "message": str(e),
                "type": "api_error"
            }
        }), 500

@app.route('/stream', methods=['POST'])
def stream():
    """SSE endpoint for streaming responses"""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()
    message = data.get('message')
    session_id = data.get('session_id')  # Optional session ID for conversation continuity

    if not message:
        return jsonify({"error": "Message field is required"}), 400

    return Response(
        stream_openai_response(message, session_id),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

def stream_openai_response(message, session_id=None):
    """Stream OpenAI responses using server-sent events"""
    try:
        # Initialize OpenAI Assistant within app context
        with app.app_context():
            assistant = OpenAIAssistant()

            # Stream responses with proper context management
            for response in assistant.stream_response(message, session_id=session_id):
                # Ensure response is treated as plain text
                if isinstance(response, str):
                    data = {
                        "type": "text",
                        "chunk": response,
                        "done": False
                    }
                else:
                    # Handle potential dictionary responses
                    data = {
                        "type": response.get("type", "text"),
                        "chunk": response.get("content", ""),
                        "done": False
                    }

                yield f"data: {json.dumps(data)}\n\n"

            # Send completion message
            yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"

    except Exception as e:
        logger.error(f"Error in stream_openai_response: {str(e)}", exc_info=True)
        error_data = json.dumps({"error": str(e)})
        yield f"data: {error_data}\n\n"

@app.route('/conversations', methods=['GET'])
def view_conversations():
    """View all conversations and their messages"""
    try:
        conversations = Conversation.query.all()
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
                'session_id': conv.session_id,
                'created_at': conv.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'messages': messages_data
            })
            
        return render_template('conversations.html', conversations=conversations_data)
    except Exception as e:
        logger.error(f"Error viewing conversations: {str(e)}")
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