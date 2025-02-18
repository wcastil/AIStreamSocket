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
            logger.info(f"Starting interim conversation analysis for session {session_id}")

            # Ensure we're in an app context
            if not current_app:
                raise RuntimeError("This function must be called within an application context")

            # Find conversation by session_id
            conversation = Conversation.query.filter_by(session_id=session_id).first()
            if not conversation:
                logger.error(f"No conversation found for session {session_id}")
                raise ValueError(f"No conversation found for session {session_id}")

            # Get conversation history
            history = self.get_conversation_history(conversation.id)
            if not history:
                logger.error("No messages found in conversation")
                raise ValueError("No messages found in conversation")

            logger.info(f"Retrieved {len(history)} messages for analysis")

            # Format conversation for analysis
            formatted_conversation = "\n".join([
                f"{msg['role'].upper()}: {msg['content']}"
                for msg in history
            ])

            # Prepare system prompt with emphasis on interim nature
            system_prompt = f"""Analyze this ongoing interview conversation and extract current insights about the person.
            This is a mid-interview evaluation - do not make final conclusions as the interview is still in progress.
            Generate a JSON response following this exact model structure:

            {json.dumps(self.model_template, indent=2)}

            Guidelines for analysis:
            1. For each section, provide analysis based on available information only
            2. Use "insufficient data" for any attribute without clear evidence
            3. Mark uncertain interpretations clearly
            4. Focus on identifying areas needing more exploration
            5. Consider this an interim assessment that will be refined
            6. Use direct quotes or paraphrased evidence where available

            Your response must be a valid JSON object matching the provided structure.
            For missing information, use null or empty strings rather than making assumptions."""

            logger.info("Sending interim analysis request to OpenAI")
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
            logger.info("Successfully received and parsed OpenAI response")
            logger.debug(f"Structured data: {json.dumps(structured_data, indent=2)}")

            # Identify missing topics
            missing_topics = self.identify_missing_topics(structured_data)
            logger.info(f"Identified {len(missing_topics)} topics needing more exploration")

            # Generate follow-up questions emphasizing ongoing nature
            follow_up_questions = self.generate_follow_up_questions(missing_topics, is_interim=True)
            logger.info(f"Generated {len(follow_up_questions)} potential follow-up questions")

            # Prepare debug info
            debug_info = {
                "system_prompt": system_prompt,
                "conversation_history": formatted_conversation,
                "raw_response": response.choices[0].message.content,
                "model_used": "gpt-4-0125-preview",
                "conversation_length": len(history),
                "missing_fields_count": len(missing_topics),
                "generated_questions_count": len(follow_up_questions),
                "evaluation_type": "interim"
            }

            # Store or update the model
            person_model = PersonModel.query.filter_by(conversation_id=conversation.id).first()
            if person_model:
                logger.info("Updating existing person model with interim assessment")
                person_model.data_model = structured_data
                person_model.missing_topics = missing_topics
                person_model.follow_up_questions = follow_up_questions
                person_model.debug_info = debug_info
            else:
                logger.info("Creating new person model from interim assessment")
                person_model = PersonModel(
                    conversation_id=conversation.id,
                    data_model=structured_data,
                    missing_topics=missing_topics,
                    follow_up_questions=follow_up_questions,
                    debug_info=debug_info
                )
                db.session.add(person_model)

            db.session.commit()
            logger.info(f"Successfully stored interim evaluation for session {session_id}")

            return {
                "success": True,
                "model": structured_data,
                "missing_topics": missing_topics,
                "follow_up_questions": follow_up_questions,
                "debug_info": debug_info,
                "evaluation_type": "interim"
            }

        except Exception as e:
            logger.error(f"Error in interim analysis: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }

    def generate_follow_up_questions(self, missing_topics, is_interim=False):
        """Generate specific follow-up questions for missing topics"""
        if not missing_topics:
            return []

        topics_str = "\n".join([f"- {topic}" for topic in missing_topics])

        system_message = """Generate scored follow-up questions to explore missing areas.
        Each question must include a relevance score from 1-10 based on how well it will improve the person data model.

        Output format must be a JSON array of objects with this structure:
        {
            "questions": [
                {
                    "question": "The follow-up question text",
                    "score": 8,  // Relevance score 1-10
                    "rationale": "Brief explanation of why this question is important"
                }
            ]
        }

        Guidelines for questions:
        1. Open-ended and natural
        2. Build on previous context
        3. Score higher (8-10) for questions that:
           - Fill critical gaps in understanding
           - Address core personality traits or decision patterns
           - Explore complex relationships between topics
        4. Score lower (1-7) for questions that:
           - Are tangential or less relevant
           - Only provide supporting details
           - Repeat previously covered ground
        5. Each score must be justified in the rationale

        Return a minimum of 5 scored questions."""

        response = self.client.chat.completions.create(
            model="gpt-4-0125-preview",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": f"Generate scored follow-up questions for these missing areas:\n{topics_str}"}
            ],
            response_format={"type": "json_object"}
        )

        try:
            result = json.loads(response.choices[0].message.content)
            # Sort questions by score in descending order
            questions = sorted(
                result.get("questions", []),
                key=lambda x: x.get("score", 0),
                reverse=True
            )

            if not questions:
                logger.warning("No questions generated by OpenAI")
                return []

            logger.info(f"Generated {len(questions)} scored follow-up questions")
            for q in questions:
                logger.debug(f"Question (Score {q.get('score')}): {q.get('question')}")
                logger.debug(f"Rationale: {q.get('rationale')}")

            return questions

        except Exception as e:
            logger.error(f"Error parsing follow-up questions: {str(e)}")
            return []

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