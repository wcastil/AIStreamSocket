import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

class OpenAIAssistant:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        # Store the assistant ID from your custom assistant
        self.assistant_id = os.environ.get("OPENAI_ASSISTANT_ID")

        if not self.assistant_id:
            raise ValueError("OPENAI_ASSISTANT_ID environment variable is required")

    def stream_response(self, user_message, is_voice=False):
        """Stream responses from the OpenAI Assistant API."""
        try:
            # Create a new thread
            thread = self.client.beta.threads.create()

            # Add the user message to the thread with voice indicator
            message_params = {
                "thread_id": thread.id,
                "role": "user",
                "content": user_message,
            }

            # Add metadata for voice processing if needed
            if is_voice:
                message_params["metadata"] = {"type": "voice_input"}

            self.client.beta.threads.messages.create(**message_params)

            # Run the assistant
            run = self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=self.assistant_id,
                metadata={"output_type": "voice" if is_voice else "text"}
            )

            # Wait for the completion and stream the response
            while True:
                run_status = self.client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id
                )

                if run_status.status == 'completed':
                    # Get the messages
                    messages = self.client.beta.threads.messages.list(
                        thread_id=thread.id
                    )

                    # Get the latest assistant message
                    for msg in messages.data:
                        if msg.role == "assistant":
                            content = msg.content[0].text.value
                            # Stream the message content word by word for voice synthesis preparation
                            words = content.split()
                            for word in words:
                                response_data = {
                                    "type": "voice" if is_voice else "text",
                                    "content": word + " "
                                }
                                yield response_data
                            break
                    break

                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    error_message = f"Assistant run failed with status: {run_status.status}"
                    logger.error(error_message)
                    yield {"type": "error", "content": error_message}
                    break

        except Exception as e:
            error_message = f"Error in OpenAI Assistant: {str(e)}"
            logger.error(error_message)
            yield {"type": "error", "content": error_message}