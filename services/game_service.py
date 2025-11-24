"""
Game service for handling OpenAI interactions for team-building game questions
"""
import os
import json
import random
import httpx
from typing import List, Dict, Optional, Any
from utils.logger_factory import new_logger

log = new_logger("game_service")

# Get OpenAI API key from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY or OPENAI_API_KEY == "INSERT_OPENAI_KEY":
    log.warning("OPENAI_API_KEY not set or is placeholder. Game question generation will fail.")


class GameService:
    """Service for generating game questions using OpenAI"""
    
    @staticmethod
    async def generate_questions(members: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Generate game questions from team members' welcomepage content.
        
        Args:
            members: List of team member dictionaries with welcomepage data
            
        Returns:
            List of question dictionaries
        """
        log.info(f"Starting question generation for {len(members)} members")
        
        # Check API key early
        if not OPENAI_API_KEY or OPENAI_API_KEY == "INSERT_OPENAI_KEY":
            log.error("OPENAI_API_KEY is not configured")
            raise ValueError("OPENAI_API_KEY is not configured")
        
        questions: List[Dict[str, Any]] = []
        
        # Filter members with enough content
        eligible_members = [
            m for m in members
            if (m.get("selectedPrompts") and len(m.get("selectedPrompts", [])) > 0) or
               (m.get("bentoWidgets") and len(m.get("bentoWidgets", [])) > 0)
        ]
        
        log.info(f"Found {len(eligible_members)} eligible members out of {len(members)} total")
        
        if len(eligible_members) < 3:
            log.warning("Not enough eligible members (need at least 3)")
            return questions
        
        # Generate questions with 2/3 guess-who, 1/3 two-truths-lie ratio
        # Target: ~7 guess-who, ~3 two-truths-lie out of 10 total
        target_two_truths = 4  # Aim for 4 to ensure we get at least 3
        target_guess_who = 6  # Start with 6, will add more if needed
        
        log.info(f"Generating {target_guess_who} guess-who questions and {target_two_truths} two-truths-lie questions")
        
        synthesized_questions = await GameService.generate_synthesized_questions(
            eligible_members, target_guess_who
        )
        log.info(f"Generated {len(synthesized_questions)} synthesized questions")
        
        two_truths_questions = await GameService.generate_two_truths_and_lie_questions(
            eligible_members, target_two_truths
        )
        log.info(f"Generated {len(two_truths_questions)} two-truths-lie questions")
        
        # Combine questions
        questions.extend(synthesized_questions)
        questions.extend(two_truths_questions)
        
        # If we don't have enough questions total, generate more guess-who to fill to 10
        if len(questions) < 10:
            needed = 10 - len(questions)
            more_guess_who = await GameService.generate_synthesized_questions(
                eligible_members, needed, questions
            )
            questions.extend(more_guess_who)
        
        # Shuffle to mix question types
        shuffled = GameService._shuffle_array(questions)
        
        return shuffled[:10]  # Return exactly 10 questions
    
    @staticmethod
    async def generate_synthesized_questions(
        members: List[Dict[str, Any]],
        target_count: int = 7,
        existing_questions: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Generate synthesized 'guess-who' questions"""
        if existing_questions is None:
            existing_questions = []
        
        questions: List[Dict[str, Any]] = []
        
        # Format all team members' welcomepage content for ChatGPT
        welcomepage_content = GameService._format_welcomepage_content_for_chatgpt(members)
        
        # Generate up to target_count questions, try more attempts to ensure we get enough
        max_attempts = target_count * 3  # Try 3x the target to account for failures
        
        for i in range(max_attempts):
            if len(questions) >= target_count:
                break
            
            try:
                question_data = await GameService._generate_single_synthesized_question(
                    welcomepage_content, members, existing_questions + questions
                )
                
                if question_data:
                    # Get 2 random distractors
                    correct_member = next(
                        (m for m in members if m.get("public_id") == question_data["correctAnswerId"]),
                        None
                    )
                    if not correct_member:
                        continue
                    
                    distractors = GameService._get_random_distractors(members, correct_member, 2)
                    
                    if len(distractors) == 2:
                        import time
                        question_id = f"synthesized-{question_data['correctAnswerId']}-{int(time.time() * 1000)}-{random.random()}"
                        question = {
                            "id": question_id,
                            "type": "guess-who",
                            "question": question_data["synthesizedQuestion"],
                            "correctAnswer": question_data["correctAnswerName"],
                            "correctAnswerId": question_data["correctAnswerId"],
                            "options": GameService._shuffle_array([
                                {
                                    "id": question_data["correctAnswerId"],
                                    "name": question_data["correctAnswerName"],
                                    "avatar": question_data.get("correctAnswerAvatar")
                                },
                                *[{"id": m.get("public_id"), "name": m.get("name"), "avatar": m.get("profile_image")} for m in distractors]
                            ]),
                            "promptText": question_data["originalPrompt"],
                            "answerText": question_data["originalAnswer"],
                            "additionalInfo": f'{question_data["correctAnswerName"]} said: "{question_data["originalPrompt"]}: {question_data["originalAnswer"]}"'
                        }
                        questions.append(question)
            except Exception as e:
                log.error(f"Error generating synthesized question: {e}")
                # Continue to next question
        
        return questions
    
    @staticmethod
    async def _generate_single_synthesized_question(
        welcomepage_content: str,
        members: List[Dict[str, Any]],
        existing_questions: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Generate a single synthesized question using OpenAI"""
        if not OPENAI_API_KEY or OPENAI_API_KEY == "INSERT_OPENAI_KEY":
            raise ValueError("OPENAI_API_KEY is not configured")
        
        log.debug("Calling OpenAI API for synthesized question")
        try:
            # Find a member with content that hasn't been used yet
            used_member_ids = {q.get("correctAnswerId") for q in existing_questions}
            available_members = [
                m for m in members
                if m.get("public_id") not in used_member_ids
                and m.get("selectedPrompts")
                and len(m.get("selectedPrompts", [])) > 0
            ]
            
            # Pick a member (prefer available, but can reuse if needed)
            if available_members:
                target_member = random.choice(available_members)
            else:
                target_member = random.choice(members)
            
            prompts = target_member.get("selectedPrompts", [])
            if not prompts:
                return None
            
            target_prompt = random.choice(prompts)
            answers = target_member.get("answers", {})
            target_answer = answers.get(target_prompt, {}).get("text") if isinstance(answers, dict) else None
            
            if not target_answer:
                return None
            
            system_prompt = """You are a creative trivia question writer for a team-building game. Your job is to synthesize questions from team members' welcomepage content.

Rules:
- Create engaging, fun questions that test how well team members know each other
- Synthesize the information - don't just repeat the prompt/answer verbatim
- Make questions creative and interesting (e.g., if someone said "I can do a backflip" to "tell us a quirky fact", you might ask "Who can invert themselves in the air?")
- Questions should be clear and answerable by someone who knows the team member
- Keep questions concise (under 100 characters)
- Return ONLY the synthesized question, nothing else
- Do NOT include the person's name in the question"""
            
            user_prompt = f"""{welcomepage_content}

Based on the above team member content, create a synthesized trivia question. Focus on this specific prompt/answer pair:

Member: {target_member.get("name")}
Original Prompt: "{target_prompt}"
Original Answer: "{target_answer}"

Create a creative, synthesized question that captures the essence of this answer without directly quoting it. The question should be answerable by selecting {target_member.get("name")} from a list of team members."""
            
            # Use a longer timeout for OpenAI API calls
            timeout = httpx.Timeout(60.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                log.debug(f"Making OpenAI API request for member: {target_member.get('name')}")
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {OPENAI_API_KEY}"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "max_tokens": 150,
                        "temperature": 0.8
                    }
                )
                log.debug(f"OpenAI API response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    synthesized_question = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    
                    if synthesized_question:
                        # Remove quotes if present
                        synthesized_question = synthesized_question.strip('"\'')
                        return {
                            "synthesizedQuestion": synthesized_question,
                            "correctAnswerId": target_member.get("public_id"),
                            "correctAnswerName": target_member.get("name"),
                            "correctAnswerAvatar": target_member.get("profile_image"),
                            "originalPrompt": target_prompt,
                            "originalAnswer": target_answer
                        }
                else:
                    log.error(f"OpenAI API error: {response.status_code} - {response.text}")
        except Exception as e:
            log.error(f"Error in _generate_single_synthesized_question: {e}")
        
        return None
    
    @staticmethod
    async def generate_two_truths_and_lie_questions(
        members: List[Dict[str, Any]],
        target_count: int = 4
    ) -> List[Dict[str, Any]]:
        """Generate 'two truths and a lie' questions"""
        questions: List[Dict[str, Any]] = []
        
        # Format all team members' welcomepage content for ChatGPT
        welcomepage_content = GameService._format_welcomepage_content_for_chatgpt(members)
        
        # Try all eligible members
        eligible_members = [
            m for m in members
            if m.get("selectedPrompts") and len(m.get("selectedPrompts", [])) > 0
        ]
        
        if not eligible_members:
            return questions
        
        # Prepare member/prompt combinations
        member_prompt_pairs: List[Dict[str, Any]] = []
        for member in eligible_members:
            for prompt in member.get("selectedPrompts", []):
                answers = member.get("answers", {})
                answer = answers.get(prompt, {}).get("text") if isinstance(answers, dict) else None
                if answer and len(answer.strip()) > 10:
                    member_prompt_pairs.append({
                        "member": member,
                        "prompt": prompt,
                        "answer": answer
                    })
        
        # Shuffle and take up to target_count * 2 to have backups
        shuffled_pairs = GameService._shuffle_array(member_prompt_pairs)[:target_count * 2]
        
        log.info(f"Starting parallel generation. Target: {target_count}, Candidate pairs: {len(shuffled_pairs)}")
        
        # Generate questions in parallel (up to target_count)
        import asyncio
        generation_tasks = [
            GameService._generate_two_truths_question_task(
                welcomepage_content, pair["member"], pair["prompt"], pair["answer"]
            )
            for pair in shuffled_pairs[:target_count]
        ]
        
        results = await asyncio.gather(*generation_tasks, return_exceptions=True)
        successful_questions = [q for q in results if isinstance(q, dict) and q is not None]
        
        # If we got fewer than target, try the backup candidates sequentially
        if len(successful_questions) < target_count and len(shuffled_pairs) > target_count:
            log.info(f"Got {len(successful_questions)}/{target_count}, trying backup candidates...")
            
            for pair in shuffled_pairs[target_count:]:
                if len(successful_questions) >= target_count:
                    break
                
                # Skip if we already have a question for this member
                if any(q.get("memberPublicId") == pair["member"].get("public_id") for q in successful_questions):
                    continue
                
                try:
                    two_truths_data = await GameService._generate_two_truths_and_lie_with_chatgpt(
                        welcomepage_content, pair["member"], pair["prompt"], pair["answer"]
                    )
                    
                    if two_truths_data:
                        display_name = pair["member"].get("nickname") or pair["member"].get("name", "").split()[0]
                        import time
                        question_id = f"two-truths-{pair['member'].get('public_id')}-{int(time.time() * 1000)}-{random.random()}"
                        question = {
                            "id": question_id,
                            "type": "two-truths-lie",
                            "question": f"Two truths and a lie about {display_name}",
                            "correctAnswer": two_truths_data["truth"],
                            "correctAnswerId": "truth",
                            "options": GameService._shuffle_array([
                                {"id": "truth", "name": two_truths_data["truth"]},
                                {"id": "lie1", "name": two_truths_data["lie1"]},
                                {"id": "lie2", "name": two_truths_data["lie2"]}
                            ]),
                            "emojis": two_truths_data["emojis"],
                            "promptText": pair["prompt"],
                            "answerText": pair["answer"],
                            "additionalInfo": f'{pair["member"].get("name")}: {pair["answer"]}',
                            "memberPublicId": pair["member"].get("public_id"),
                            "memberNickname": display_name
                        }
                        successful_questions.append(question)
                except Exception as e:
                    log.error(f"Error generating backup two-truths question: {e}")
        
        log.info(f"Finished. Generated {len(successful_questions)}/{target_count} questions")
        
        return successful_questions[:target_count]
    
    @staticmethod
    async def _generate_two_truths_question_task(
        welcomepage_content: str,
        member: Dict[str, Any],
        prompt: str,
        answer: str
    ) -> Optional[Dict[str, Any]]:
        """Task wrapper for generating a single two-truths question"""
        try:
            log.info(f"Generating for {member.get('name')}")
            two_truths_data = await GameService._generate_two_truths_and_lie_with_chatgpt(
                welcomepage_content, member, prompt, answer
            )
            
            if two_truths_data:
                display_name = member.get("nickname") or member.get("name", "").split()[0]
                import time
                question_id = f"two-truths-{member.get('public_id')}-{int(time.time() * 1000)}-{random.random()}"
                return {
                    "id": question_id,
                    "type": "two-truths-lie",
                    "question": f"Two truths and a lie about {display_name}",
                    "correctAnswer": two_truths_data["truth"],
                    "correctAnswerId": "truth",
                    "options": GameService._shuffle_array([
                        {"id": "truth", "name": two_truths_data["truth"]},
                        {"id": "lie1", "name": two_truths_data["lie1"]},
                        {"id": "lie2", "name": two_truths_data["lie2"]}
                    ]),
                    "emojis": two_truths_data["emojis"],
                    "promptText": prompt,
                    "answerText": answer,
                    "additionalInfo": f'{member.get("name")}: {answer}',
                    "memberPublicId": member.get("public_id"),
                    "memberNickname": display_name
                }
            return None
        except Exception as e:
            log.error(f"Error generating two-truths question for {member.get('name')}: {e}")
            return None
    
    @staticmethod
    async def _generate_two_truths_and_lie_with_chatgpt(
        welcomepage_content: str,
        member: Dict[str, Any],
        original_prompt: str,
        original_answer: str
    ) -> Optional[Dict[str, Any]]:
        """Generate two truths and a lie using OpenAI"""
        if not OPENAI_API_KEY or OPENAI_API_KEY == "INSERT_OPENAI_KEY":
            raise ValueError("OPENAI_API_KEY is not configured")
        
        try:
            system_prompt = """You are a creative trivia game writer for a team-building game. Your job is to create "2 Truths and a Lie" questions based on team members' welcomepage content.

Rules:
- Create 2 believable lies that could plausibly be true about the person
- Rephrase 1 truth from their welcomepage content (don't quote it verbatim)
- All three statements should be similar in style and believability
- Keep statements concise (under 60 characters each)
- For each statement (truth, lie1, lie2), suggest ONE relevant emoji that represents that statement
- Emojis should be contextually relevant to the statement content (e.g., 🏔️ for mountains, 🎨 for art, 🎸 for music)
- Do NOT use checkmarks or X marks - use relevant thematic emojis
- Return JSON with: truth (rephrased fact), lie1, lie2, and emojis as an object mapping each statement to its emoji
- The truth should be based on the original answer provided
- The lies should be creative but believable"""
            
            user_prompt = f"""{welcomepage_content}

Based on the above team member content, create a "2 Truths and a Lie" question. Focus on this specific prompt/answer pair:

Member: {member.get("name")}
Original Prompt: "{original_prompt}"
Original Answer: "{original_answer}"

Create 2 believable lies and rephrase the truth. For each statement, suggest ONE relevant emoji that represents that statement (use contextually appropriate emojis, not checkmarks/X marks).

Return JSON only with this exact structure:
{{
  "truth": "rephrased truth statement",
  "lie1": "first believable lie",
  "lie2": "second believable lie",
  "emojis": {{
    "truth": "relevant emoji for truth",
    "lie1": "relevant emoji for lie1",
    "lie2": "relevant emoji for lie2"
  }}
}}"""
            
            # Use a longer timeout for OpenAI API calls
            timeout = httpx.Timeout(60.0, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                log.debug(f"Making OpenAI API request for two-truths-lie: {member.get('name')}")
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {OPENAI_API_KEY}"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "max_tokens": 300,
                        "temperature": 0.8,
                        "response_format": {"type": "json_object"}
                    }
                )
                log.debug(f"OpenAI API response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content")
                    
                    if content:
                        parsed = json.loads(content)
                        
                        # Handle emoji format (both array and object)
                        emojis: Dict[str, str]
                        if isinstance(parsed.get("emojis"), list):
                            # Legacy array format
                            emoji_list = parsed.get("emojis", [])
                            bad_emojis = ["✅", "✓", "✔", "❌", "✗", "✖"]
                            truth_emoji = emoji_list[0] if emoji_list and emoji_list[0] not in bad_emojis else "✨"
                            lie1_emoji = emoji_list[1] if len(emoji_list) > 1 and emoji_list[1] not in bad_emojis else "❓"
                            lie2_emoji = emoji_list[2] if len(emoji_list) > 2 and emoji_list[2] not in bad_emojis else "❓"
                            emojis = {
                                "truth": truth_emoji,
                                "lie1": lie1_emoji,
                                "lie2": lie2_emoji
                            }
                        else:
                            # Object format
                            raw_emojis = parsed.get("emojis", {})
                            bad_emojis = ["✅", "✓", "✔", "❌", "✗", "✖"]
                            
                            def filter_bad_emoji(emoji: Optional[str]) -> str:
                                if not emoji or emoji in bad_emojis:
                                    return "❓"
                                return emoji
                            
                            emojis = {
                                "truth": filter_bad_emoji(raw_emojis.get("truth")) or "✨",
                                "lie1": filter_bad_emoji(raw_emojis.get("lie1")) or "❓",
                                "lie2": filter_bad_emoji(raw_emojis.get("lie2")) or "❓"
                            }
                        
                        return {
                            "truth": parsed.get("truth") or original_answer[:50],
                            "lie1": parsed.get("lie1") or "Likes pineapple on pizza",
                            "lie2": parsed.get("lie2") or "Has been to 50 countries",
                            "emojis": emojis
                        }
                else:
                    log.error(f"OpenAI API error: {response.status_code} - {response.text}")
        except Exception as e:
            log.error(f"Error in _generate_two_truths_and_lie_with_chatgpt: {e}")
        
        # Fallback - but we should error out per user's request
        raise ValueError("Failed to generate two truths and a lie question")
    
    @staticmethod
    def _format_welcomepage_content_for_chatgpt(members: List[Dict[str, Any]]) -> str:
        """Format team members' welcomepage content for ChatGPT"""
        content = "Here are the team members and their welcomepage content:\n\n"
        
        for index, member in enumerate(members, 1):
            content += f"--- Team Member {index} ---\n"
            content += f"Name: {member.get('name', 'Unknown')}\n"
            
            if member.get("nickname"):
                content += f"Nickname: {member.get('nickname')}\n"
            
            content += f"Role: {member.get('role', 'Not specified')}\n"
            
            selected_prompts = member.get("selectedPrompts", [])
            if selected_prompts:
                content += "\nPrompts and Answers:\n"
                answers = member.get("answers", {})
                for prompt in selected_prompts:
                    answer_data = answers.get(prompt, {}) if isinstance(answers, dict) else {}
                    answer_text = answer_data.get("text") if isinstance(answer_data, dict) else None
                    if answer_text:
                        content += f'  Prompt: "{prompt}"\n'
                        content += f'  Answer: "{answer_text}"\n\n'
            
            bento_widgets = member.get("bentoWidgets", [])
            if bento_widgets:
                content += "\nAdditional Information:\n"
                for widget in bento_widgets:
                    if isinstance(widget, dict) and widget.get("type") == "location":
                        widget_content = widget.get("content", {})
                        if isinstance(widget_content, dict) and widget_content.get("location"):
                            content += f"  Location: {widget_content.get('location')}\n"
            
            content += "\n"
        
        return content
    
    @staticmethod
    def _get_random_distractors(
        members: List[Dict[str, Any]],
        exclude: Dict[str, Any],
        count: int
    ) -> List[Dict[str, Any]]:
        """Get random distractors (other members) for a question"""
        exclude_id = exclude.get("public_id")
        available = [m for m in members if m.get("public_id") != exclude_id]
        random.shuffle(available)
        return available[:count]
    
    @staticmethod
    def _shuffle_array(array: List[Any]) -> List[Any]:
        """Shuffle an array in place and return it"""
        shuffled = array.copy()
        random.shuffle(shuffled)
        return shuffled

