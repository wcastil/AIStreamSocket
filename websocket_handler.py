import json
import logging
from database import db
from models import Conversation, Message
from openai_assistant import OpenAIAssistant

logger = logging.getLogger(__name__)

def handle_websocket(ws):
    """Handle WebSocket connections and messages."""
    logger.info("New WebSocket connection established")
    assistant = OpenAIAssistant()

    # Create a new conversation for this WebSocket connection
    conversation = Conversation()
    db.session.add(conversation)
    db.session.commit()

    try:
        while not ws.closed:
            message = ws.receive()

            if message is None:
                continue

            try:
                data = json.loads(message)
                user_message = data.get('message')

                if not user_message:
                    ws.send(json.dumps({
                        "error": "Message field is required"
                    }))
                    continue

                # Store user message in database
                db_message = Message(
                    conversation_id=conversation.id,
                    role='user',
                    content=user_message
                )
                db.session.add(db_message)
                db.session.commit()

                # Stream the response from OpenAI
                full_response = ""
                for response_chunk in assistant.stream_response(user_message):
                    if ws.closed:
                        break
                    full_response += response_chunk
                    ws.send(json.dumps({
                        "chunk": response_chunk,
                        "done": False
                    }))

                if not ws.closed and full_response:
                    # Store assistant's response in database
                    assistant_message = Message(
                        conversation_id=conversation.id,
                        role='assistant',
                        content=full_response.strip()
                    )
                    db.session.add(assistant_message)
                    db.session.commit()

                    # Send completion message
                    ws.send(json.dumps({
                        "chunk": "",
                        "done": True
                    }))

            except json.JSONDecodeError:
                ws.send(json.dumps({
                    "error": "Invalid JSON message"
                }))
            except Exception as e:
                logger.error(f"Error processing message: {str(e)}")
                ws.send(json.dumps({
                    "error": f"Error processing message: {str(e)}"
                }))

    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
    finally:
        logger.info("WebSocket connection closed")