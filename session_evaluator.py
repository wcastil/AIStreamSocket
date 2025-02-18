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
            logger.warning("empty_model_001.json not found, using default empty model")
            self.model_template = {
                "personal_values": [],
                "professional_values": [],
                "leadership_style": None,
                "decision_making": {
                    "style": None,
                    "risk_tolerance": None
                },
                "communication": {
                    "style": None,
                    "strengths": [],
                    "areas_for_improvement": []
                },
                "learning": {
                    "preferred_style": None,
                    "growth_mindset": None
                }
            }

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

            # Process with OpenAI
            response = self.client.chat.completions.create(
                model="gpt-4-0125-preview",  # Using latest model for better structured output
                messages=[
                    {
                        "role": "system",
                        "content": """Analyze the interview conversation and extract structured insights about the person.
                        Focus on:
                        1. Personal and professional values
                        2. Leadership and decision-making style
                        3. Communication patterns and preferences
                        4. Learning and growth mindset
                        
                        Provide output in JSON format matching this structure:
                        {
                            "personal_values": [],
                            "professional_values": [],
                            "leadership_style": "",
                            "decision_making": {
                                "style": "",
                                "risk_tolerance": ""
                            },
                            "communication": {
                                "style": "",
                                "strengths": [],
                                "areas_for_improvement": []
                            },
                            "learning": {
                                "preferred_style": "",
                                "growth_mindset": null
                            }
                        }"""
                    },
                    {"role": "user", "content": formatted_conversation}
                ],
                response_format={"type": "json_object"}
            )

            # Parse the structured insights
            structured_data = json.loads(response.choices[0].message.content)
            logger.info(f"🔹 Extracted Data Model: {structured_data}")

            # Compare with template to identify missing topics
            missing_topics = self.identify_missing_topics(structured_data)

            # Generate follow-up questions
            follow_up_questions = self.generate_follow_up_questions(missing_topics)

            # Store the model
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
                "follow_up_questions": follow_up_questions
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
        
        def check_value(value, path):
            if value is None or value == "" or (isinstance(value, list) and len(value) == 0):
                missing_topics.append(path)
            elif isinstance(value, dict):
                for key, subvalue in value.items():
                    check_value(subvalue, f"{path}.{key}")

        for key, value in self.model_template.items():
            check_value(structured_data.get(key), key)

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
                    Questions should be conversational and encourage detailed responses.
                    Return questions in JSON array format."""
                },
                {"role": "user", "content": f"Generate follow-up questions for these missing topics:\n{topics_str}"}
            ],
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content).get("questions", [])
