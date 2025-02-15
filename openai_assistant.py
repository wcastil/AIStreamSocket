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

    def _extract_interview_data(self, user_input, interview_data):
        """Extract structured interview data from user input and generate next question"""
        try:
            tools = [{
                "type": "function",
                "function": {
                    "name": "update_interview_data_model",
                    "description": "Update the interview data model with extracted information and generate next question",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "updates": {
                                "type": "object",
                                "properties": {
                                    "core_values_and_priorities": {
                                        "type": "object",
                                        "properties": {
                                            "personal_values": {"type": "array", "items": {"type": "string"}},
                                            "professional_values": {"type": "array", "items": {"type": "string"}},
                                            "prioritization_rules": {"type": "array", "items": {"type": "string"}}
                                        }
                                    },
                                    "personality_and_emotional_profile": {
                                        "type": "object",
                                        "properties": {
                                            "emotional_regulation": {"type": "string"},
                                            "leadership_style": {"type": "string"},
                                            "decision_making_tendencies": {"type": "string"}
                                        }
                                    },
                                    "decision_making_framework": {
                                        "type": "object",
                                        "properties": {
                                            "analytical_intuitive_balance": {"type": "number"},
                                            "risk_tolerance": {"type": "string"},
                                            "timeframe_focus": {"type": "string"}
                                        }
                                    },
                                    "behavioral_patterns": {
                                        "type": "object",
                                        "properties": {
                                            "stress_response": {"type": "string"},
                                            "conflict_resolution": {"type": "string"},
                                            "work_life_balance": {"type": "string"}
                                        }
                                    },
                                    "relationships_and_interactions": {
                                        "type": "object",
                                        "properties": {
                                            "collaboration_style": {"type": "string"},
                                            "trust_building": {"type": "string"},
                                            "conflict_handling": {"type": "string"}
                                        }
                                    },
                                    "growth_and_learning": {
                                        "type": "object",
                                        "properties": {
                                            "preferred_learning": {"type": "string"},
                                            "reflection_tendencies": {"type": "string"},
                                            "openness_to_change": {"type": "number"}
                                        }
                                    },
                                    "creativity_and_divergence": {
                                        "type": "object",
                                        "properties": {
                                            "divergent_thinking": {"type": "string"},
                                            "contrarian_tendencies": {"type": "string"},
                                            "paradox_handling": {"type": "string"},
                                            "deviation_conditions": {"type": "string"}
                                        }
                                    }
                                }
                            },
                            "missing_fields": {"type": "array", "items": {"type": "string"}},
                            "next_question": {"type": "string", "description": "The next question to ask based on missing fields"}
                        },
                        "required": ["updates", "missing_fields", "next_question"]
                    }
                }
            }]

            system_prompt = """You are an expert interviewer focusing on understanding the person deeply.
            After each user response:
            1. Extract ALL relevant information that fits our data model
            2. Update the interview data model using the update_interview_data_model function
            3. Identify missing or incomplete information
            4. Generate a targeted follow-up question

            Always call update_interview_data_model with every response, even if only updating missing_fields.
            Focus questions on gathering missing information systematically."""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]

            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "update_interview_data_model"}}
            )

            return response.choices[0].message

        except Exception as e:
            logger.error(f"Error in extracting interview data: {str(e)}", exc_info=True)
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

            # First, extract structured data and get next question
            extraction_result = self._extract_interview_data(user_message, interview_data)
            logger.info("Extraction result received")

            next_question = None
            if extraction_result and hasattr(extraction_result, 'tool_calls'):
                for tool_call in extraction_result.tool_calls:
                    if tool_call.function.name == "update_interview_data_model":
                        try:
                            data = json.loads(tool_call.function.arguments)
                            logger.info(f"Extracted data: {json.dumps(data, indent=2)}")

                            # Update interview data model
                            for category, updates in data['updates'].items():
                                if hasattr(interview_data, category):
                                    for field, value in updates.items():
                                        if hasattr(interview_data, field):
                                            setattr(interview_data, field, value)
                                            logger.info(f"Updated {category}.{field}")

                            # Update missing fields
                            interview_data.missing_fields = data['missing_fields']
                            next_question = data['next_question']

                            db.session.commit()
                            logger.info("Database updated successfully")
                        except Exception as e:
                            logger.error(f"Error updating interview data: {str(e)}", exc_info=True)

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

                    if run_status.status == 'completed':
                        messages = self.client.beta.threads.messages.list(
                            thread_id=thread_id
                        )

                        # Stream the response and append the next question
                        for msg in messages.data:
                            if msg.role == "assistant":
                                try:
                                    content = msg.content[0].text.value if hasattr(msg.content[0], 'text') else str(msg.content[0])

                                    # If we have a next question, append it
                                    if next_question:
                                        content = f"{content}\n\n{next_question}"

                                    logger.info(f"Assistant response with next question: {content[:100]}...")
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

                    time.sleep(0.5)

                except Exception as e:
                    logger.error(f"Error checking run status: {str(e)}", exc_info=True)
                    retry_count += 1

                    if retry_count >= max_retries:
                        error_msg = f"Max retries reached, failed to get response: {str(e)}"
                        logger.error(error_msg)
                        yield error_msg
                        break

                    time.sleep(1)

        except Exception as e:
            error_msg = f"Error in OpenAI Assistant: {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield error_msg