import os
import logging
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS
from openai_assistant import OpenAIAssistant
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Flask
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET")

# Configure CORS for SSE and VAPI
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "supports_credentials": True
    }
})

def stream_openai_response(message, is_voice=False):
    """Stream OpenAI responses using server-sent events"""
    assistant = OpenAIAssistant()
    try:
        for response in assistant.stream_response(message, is_voice=is_voice):
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

@app.route('/v1/chat/completions', methods=['POST'])
def vapi_chat():
    """VAPI LLM endpoint for chat completions"""
    try:
        data = request.get_json()
        if not data or 'messages' not in data:
            return jsonify({"error": "Invalid request format"}), 400

        # Get the last user message
        last_message = next((msg['content'] for msg in reversed(data['messages']) 
                           if msg['role'] == 'user'), None)

        if not last_message:
            return jsonify({"error": "No user message found"}), 400

        # Process through our assistant
        assistant = OpenAIAssistant()
        full_response = ""

        # Collect the full response
        for response in assistant.stream_response(last_message, is_voice=True):
            if response.get("type") == "error":
                return jsonify({"error": response["content"]}), 500
            full_response += response.get("content", "")

        # Format response for VAPI
        return jsonify({
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": full_response.strip()
                }
            }]
        })

    except Exception as e:
        logger.error(f"Error in VAPI endpoint: {str(e)}")
        return jsonify({"error": str(e)}), 500

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

@app.route('/')
def index():
    """Render the chat interface"""
    return render_template('index.html')

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    logger.error("404 error: %s", error)
    return "Page not found", 404

@app.errorhandler(500)
def internal_error(error):
    logger.error("500 error: %s", error)
    return "Internal server error", 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)