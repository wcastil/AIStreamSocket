import os
import logging
import json
from openai import OpenAI
from models import InterviewData, Message
from database import db

logger = logging.getLogger(__name__)

class OpenAIAssistant:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.assistant_id = os.environ.get("OPENAI_ASSISTANT_ID")

        if not self.assistant_id:
            raise ValueError("OPENAI_ASSISTANT_ID environment variable is required")

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
            thread = self.client.beta.threads.create() if not thread_id else None
            thread_id = thread.id if thread else thread_id

            logger.info(f"Processing message in thread {thread_id}")

            # Add the user message to the thread
            self.client.beta.threads.messages.create(
                thread_id=thread_id,
                role="user",
                content=user_message
            )
            logger.info(f"Added user message: {user_message[:50]}...")

            # First, extract structured data from the user's message
            if interview_data:
                extraction_result = self._extract_interview_data(user_message, interview_data)
                logger.info("Extraction result received")

                if extraction_result and extraction_result.tool_calls:
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
            logger.info("Starting assistant run")
            run = self.client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=self.assistant_id
            )

            # Poll for response and stream it
            while True:
                run_status = self.client.beta.threads.runs.retrieve(
                    thread_id=thread_id,
                    run_id=run.id
                )

                logger.info(f"Run status: {run_status.status}")

                if run_status.status == 'completed':
                    # Get the messages
                    messages = self.client.beta.threads.messages.list(
                        thread_id=thread_id
                    )

                    # Get the latest assistant message
                    for msg in messages.data:
                        if msg.role == "assistant":
                            content = msg.content[0].text.value
                            logger.info(f"Assistant response: {content[:50]}...")
                            # Stream the message content word by word
                            words = content.split()
                            for word in words:
                                yield word + " "
                            break
                    break

                elif run_status.status in ['failed', 'cancelled', 'expired']:
                    error_message = f"Assistant run failed with status: {run_status.status}"
                    logger.error(error_message)
                    yield error_message
                    break

        except Exception as e:
            error_message = f"Error in OpenAI Assistant: {str(e)}"
            logger.error(error_message)
            yield error_message