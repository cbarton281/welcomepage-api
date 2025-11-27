"""
Game service for handling OpenAI interactions for team-building game questions
"""
import os
import json
import random
import httpx
import time
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
    async def generate_questions(members: List[Dict[str, Any]], alternate_pool: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Generate all game questions in a single OpenAI API call.
        
        Args:
            members: List of team member dictionaries with welcomepage data
            alternate_pool: Optional list of alternate members (minimal data) for distractors
            
        Returns:
            List of question dictionaries
        """
        import time
        import uuid
        request_id = str(uuid.uuid4())[:8]
        start_time = time.time()
        log.info(f"[REQUEST_ID:{request_id}] Starting question generation for {len(members)} members")
        
        # Check API key early
        if not OPENAI_API_KEY or OPENAI_API_KEY == "INSERT_OPENAI_KEY":
            log.error("OPENAI_API_KEY is not configured")
            raise ValueError("OPENAI_API_KEY is not configured")
        
        # Filter members with enough content
        filter_start = time.time()
        eligible_members = [
            m for m in members
            if (m.get("selectedPrompts") and len(m.get("selectedPrompts", [])) > 0) or
               (m.get("bentoWidgets") and len(m.get("bentoWidgets", [])) > 0)
        ]
        filter_time = (time.time() - filter_start) * 1000
        log.info(f"Member filtering took {filter_time:.2f}ms, found {len(eligible_members)} eligible out of {len(members)} total")
        
        if len(eligible_members) < 3:
            log.warning("Not enough eligible members (need at least 3)")
            return []
        
        # Select exactly 10 members for question generation (6 for guess-who + 4 for two-truths-lie)
        # We need 10 unique members total, but fetch a few extra as buffer
        # Randomly select to ensure variety
        select_start = time.time()
        # Select 12 to have buffer, but we'll only use 10 for questions
        selected_members = GameService._shuffle_array(eligible_members)[:12]
        select_time = (time.time() - select_start) * 1000
        log.info(f"Member selection took {select_time:.2f}ms, selected {len(selected_members)} members (will use 10 for questions)")
        
        log.info(f"Generating 10 questions (6 guess-who, 4 two-truths-lie) in single OpenAI call")
        
        # Generate all questions in a single API call
        # Context will be minimized inside to only include members used for questions
        openai_start = time.time()
        questions = await GameService._generate_all_questions_single_call(
            selected_members, request_id, alternate_pool
        )
        openai_time = (time.time() - openai_start) * 1000
        log.info(f"OpenAI API call took {openai_time:.2f}ms")
        
        if not questions:
            log.warning("Failed to generate questions, returning empty list")
            return []
        
        # Shuffle to mix question types
        shuffle_start = time.time()
        shuffled = GameService._shuffle_array(questions)
        shuffle_time = (time.time() - shuffle_start) * 1000
        log.info(f"Question shuffling took {shuffle_time:.2f}ms")
        
        total_time = (time.time() - start_time) * 1000
        log.info(f"Total generate_questions time: {total_time:.2f}ms, returning {len(shuffled[:10])} questions")
        
        return shuffled[:10]  # Return exactly 10 questions
    
    @staticmethod
    def _create_minimized_context(members: List[Dict[str, Any]]) -> str:
        """
        Create a minimized context string with only essential member data.
        Only includes name, prompts, and answers - excludes unnecessary fields.
        Optimized for minimal token usage.
        """
        context_parts = []
        
        for member in members:
            name = member.get('name', 'Unknown')
            nickname = member.get('nickname')
            # Use shorter format: Name (Nick) or just Name
            member_info = f"{name}"
            if nickname and nickname != name:
                member_info += f" ({nickname})"
            
            # Only include prompts and answers - use compact format
            selected_prompts = member.get("selectedPrompts", [])
            answers = member.get("answers", {})
            
            if selected_prompts:
                for prompt in selected_prompts[:3]:  # Limit to 3 prompts per member
                    answer_data = answers.get(prompt, {}) if isinstance(answers, dict) else {}
                    answer_text = answer_data.get("text") if isinstance(answer_data, dict) else None
                    if answer_text:
                        # Use compact format: Q: prompt A: answer
                        # Truncate very long answers to save tokens
                        if len(answer_text) > 200:
                            answer_text = answer_text[:200] + "..."
                        member_info += f'\nQ: {prompt[:60]}'  # Truncate long prompts
                        member_info += f'\nA: {answer_text}'
            
            context_parts.append(member_info)
        
        return "\n\n".join(context_parts)
    
    @staticmethod
    async def _generate_all_questions_single_call(
        members: List[Dict[str, Any]],
        request_id: str = "unknown",
        alternate_pool: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate all questions (guess-who and two-truths-lie) in a single OpenAI API call.
        """
        # Validate we have enough members
        if len(members) < 10:
            log.warning(f"Not enough members for question generation: {len(members)} (need at least 10)")
            return []
        
        # Select members and their specific prompt/answer pairs for each question
        # This dramatically reduces payload - we only send ONE prompt/answer per member
        shuffled = GameService._shuffle_array(members)
        members_to_use = shuffled[:10]
        guess_who_members = members_to_use[:6]
        two_truths_members = members_to_use[6:10]
        
        # Pre-select specific prompt/answer pairs for each question
        def select_prompt_answer_pair(member: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """Select one random prompt/answer pair from a member"""
            selected_prompts = member.get("selectedPrompts", [])
            answers = member.get("answers", {})
            
            if not selected_prompts:
                return None
            
            # Randomly select one prompt that has an answer
            available_prompts = [
                p for p in selected_prompts 
                if isinstance(answers, dict) and answers.get(p, {}).get("text")
            ]
            
            if not available_prompts:
                return None
            
            selected_prompt = random.choice(available_prompts)
            answer_data = answers.get(selected_prompt, {})
            answer_text = answer_data.get("text", "") if isinstance(answer_data, dict) else ""
            
            return {
                "prompt": selected_prompt,
                "answer": answer_text
            }
        
        # Build question assignments with pre-selected prompt/answer pairs
        guess_who_assignments = []
        for member in guess_who_members:
            pair = select_prompt_answer_pair(member)
            if pair:
                guess_who_assignments.append({
                    "name": member.get("name"),
                    "public_id": member.get("public_id"),
                    "prompt": pair["prompt"],
                    "answer": pair["answer"]
                })
        
        two_truths_assignments = []
        for member in two_truths_members:
            pair = select_prompt_answer_pair(member)
            if pair:
                two_truths_assignments.append({
                    "name": member.get("name"),
                    "public_id": member.get("public_id"),
                    "nickname": member.get("nickname"),
                    "prompt": pair["prompt"],
                    "answer": pair["answer"]
                })
        
        # Ensure we have enough assignments
        if len(guess_who_assignments) < 6 or len(two_truths_assignments) < 4:
            log.warning(f"Insufficient prompt/answer pairs: guess-who={len(guess_who_assignments)}, two-truths={len(two_truths_assignments)}")
            return []
        
        # Create ultra-minimal context - only the specific prompt/answer pairs we'll use
        context_parts = []
        for assignment in guess_who_assignments[:6]:
            name = assignment["name"]
            prompt = assignment["prompt"]
            answer = assignment["answer"]
            # Truncate long answers
            if len(answer) > 150:
                answer = answer[:150] + "..."
            context_parts.append(f"{name}: Q: {prompt[:50]} A: {answer}")
        
        for assignment in two_truths_assignments[:4]:
            name = assignment["name"]
            prompt = assignment["prompt"]
            answer = assignment["answer"]
            # Truncate long answers
            if len(answer) > 150:
                answer = answer[:150] + "..."
            context_parts.append(f"{name}: Q: {prompt[:50]} A: {answer}")
        
        minimized_context = "\n".join(context_parts)
        context_size = len(minimized_context)
        log.info(f"Ultra-minimal context: {context_size} characters (only 1 prompt/answer per member for 10 questions)")
        
        # Store assignments for later use in parsing
        member_selections = {
            "guess_who": guess_who_assignments[:6],
            "two_truths_lie": two_truths_assignments[:4]
        }
        
        system_prompt = """Generate team-building game questions from member data. Be concise and creative.

Rules:
- Guess-who: Synthesize info into creative questions (max 80 chars). Don't include names.
- Two-truths-lie: Rephrase 1 truth, create 2 believable lies (max 50 chars each). Add relevant emojis.
- Return JSON only with the exact structure specified."""

        user_prompt = f"""Data:
{minimized_context}

Generate 10 questions using the above prompt/answer pairs:
- 6 guess-who questions (one per person in first 6 lines)
- 4 two-truths-lie questions (one per person in last 4 lines)

JSON structure:
{{
  "guess_who": [
    {{
      "member_name": "Member Name",
      "prompt": "Original prompt text",
      "answer": "Original answer text",
      "question": "Synthesized question text"
    }}
  ],
  "two_truths_lie": [
    {{
      "member_name": "Member Name",
      "prompt": "Original prompt text",
      "answer": "Original answer text",
      "truth": "Rephrased truth statement",
      "lie1": "First believable lie",
      "lie2": "Second believable lie",
      "emojis": {{
        "truth": "emoji",
        "lie1": "emoji",
        "lie2": "emoji"
      }}
    }}
  ]
}}"""

        try:
            import time
            timeout = httpx.Timeout(90.0, connect=10.0)  # Longer timeout for single large call
            
            # Log the exact prompt for testing in ChatGPT
            log.info("=" * 80)
            log.info("OPENAI PROMPT FOR TESTING IN CHATGPT:")
            log.info("=" * 80)
            log.info("SYSTEM PROMPT:")
            log.info(system_prompt)
            log.info("-" * 80)
            log.info("USER PROMPT:")
            log.info(user_prompt)
            log.info("-" * 80)
            log.info("MODEL: gpt-4o")
            log.info("MAX_TOKENS: 1500")
            log.info("TEMPERATURE: 0.7")
            log.info("RESPONSE_FORMAT: json_object")
            log.info("=" * 80)
            log.info("Copy the SYSTEM PROMPT and USER PROMPT above to test in ChatGPT")
            log.info("=" * 80)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                log.info(f"[REQUEST_ID:{request_id}] Making single OpenAI API call to generate all questions")
                request_start = time.time()
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {OPENAI_API_KEY}"
                    },
                    json={
                        "model": "gpt-4o",  # Try full gpt-4o model - may be faster than gpt-4o-mini for structured tasks
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "max_tokens": 1500,  # Reduced - 10 questions with concise text should fit
                        "temperature": 0.7,  # Slightly lower for faster, more consistent generation
                        "response_format": {"type": "json_object"}
                    }
                )
                request_time = (time.time() - request_start) * 1000
                log.info(f"[REQUEST_ID:{request_id}] OpenAI API request completed in {request_time:.2f}ms, status: {response.status_code}")
                
                if response.status_code == 200:
                    parse_start = time.time()
                    data = response.json()
                    parse_time = (time.time() - parse_start) * 1000
                    log.info(f"[REQUEST_ID:{request_id}] OpenAI response JSON parse took {parse_time:.2f}ms")
                    
                    # Log OpenAI API usage (token consumption) for cost tracking
                    usage = data.get("usage", {})
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)
                        total_tokens = usage.get("total_tokens", 0)
                        log.info(f"[REQUEST_ID:{request_id}] OpenAI API Usage - prompt_tokens: {prompt_tokens}, completion_tokens: {completion_tokens}, total_tokens: {total_tokens}")
                    else:
                        log.warning(f"[REQUEST_ID:{request_id}] OpenAI API response missing usage information")
                    
                    content = data.get("choices", [{}])[0].get("message", {}).get("content")
                    
                    if content:
                        json_parse_start = time.time()
                        parsed = json.loads(content)
                        json_parse_time = (time.time() - json_parse_start) * 1000
                        log.info(f"[REQUEST_ID:{request_id}] Content JSON parse took {json_parse_time:.2f}ms")
                        
                        question_parse_start = time.time()
                        questions = GameService._parse_questions_from_response(
                            parsed, members, member_selections, alternate_pool
                        )
                        question_parse_time = (time.time() - question_parse_start) * 1000
                        log.info(f"[REQUEST_ID:{request_id}] Question parsing took {question_parse_time:.2f}ms, generated {len(questions)} questions")
                        return questions
                    else:
                        log.error(f"[REQUEST_ID:{request_id}] OpenAI response missing content")
                else:
                    error_text = response.text[:500] if hasattr(response, 'text') else str(response)
                    log.error(f"[REQUEST_ID:{request_id}] OpenAI API error: {response.status_code} - {error_text}")
        except Exception as e:
            log.error(f"[REQUEST_ID:{request_id}] Error in _generate_all_questions_single_call: {e}")
        
        return []
    
    @staticmethod
    def _parse_questions_from_response(
        parsed: Dict[str, Any],
        members: List[Dict[str, Any]],
        member_selections: Dict[str, List[Dict[str, Any]]],
        alternate_pool: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Parse OpenAI response and convert to question format"""
        questions: List[Dict[str, Any]] = []
        
        # Create lookup maps
        member_map = {m.get("name"): m for m in members}
        # Create lookup for pre-selected assignments
        guess_who_assignments_map = {a["name"]: a for a in member_selections.get("guess_who", [])}
        two_truths_assignments_map = {a["name"]: a for a in member_selections.get("two_truths_lie", [])}
        
        # Initialize usage tracker for alternates (to avoid repetition)
        alternate_usage: Dict[str, int] = {}
        if alternate_pool:
            for alt in alternate_pool:
                alt_id = alt.get("public_id")
                if alt_id:
                    alternate_usage[alt_id] = 0
        
        # Process guess-who questions
        guess_who_data = parsed.get("guess_who", [])
        for q_data in guess_who_data[:6]:  # Limit to 6
            member_name = q_data.get("member_name")
            member = member_map.get(member_name)
            assignment = guess_who_assignments_map.get(member_name)
            
            if not member or not assignment:
                log.warning(f"Member or assignment not found: {member_name}")
                continue
            
            # Use the pre-selected prompt/answer from assignment
            # OpenAI might have rephrased, but we use our original for consistency
            original_prompt = assignment.get("prompt", q_data.get("prompt", ""))
            original_answer = assignment.get("answer", q_data.get("answer", ""))
            
            # Get distractors (prefer alternate pool, track usage to avoid repetition)
            distractors = GameService._get_random_distractors(
                members, member, 2, alternate_pool, alternate_usage
            )
            if len(distractors) < 2:
                continue
            
            question_id = f"synthesized-{member.get('public_id')}-{int(time.time() * 1000)}-{random.random()}"
            question = {
                "id": question_id,
                "type": "guess-who",
                "question": q_data.get("question", "").strip('"\''),
                "correctAnswer": member.get("name"),
                "correctAnswerId": member.get("public_id"),
                "options": GameService._shuffle_array([
                    {
                        "id": member.get("public_id"),
                        "name": member.get("name"),
                        "avatar": member.get("profile_image")
                    },
                    *[{"id": m.get("public_id"), "name": m.get("name"), "avatar": m.get("profile_image")} for m in distractors]
                ]),
                "promptText": original_prompt,
                "answerText": original_answer,
                "additionalInfo": f'{member.get("name")} said: "{original_prompt}: {original_answer}"'
            }
            questions.append(question)
        
        # Process two-truths-lie questions
        two_truths_data = parsed.get("two_truths_lie", [])
        for q_data in two_truths_data[:4]:  # Limit to 4
            member_name = q_data.get("member_name")
            member = member_map.get(member_name)
            assignment = two_truths_assignments_map.get(member_name)
            
            if not member or not assignment:
                log.warning(f"Member or assignment not found: {member_name}")
                continue
            
            # Use the pre-selected prompt/answer from assignment
            original_prompt = assignment.get("prompt", q_data.get("prompt", ""))
            original_answer = assignment.get("answer", q_data.get("answer", ""))
            
            # Filter bad emojis
            bad_emojis = ["✅", "✓", "✔", "❌", "✗", "✖"]
            emojis_data = q_data.get("emojis", {})
            
            def filter_emoji(emoji: Optional[str]) -> str:
                if not emoji or emoji in bad_emojis:
                    return "❓"
                return emoji
            
            emojis = {
                "truth": filter_emoji(emojis_data.get("truth")) or "✨",
                "lie1": filter_emoji(emojis_data.get("lie1")) or "❓",
                "lie2": filter_emoji(emojis_data.get("lie2")) or "❓"
            }
            
            display_name = member.get("nickname") or member.get("name", "").split()[0]
            question_id = f"two-truths-{member.get('public_id')}-{int(time.time() * 1000)}-{random.random()}"
            question = {
                "id": question_id,
                "type": "two-truths-lie",
                "question": f"Two truths and a lie about {display_name}",
                "correctAnswer": q_data.get("truth", ""),
                "correctAnswerId": "truth",
                "options": GameService._shuffle_array([
                    {"id": "truth", "name": q_data.get("truth", "")},
                    {"id": "lie1", "name": q_data.get("lie1", "")},
                    {"id": "lie2", "name": q_data.get("lie2", "")}
                ]),
                "emojis": emojis,
                "promptText": original_prompt,
                "answerText": original_answer,
                "additionalInfo": f'{member.get("name")}: {original_answer}',
                "memberPublicId": member.get("public_id"),
                "memberNickname": display_name
            }
            questions.append(question)
        
        return questions
    
    @staticmethod
    def _get_random_distractors(
        members: List[Dict[str, Any]],
        exclude: Dict[str, Any],
        count: int,
        alternate_pool: Optional[List[Dict[str, Any]]] = None,
        usage_tracker: Optional[Dict[str, int]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get random distractors (other members) for a question.
        Prefers alternate_pool if provided, using usage_tracker to avoid repetition.
        Falls back to members list if alternate_pool is not available or exhausted.
        """
        exclude_id = exclude.get("public_id")
        distractors: List[Dict[str, Any]] = []
        
        # Prefer alternate pool if available
        if alternate_pool and usage_tracker is not None:
            # Filter out the excluded member and get available alternates
            available_alternates = [
                alt for alt in alternate_pool
                if alt.get("public_id") != exclude_id
            ]
            
            # Sort by usage count (ascending) to prefer least-used alternates
            available_alternates.sort(key=lambda alt: usage_tracker.get(alt.get("public_id", ""), 0))
            
            # Select up to count distinct alternates
            selected_alternates = []
            for alt in available_alternates:
                if len(selected_alternates) >= count:
                    break
                alt_id = alt.get("public_id")
                if alt_id:
                    selected_alternates.append(alt)
                    # Increment usage count
                    usage_tracker[alt_id] = usage_tracker.get(alt_id, 0) + 1
            
            # Convert alternate format to match expected format (with profile_image)
            for alt in selected_alternates:
                distractors.append({
                    "public_id": alt.get("public_id"),
                    "name": alt.get("name"),
                    "profile_image": alt.get("wave_gif_url")  # Use wave_gif_url as avatar fallback
                })
        
        # If we still need more distractors, fall back to members list
        if len(distractors) < count:
            available_members = [
                m for m in members
                if m.get("public_id") != exclude_id
                and not any(d.get("public_id") == m.get("public_id") for d in distractors)
            ]
            random.shuffle(available_members)
            needed = count - len(distractors)
            distractors.extend(available_members[:needed])
        
        return distractors[:count]
    
    @staticmethod
    def _shuffle_array(array: List[Any]) -> List[Any]:
        """Shuffle an array in place and return it"""
        shuffled = array.copy()
        random.shuffle(shuffled)
        return shuffled
