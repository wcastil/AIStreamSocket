import os
import logging
import time
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from openai_assistant import OpenAIAssistant
import json

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key")

# Configure CORS for all routes
CORS(app)

@app.route('/', methods=['GET'])
def index():
    """Render the chat interface"""
    logger.info("Serving index page")
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error serving index page: {e}")
        return "Error loading chat interface", 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    logger.info("Health check request received")
    try:
        return jsonify({
            "status": "healthy",
            "timestamp": time.time(),
            "env": {
                "port": os.environ.get('PORT'),
                "host": request.host
            }
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

def stream_openai_response(message, is_voice=False):
    """Stream OpenAI responses using server-sent events"""
    assistant = OpenAIAssistant()
    try:
        for response in assistant.stream_response(message):
            data = json.dumps({
                "type": response.get("type", "text"),
                "chunk": response.get("content", ""),
                "done": False
            })
            yield f"data: {data}\n\n"

        # Send completion message
        yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
    except Exception as e:
        error_data = json.dumps({"error": str(e)})
        yield f"data: {error_data}\n\n"

@app.route('/stream', methods=['POST'])
def stream():
    """SSE endpoint for streaming responses"""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 400

    data = request.get_json()
    message = data.get('message')
    is_voice = data.get('is_voice', False)

    if not message:
        return jsonify({"error": "Message field is required"}), 400

    return Response(
        stream_openai_response(message, is_voice=is_voice),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/v1/chat/completions', methods=['POST'])
def vapi_chat():
    """VAPI LLM endpoint for chat completions"""
    try:
        data = request.get_json()
        if not data or 'messages' not in data:
            return jsonify({
                "error": {
                    "message": "Invalid request format - 'messages' field is required",
                    "type": "invalid_request_error"
                }
            }), 400

        # Process through our assistant
        assistant = OpenAIAssistant()

        def generate():
            try:
                # Get the last user message as the current query
                last_message = next((msg['content'] for msg in reversed(data['messages']) 
                                   if msg['role'] == 'user'), None)

                if not last_message:
                    error_response = json.dumps({
                        "error": {
                            "message": "No user message found in conversation",
                            "type": "invalid_request_error"
                        }
                    })
                    yield f"data: {error_response}\n\n"
                    return

                # Process through the assistant
                for response in assistant.stream_response(last_message):
                    if response.get("type") == "error":
                        error_response = json.dumps({
                            "error": {
                                "message": response["content"],
                                "type": "api_error"
                            }
                        })
                        yield f"data: {error_response}\n\n"
                        return

                    content = response.get("content", "")
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
                yield f"data: {json.dumps(completion_data)}\n\n"

            except Exception as e:
                logger.error(f"Streaming error: {str(e)}")
                error_response = json.dumps({
                    "error": {
                        "message": str(e),
                        "type": "api_error"
                    }
                })
                yield f"data: {error_response}\n\n"

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
        logger.error(f"Error in VAPI endpoint: {str(e)}")
        return jsonify({
            "error": {
                "message": str(e),
                "type": "api_error"
            }
        }), 500

@app.errorhandler(404)
def not_found_error(error):
    logger.error("404 error: %s", error)
    return "Page not found", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error("500 error: %s", error)
    return "Internal server error", 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)