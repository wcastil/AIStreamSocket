import os
import logging
import json
from openai import OpenAI
from models import InterviewData, Message
from database import db
import time

logger = logging.getLogger(__name__)

class OpenAIAssistant:
    def __init__(self):
        try:
            self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            self.assistant_id = os.environ.get("OPENAI_ASSISTANT_ID")

            if not self.assistant_id:
                raise ValueError("OPENAI_ASSISTANT_ID environment variable is required")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {str(e)}", exc_info=True)
            raise

    def _extract_interview_data(self, user_input, current_data):
        """Extract structured interview data from user input"""
        try:
            # Define the data extraction functions available to the assistant
            tools = [{
                "type": "function",
                "function": {
                    "name": "update_interview_data",
                    "description": "Update the interview data model with extracted information",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "field_category": {
                                "type": "string",
                                "enum": [
                                    "core_values_and_priorities",
                                    "personality_and_emotional_profile",
                                    "decision_making_framework",
                                    "behavioral_patterns",
                                    "relationships_and_interactions",
                                    "growth_and_learning",
                                    "creativity_and_divergence"
                                ]
                            },
                            "field_name": {"type": "string"},
                            "value": {"type": "string"},
                            "missing_fields": {
                                "type": "array",
                                "items": {"type": "string"}
                            }
                        },
                        "required": ["field_category", "field_name", "value"]
                    }
                }
            }]

            messages = [
                {
                    "role": "system",
                    "content": """You are an expert at extracting structured interview data. 
                    Analyze user responses and extract relevant information for our data model.
                    If you identify information that fits into our model, call the update_interview_data function."""
                },
                {"role": "user", "content": user_input}
            ]

            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )

            return response.choices[0].message

        except Exception as e:
            logger.error(f"Error in extracting interview data: {e}")
            return None

    def stream_response(self, user_message, thread_id=None, interview_data=None):
        """Stream responses from the OpenAI Assistant API with data extraction"""
        try:
            # Create a new thread if none provided
            try:
                thread = self.client.beta.threads.create() if not thread_id else None
                thread_id = thread.id if thread else thread_id
                logger.info(f"Processing message in thread {thread_id}")
            except Exception as e:
                logger.error(f"Error creating thread: {str(e)}", exc_info=True)
                yield f"Error creating conversation thread: {str(e)}"
                return

            # Add the user message to the thread
            try:
                self.client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=user_message
                )
            except Exception as e:
                logger.error(f"Error adding message to thread: {str(e)}", exc_info=True)
                yield f"Error adding message to conversation: {str(e)}"
                return

            # First, extract structured data from the user's message
            if interview_data:
                extraction_result = self._extract_interview_data(user_message, interview_data)
                logger.info("Extraction result received")

                if extraction_result and hasattr(extraction_result, 'tool_calls'):
                    logger.info(f"Found {len(extraction_result.tool_calls)} tool calls")
                    # Process the extracted data
                    for tool_call in extraction_result.tool_calls:
                        if tool_call.function.name == "update_interview_data":
                            extracted_data = json.loads(tool_call.function.arguments)
                            logger.info(f"Function call detected: update_interview_data")
                            logger.info(f"Arguments: {json.dumps(extracted_data, indent=2)}")

                            # Update the interview data model
                            for field_name, value in extracted_data.items():
                                if hasattr(interview_data, field_name):
                                    setattr(interview_data, field_name, value)
                                    logger.info(f"Updated field {field_name} with value: {value}")

                            if "missing_fields" in extracted_data:
                                interview_data.missing_fields = extracted_data["missing_fields"]
                                logger.info(f"Missing fields updated: {extracted_data['missing_fields']}")

                            db.session.commit()
                            logger.info("Database updated successfully")

            # Run the assistant
            try:
                logger.info("Starting assistant run")
                run = self.client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=self.assistant_id
                )
            except Exception as e:
                logger.error(f"Error starting assistant run: {str(e)}", exc_info=True)
                yield f"Error starting conversation: {str(e)}"
                return

            # Poll for response and stream it
            max_retries = 3
            retry_count = 0

            while True:
                try:
                    run_status = self.client.beta.threads.runs.retrieve(
                        thread_id=thread_id,
                        run_id=run.id
                    )

                    logger.info(f"Run status: {run_status.status}")

                    if run_status.status == 'completed':
                        messages = self.client.beta.threads.messages.list(
                            thread_id=thread_id
                        )

                        for msg in messages.data:
                            if msg.role == "assistant":
                                try:
                                    content = msg.content[0].text.value if hasattr(msg.content[0], 'text') else str(msg.content[0])
                                    logger.info(f"Assistant response: {content[:50]}...")
                                    yield content
                                except Exception as e:
                                    error_msg = f"Error processing message: {str(e)}"
                                    logger.error(error_msg, exc_info=True)
                                    yield error_msg
                                break
                        break

                    elif run_status.status in ['failed', 'cancelled', 'expired']:
                        error_msg = f"Assistant run failed with status: {run_status.status}"
                        logger.error(error_msg)
                        yield error_msg
                        break

                    time.sleep(0.5)  # Add a small delay between status checks

                except Exception as e:
                    logger.error(f"Error checking run status: {str(e)}", exc_info=True)
                    retry_count += 1

                    if retry_count >= max_retries:
                        error_msg = f"Max retries reached, failed to get response: {str(e)}"
                        logger.error(error_msg)
                        yield error_msg
                        break

                    time.sleep(1)  # Wait before retrying

        except Exception as e:
            error_msg = f"Error in OpenAI Assistant: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield error_msg