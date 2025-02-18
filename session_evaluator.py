import logging
import json
import os
from openai import OpenAI
from models import Conversation, Message, PersonModel
from database import db
from flask import current_app

logger = logging.getLogger(__name__)

class SessionEvaluator:
    def __init__(self):
        self.client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        # Load the empty model template
        try:
            with open('empty_model_001.json', 'r') as f:
                self.model_template = json.load(f)
        except FileNotFoundError:
            logger.error("empty_model_001.json not found, this is required for proper evaluation")
            raise

    def get_conversation_history(self, conversation_id):
        """Retrieve full conversation history"""
        messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at).all()
        return [{"role": msg.role, "content": msg.content} for msg in messages]

    def analyze_conversation(self, session_id):
        """Analyze conversation and generate structured insights"""
        try:
            # Find conversation by session_id
            conversation = Conversation.query.filter_by(session_id=session_id).first()
            if not conversation:
                raise ValueError(f"No conversation found for session {session_id}")

            # Get conversation history
            history = self.get_conversation_history(conversation.id)
            if not history:
                raise ValueError("No messages found in conversation")

            # Format conversation for analysis
            formatted_conversation = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in history
            ])

            # Prepare system prompt
            system_prompt = f"""Analyze the interview conversation and extract structured insights about the person.
            Generate a JSON response following this exact model structure:

            {json.dumps(self.model_template, indent=2)}

            Guidelines for analysis:
            1. For each section, provide detailed analysis within the structure
            2. For attributes, use specific examples from the conversation
            3. For potential_divergence_points, identify possible inconsistencies or areas of change
            4. Keep definitions concise but informative
            5. Use direct quotes or paraphrased evidence from the conversation where possible
            6. Mark uncertain interpretations with appropriate qualifiers

            Your response must be a valid JSON object matching the provided structure.
            If information is missing or uncertain, indicate this clearly in the relevant fields."""

            # Process with OpenAI
            response = self.client.chat.completions.create(
                model="gpt-4-0125-preview",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {"role": "user", "content": formatted_conversation}
                ],
                response_format={"type": "json_object"}
            )

            # Parse the structured insights
            structured_data = json.loads(response.choices[0].message.content)
            logger.info(f"🔹 Extracted Person Model: {json.dumps(structured_data, indent=2)}")

            # Identify missing topics by comparing with template
            missing_topics = self.identify_missing_topics(structured_data)

            # Generate follow-up questions for missing areas
            follow_up_questions = self.generate_follow_up_questions(missing_topics)

            # Prepare debug info
            debug_info = {
                "system_prompt": system_prompt,
                "conversation_history": formatted_conversation,
                "raw_response": response.choices[0].message.content,
                "model_used": "gpt-4-0125-preview",
                "conversation_length": len(history),
                "missing_fields_count": len(missing_topics),
                "generated_questions_count": len(follow_up_questions)
            }

            # Store or update the model
            person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
            if person_model:
                person_model.data_model = structured_data
                person_model.missing_topics = missing_topics
                person_model.follow_up_questions = follow_up_questions
            else:
                person_model = PersonModel(
                    conversation_id=conversation.id,
                    data_model=structured_data,
                    missing_topics=missing_topics,
                    follow_up_questions=follow_up_questions
                )
                db.session.add(person_model)

            db.session.commit()
            logger.info(f"Successfully stored person model for session {session_id}")

            return {
                "success": True,
                "model": structured_data,
                "missing_topics": missing_topics,
                "follow_up_questions": follow_up_questions,
                "debug_info": debug_info
            }

        except Exception as e:
            logger.error(f"Error analyzing conversation: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def identify_missing_topics(self, structured_data):
        """Compare extracted data with template to identify missing or incomplete topics"""
        missing_topics = []

        def check_missing_fields(template, data, path=""):
            if isinstance(template, dict):
                for key, value in template.items():
                    new_path = f"{path}.{key}" if path else key

                    # Skip checking definition and example fields
                    if key in ['definition', 'example']:
                        continue

                    if key not in data:
                        missing_topics.append(new_path)
                    elif isinstance(value, (dict, list)):
                        check_missing_fields(value, data[key], new_path)
                    elif not data[key] and data[key] != 0:  # Allow 0 as a valid value
                        missing_topics.append(new_path)
            elif isinstance(template, list) and not data:
                missing_topics.append(path)

        check_missing_fields(self.model_template, structured_data)
        return missing_topics

    def generate_follow_up_questions(self, missing_topics):
        """Generate specific follow-up questions for missing topics"""
        if not missing_topics:
            return []

        topics_str = "\n".join([f"- {topic}" for topic in missing_topics])

        response = self.client.chat.completions.create(
            model="gpt-4-0125-preview",
            messages=[
                {
                    "role": "system",
                    "content": """Generate specific, open-ended follow-up questions to gather missing information.
                    Questions should be:
                    1. Conversational and natural
                    2. Designed to elicit detailed responses
                    3. Prioritized by importance
                    4. Focused on understanding the person's:
                       - Core values and behavioral patterns
                       - Decision-making processes
                       - Growth and adaptation capabilities
                       - Relationship dynamics
                    Return questions in JSON array format."""
                },
                {"role": "user", "content": f"Generate follow-up questions for these missing topics:\n{topics_str}"}
            ],
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content).get("questions", [])