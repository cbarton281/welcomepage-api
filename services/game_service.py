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
        
        # Shuffle to mix question types with balanced distribution
        shuffle_start = time.time()
        shuffled = GameService._balanced_shuffle_questions(questions)
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
        
        # Select 10 UNIQUE members as subjects, ensuring each has valid content
        # Track used subject IDs to prevent duplicates across question types
        used_subject_ids = set()
        selected_subjects = []
        shuffled = GameService._shuffle_array(members)
        
        # Collect members with valid content (any prompt/answer pair)
        for member in shuffled:
            if len(selected_subjects) >= 10:
                break
            
            member_id = member.get("public_id")
            if not member_id or member_id in used_subject_ids:
                continue
            
            # Check if member has valid content (any prompt with an answer)
            selected_prompts = member.get("selectedPrompts", [])
            answers = member.get("answers", {})
            
            if selected_prompts and isinstance(answers, dict):
                # Check if member has at least one prompt with an answer
                has_content = any(
                    isinstance(answers.get(p, {}), dict) and answers.get(p, {}).get("text")
                    for p in selected_prompts
                )
                if has_content:
                    selected_subjects.append(member)
                    used_subject_ids.add(member_id)
        
        # Validate we have exactly 10 unique subjects with valid content
        if len(selected_subjects) < 10:
            log.warning(f"Not enough members with valid content: {len(selected_subjects)} (need 10)")
            return []
        
        # Verify uniqueness
        subject_ids = [m.get("public_id") for m in selected_subjects]
        if len(subject_ids) != len(set(subject_ids)):
            log.error("Duplicate subject IDs detected! This should not happen.")
            return []
        
        log.info(f"Selected {len(selected_subjects)} unique subjects with valid content")
        
        # Split into guess-who (6) and two-truths-lie (4) subjects
        # Shuffle again to randomize which members go to which question type
        selected_subjects = GameService._shuffle_array(selected_subjects)
        guess_who_members = selected_subjects[:6]
        two_truths_members = selected_subjects[6:10]
        
        # Build member assignments (without pre-selecting prompts - OpenAI will choose)
        guess_who_assignments = []
        for member in guess_who_members:
            guess_who_assignments.append({
                "name": member.get("name"),
                "public_id": member.get("public_id"),
            })
        
        two_truths_assignments = []
        for member in two_truths_members:
            two_truths_assignments.append({
                "name": member.get("name"),
                "public_id": member.get("public_id"),
                "nickname": member.get("nickname"),
            })
        
        # Create context with ALL prompts/answers for each member
        # OpenAI will select the best prompt for each question type
        context_parts = []
        
        # Add guess-who members with all their prompts/answers
        for member in guess_who_members:
            name = member.get("name", "Unknown")
            selected_prompts = member.get("selectedPrompts", [])
            answers = member.get("answers", {})
            
            member_context = f"{name}:"
            if selected_prompts and isinstance(answers, dict):
                for prompt in selected_prompts:
                    answer_data = answers.get(prompt, {})
                    if isinstance(answer_data, dict):
                        answer_text = answer_data.get("text", "")
                        if answer_text:
                            # Truncate very long answers to save tokens
                            if len(answer_text) > 200:
                                answer_text = answer_text[:200] + "..."
                            member_context += f"\n  Q: {prompt}\n  A: {answer_text}"
            
            if member_context != f"{name}:":
                context_parts.append(member_context)
        
        # Add two-truths-lie members with all their prompts/answers
        for member in two_truths_members:
            name = member.get("name", "Unknown")
            selected_prompts = member.get("selectedPrompts", [])
            answers = member.get("answers", {})
            
            member_context = f"{name}:"
            if selected_prompts and isinstance(answers, dict):
                for prompt in selected_prompts:
                    answer_data = answers.get(prompt, {})
                    if isinstance(answer_data, dict):
                        answer_text = answer_data.get("text", "")
                        if answer_text:
                            # Truncate very long answers to save tokens
                            if len(answer_text) > 200:
                                answer_text = answer_text[:200] + "..."
                            member_context += f"\n  Q: {prompt}\n  A: {answer_text}"
            
            if member_context != f"{name}:":
                context_parts.append(member_context)
        
        full_context = "\n\n".join(context_parts)
        context_size = len(full_context)
        log.info(f"Full context with all prompts: {context_size} characters ({len(guess_who_members)} guess-who + {len(two_truths_members)} two-truths members)")
        
        # Store member assignments for later use in parsing (without pre-selected prompts)
        member_selections = {
            "guess_who": guess_who_assignments[:6],
            "two_truths_lie": two_truths_assignments[:4]
        }
        
        system_prompt = """Generate team-building game questions from member data. Be concise and creative.

IMPORTANT: For each member, you have access to multiple prompt/answer pairs. Select the BEST prompt/answer pair for each question type:
- Guess-who: Choose prompts that reveal interesting, distinctive traits or behaviors that make good "guess who" questions
- Two-truths-lie: Choose prompts that have interesting, believable content that can be rephrased as truths and used to create convincing lies

Rules:
- Guess-who: Synthesize info into creative questions (max 80 chars). Don't include names. Pick the most distinctive/interesting prompt for each person.
- Two-truths-lie: Rephrase 1 truth, create 2 believable lies (max 50 chars each). Add relevant emojis. Pick the most interesting prompt that will create engaging statements.
- Return JSON only with the exact structure specified.
- Include the exact prompt text and answer text you selected in your response."""

        user_prompt = f"""Data:
{full_context}

Generate 10 questions by selecting the BEST prompt/answer pair for each member:
- 6 guess-who questions (one per person from the first 6 members listed above)
- 4 two-truths-lie questions (one per person from the last 4 members listed above)

For each member, review ALL their available prompt/answer pairs and select the one that will create the most engaging question for that question type.

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
                        
                        # Log the structure of OpenAI response for debugging
                        log.info(f"[REQUEST_ID:{request_id}] OpenAI response structure: {list(parsed.keys())}")
                        if "guess_who" in parsed:
                            log.info(f"[REQUEST_ID:{request_id}] guess_who count: {len(parsed.get('guess_who', []))}")
                        if "two_truths_lie" in parsed:
                            log.info(f"[REQUEST_ID:{request_id}] two_truths_lie count: {len(parsed.get('two_truths_lie', []))}")
                        
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
        # Create lookup for member assignments (without pre-selected prompts - OpenAI chose them)
        guess_who_assignments_map = {a["name"]: a for a in member_selections.get("guess_who", [])}
        two_truths_assignments_map = {a["name"]: a for a in member_selections.get("two_truths_lie", [])}
        
        # Track used subject IDs to ensure uniqueness across all question types
        used_subject_ids = set()
        
        # Collect all subject IDs first (from both question types) to exclude from alternates
        all_subject_ids = set()
        for assignment in member_selections.get("guess_who", []):
            subject_id = assignment.get("public_id")
            if subject_id:
                all_subject_ids.add(subject_id)
        for assignment in member_selections.get("two_truths_lie", []):
            subject_id = assignment.get("public_id")
            if subject_id:
                all_subject_ids.add(subject_id)
        
        log.info(f"All subject IDs to exclude from alternates: {sorted(all_subject_ids)}")
        
        # Initialize usage tracker for alternates (to avoid repetition)
        alternate_usage: Dict[str, int] = {}
        if alternate_pool:
            log.info(f"Initializing alternate_usage tracker with {len(alternate_pool)} alternates")
            for alt in alternate_pool:
                alt_id = alt.get("public_id")
                if alt_id:
                    alternate_usage[alt_id] = 0
            log.info(f"Alternate pool IDs: {sorted([alt.get('public_id') for alt in alternate_pool])}")
        else:
            log.warning("No alternate_pool provided - will fall back to members list for distractors")
        
        # Process guess-who questions
        guess_who_data = parsed.get("guess_who", [])
        log.info(f"OpenAI returned {len(guess_who_data)} guess-who questions in response")
        if not guess_who_data:
            log.warning("No guess-who questions found in OpenAI response! Check OpenAI response structure.")
            log.warning(f"Available keys in parsed response: {list(parsed.keys())}")
        
        guess_who_processed = 0
        guess_who_skipped = 0
        for q_data in guess_who_data[:6]:  # Limit to 6
            member_name = q_data.get("member_name")
            member = member_map.get(member_name)
            assignment = guess_who_assignments_map.get(member_name)
            
            if not member or not assignment:
                log.warning(f"Member or assignment not found for guess-who: {member_name}")
                guess_who_skipped += 1
                continue
            
            # Ensure subject uniqueness - check if this member was already used
            member_id = member.get("public_id")
            if member_id in used_subject_ids:
                log.warning(f"Subject {member_name} (ID: {member_id}) already used in another question, skipping to maintain uniqueness")
                guess_who_skipped += 1
                continue
            
            # Mark this subject as used
            used_subject_ids.add(member_id)
            
            # Use the prompt/answer that OpenAI selected (from the response)
            # OpenAI chose the best prompt for this question type
            original_prompt = q_data.get("prompt", "")
            original_answer = q_data.get("answer", "")
            
            # If OpenAI didn't include prompt/answer in response, try to find it from member data
            if not original_prompt or not original_answer:
                selected_prompts = member.get("selectedPrompts", [])
                answers = member.get("answers", {})
                # Try to match based on the question content or use first available
                if selected_prompts and isinstance(answers, dict):
                    for prompt in selected_prompts:
                        answer_data = answers.get(prompt, {})
                        if isinstance(answer_data, dict) and answer_data.get("text"):
                            original_prompt = prompt
                            original_answer = answer_data.get("text", "")
                            break
            
            # Get distractors (prefer alternate pool, track usage to avoid repetition)
            # Exclude ALL subjects (not just this one) to prevent subjects from being alternates
            log.info(f"Getting distractors for guess-who question about {member.get('name')} (ID: {member_id})")
            log.info(f"  - alternate_pool provided: {alternate_pool is not None}, size: {len(alternate_pool) if alternate_pool else 0}")
            log.info(f"  - alternate_usage tracker size: {len(alternate_usage)}")
            log.info(f"  - all_subject_ids to exclude: {len(all_subject_ids)} subjects")
            distractors = GameService._get_random_distractors(
                members, member, 2, alternate_pool, alternate_usage, all_subject_ids
            )
            log.info(f"  - Got {len(distractors)} distractors: {[d.get('name') for d in distractors]}")
            if len(distractors) < 2:
                # If we can't get distractors, remove this subject from used set and skip
                used_subject_ids.discard(member_id)
                log.warning(f"Could not get 2 distractors for guess-who question about {member.get('name')}, skipping")
                guess_who_skipped += 1
                continue
            
            question_id = f"synthesized-{member.get('public_id')}-{int(time.time() * 1000)}-{random.random()}"
            
            # Build options array with correct answer and distractors
            options_array = [
                {
                    "id": member.get("public_id"),
                    "name": member.get("name"),
                    "avatar": member.get("profile_image")
                },
                *[{"id": m.get("public_id"), "name": m.get("name"), "avatar": m.get("profile_image")} for m in distractors]
            ]
            
            # Shuffle to randomize position of correct answer
            shuffled_options = GameService._shuffle_array(options_array)
            
            # Find the position of the correct answer after shuffling (0=left, 1=center, 2=right)
            correct_answer_position = next(
                (i for i, opt in enumerate(shuffled_options) if opt.get("id") == member.get("public_id")),
                -1
            )
            position_names = ["left", "center", "right"]
            position_name = position_names[correct_answer_position] if 0 <= correct_answer_position < 3 else "unknown"
            
            question = {
                "id": question_id,
                "type": "guess-who",
                "question": q_data.get("question", "").strip('"\''),
                "correctAnswer": member.get("name"),
                "correctAnswerId": member.get("public_id"),
                "options": shuffled_options,
                "promptText": original_prompt,
                "answerText": original_answer,
                "additionalInfo": f'{member.get("name")} said: "{original_prompt}: {original_answer}"'
            }
            questions.append(question)
            guess_who_processed += 1
            
            # Log question details for debugging
            distractor_names = [d.get("name") for d in distractors]
            distractor_ids = [d.get("public_id") for d in distractors]
            log.info(f"[QUESTION {len(questions)}] Type: guess-who | Subject: {member.get('name')} (ID: {member_id}) | Alternates: {distractor_names} (IDs: {distractor_ids}) | Correct answer position: {position_name} ({correct_answer_position})")
        
        log.info(f"Guess-who questions: {guess_who_processed} processed, {guess_who_skipped} skipped out of {len(guess_who_data)} received")
        
        # Process two-truths-lie questions
        two_truths_data = parsed.get("two_truths_lie", [])
        log.info(f"OpenAI returned {len(two_truths_data)} two-truths-lie questions in response")
        if not two_truths_data:
            log.warning("No two-truths-lie questions found in OpenAI response!")
        
        two_truths_processed = 0
        two_truths_skipped = 0
        for q_data in two_truths_data[:4]:  # Limit to 4
            member_name = q_data.get("member_name")
            member = member_map.get(member_name)
            assignment = two_truths_assignments_map.get(member_name)
            
            if not member or not assignment:
                log.warning(f"Member or assignment not found for two-truths-lie: {member_name}")
                two_truths_skipped += 1
                continue
            
            # Ensure subject uniqueness - check if this member was already used
            member_id = member.get("public_id")
            if member_id in used_subject_ids:
                log.warning(f"Subject {member_name} (ID: {member_id}) already used in another question, skipping to maintain uniqueness")
                two_truths_skipped += 1
                continue
            
            # Mark this subject as used
            used_subject_ids.add(member_id)
            
            # Use the prompt/answer that OpenAI selected (from the response)
            # OpenAI chose the best prompt for this question type
            original_prompt = q_data.get("prompt", "")
            original_answer = q_data.get("answer", "")
            
            # If OpenAI didn't include prompt/answer in response, try to find it from member data
            if not original_prompt or not original_answer:
                selected_prompts = member.get("selectedPrompts", [])
                answers = member.get("answers", {})
                # Try to match based on the question content or use first available
                if selected_prompts and isinstance(answers, dict):
                    for prompt in selected_prompts:
                        answer_data = answers.get(prompt, {})
                        if isinstance(answer_data, dict) and answer_data.get("text"):
                            original_prompt = prompt
                            original_answer = answer_data.get("text", "")
                            break
            
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
            two_truths_processed += 1
            
            # Log question details for debugging (two-truths-lie has no alternates, just statements)
            log.info(f"[QUESTION {len(questions)}] Type: two-truths-lie | Subject: {member.get('name')} (ID: {member_id}) | Alternates: N/A (statements only)")
        
        log.info(f"Two-truths-lie questions: {two_truths_processed} processed, {two_truths_skipped} skipped out of {len(two_truths_data)} received")
        
        # Final validation and comprehensive logging
        log.info("=" * 80)
        log.info("QUESTION GENERATION SUMMARY")
        log.info("=" * 80)
        
        subject_ids = []
        subject_names = []
        all_alternate_ids = []
        all_alternate_names = []
        
        for idx, q in enumerate(questions, 1):
            # For guess-who questions, correctAnswerId is the member's public_id
            # For two-truths-lie questions, correctAnswerId is "truth", so use memberPublicId
            if q.get("type") == "two-truths-lie":
                subject_id = q.get("memberPublicId")
                subject_name = q.get("memberNickname") or q.get("correctAnswer", "Unknown")
                alternates = []  # Two-truths-lie has no alternates
            else:
                subject_id = q.get("correctAnswerId")
                subject_name = q.get("correctAnswer", "Unknown")
                # Extract alternates from options (exclude the subject)
                options = q.get("options", [])
                alternates = [opt for opt in options if opt.get("id") != subject_id]
                alternate_ids = [alt.get("id") for alt in alternates]
                alternate_names = [alt.get("name") for alt in alternates]
                all_alternate_ids.extend(alternate_ids)
                all_alternate_names.extend(alternate_names)
            
            if subject_id:
                subject_ids.append(subject_id)
                subject_names.append(subject_name)
            
            # Log each question with full details
            if q.get("type") == "guess-who":
                log.info(f"Q{idx}: {q.get('type')} | Subject: {subject_name} (ID: {subject_id}) | Alternates: {alternate_names} (IDs: {alternate_ids})")
            else:
                log.info(f"Q{idx}: {q.get('type')} | Subject: {subject_name} (ID: {subject_id}) | Alternates: N/A")
        
        log.info("-" * 80)
        log.info(f"Total Questions: {len(questions)}")
        log.info(f"Unique Subjects: {len(set(subject_ids))} / {len(subject_ids)}")
        log.info(f"Subject Names: {subject_names}")
        log.info(f"Subject IDs: {subject_ids}")
        log.info(f"Total Alternates Used: {len(all_alternate_ids)}")
        log.info(f"Unique Alternates: {len(set(all_alternate_ids))} / {len(all_alternate_ids)}")
        log.info(f"Alternate Names: {all_alternate_names}")
        log.info(f"Alternate IDs: {all_alternate_ids}")
        
        # Check for duplicates
        if len(subject_ids) != len(set(subject_ids)):
            log.error(f"❌ DUPLICATE SUBJECTS DETECTED! Found {len(subject_ids)} questions but only {len(set(subject_ids))} unique subjects.")
            log.error(f"Duplicate subject IDs: {[sid for sid in subject_ids if subject_ids.count(sid) > 1]}")
        
        # Check if any subjects appear as alternates
        subject_ids_set = set(subject_ids)
        subjects_as_alternates = subject_ids_set.intersection(set(all_alternate_ids))
        if subjects_as_alternates:
            log.error(f"❌ SUBJECTS FOUND AS ALTERNATES! Subject IDs that appear as alternates: {list(subjects_as_alternates)}")
            # Find which questions have subjects as alternates
            for idx, q in enumerate(questions, 1):
                if q.get("type") == "guess-who":
                    options = q.get("options", [])
                    for opt in options:
                        if opt.get("id") in subjects_as_alternates:
                            log.error(f"  → Q{idx} has subject {opt.get('name')} (ID: {opt.get('id')}) as an alternate")
        else:
            log.info("✅ No subjects found as alternates - validation passed")
        
        if len(questions) < 10:
            log.warning(f"⚠️  Generated only {len(questions)} questions instead of 10. This may be due to duplicate subjects or missing content.")
        
        log.info("=" * 80)
        
        return questions
    
    @staticmethod
    def _get_random_distractors(
        members: List[Dict[str, Any]],
        exclude: Dict[str, Any],
        count: int,
        alternate_pool: Optional[List[Dict[str, Any]]] = None,
        usage_tracker: Optional[Dict[str, int]] = None,
        all_subject_ids: Optional[set] = None
    ) -> List[Dict[str, Any]]:
        """
        Get random distractors (other members) for a question.
        Prefers alternate_pool if provided, using usage_tracker to avoid repetition.
        Ensures distractors are unique within the question.
        Excludes ALL subjects (not just the current question's subject) to prevent subjects from being alternates.
        Falls back to members list if alternate_pool is not available or exhausted.
        """
        exclude_id = exclude.get("public_id")
        distractors: List[Dict[str, Any]] = []
        used_distractor_ids = set()  # Track IDs used in this specific question
        
        # Combine current exclude_id with all subject IDs to exclude
        excluded_ids = set()
        if exclude_id:
            excluded_ids.add(exclude_id)
        if all_subject_ids:
            excluded_ids.update(all_subject_ids)
        
        # Prefer alternate pool if available
        if alternate_pool and usage_tracker is not None:
            log.info(f"[_get_random_distractors] Using alternate_pool with {len(alternate_pool)} members, excluding {len(excluded_ids)} subject IDs")
            log.info(f"[_get_random_distractors] Excluded subject IDs: {sorted(excluded_ids)}")
            # Filter out ALL subjects (not just current exclude) and get available alternates
            available_alternates = [
                alt for alt in alternate_pool
                if alt.get("public_id") not in excluded_ids
                and alt.get("public_id") not in used_distractor_ids
            ]
            
            log.info(f"[_get_random_distractors] Found {len(available_alternates)} available alternates after filtering (excluded {len(excluded_ids)} subjects)")
            
            if len(available_alternates) < count:
                log.warning(f"[_get_random_distractors] Only {len(available_alternates)} available alternates, need {count} for question about {exclude.get('name', 'Unknown')}")
                log.warning(f"[_get_random_distractors] Excluded IDs: {sorted(excluded_ids)}")
                alternate_pool_ids = [alt.get("public_id") for alt in alternate_pool]
                log.warning(f"[_get_random_distractors] Alternate pool IDs ({len(alternate_pool_ids)} total): {sorted(alternate_pool_ids)}")
                available_ids = [alt.get("public_id") for alt in available_alternates]
                log.warning(f"[_get_random_distractors] Available alternate IDs: {sorted(available_ids)}")
            
            # Sort by usage count (ascending) to prefer least-used alternates
            available_alternates.sort(key=lambda alt: usage_tracker.get(alt.get("public_id", ""), 0))
            
            # Select up to count distinct alternates (unique within this question)
            selected_alternates = []
            for alt in available_alternates:
                if len(selected_alternates) >= count:
                    break
                alt_id = alt.get("public_id")
                if alt_id and alt_id not in used_distractor_ids:
                    selected_alternates.append(alt)
                    used_distractor_ids.add(alt_id)
                    # Increment usage count
                    usage_tracker[alt_id] = usage_tracker.get(alt_id, 0) + 1
            
            log.info(f"[_get_random_distractors] Selected {len(selected_alternates)} alternates from alternate pool: {[alt.get('name') for alt in selected_alternates]}")
            
            # Convert alternate format to match expected format (with profile_image)
            for alt in selected_alternates:
                distractors.append({
                    "public_id": alt.get("public_id"),
                    "name": alt.get("name"),
                    "profile_image": alt.get("wave_gif_url")  # Use wave_gif_url as avatar fallback
                })
        else:
            log.warning(f"[_get_random_distractors] Not using alternate_pool: alternate_pool={alternate_pool is not None}, usage_tracker={usage_tracker is not None}")
            if alternate_pool is None:
                log.warning(f"[_get_random_distractors] alternate_pool is None!")
            if usage_tracker is None:
                log.warning(f"[_get_random_distractors] usage_tracker is None!")
        
        # If we still need more distractors, fall back to members list
        if len(distractors) < count:
            available_members = [
                m for m in members
                if m.get("public_id") not in excluded_ids
                and m.get("public_id") not in used_distractor_ids
                and not any(d.get("public_id") == m.get("public_id") for d in distractors)
            ]
            random.shuffle(available_members)
            needed = count - len(distractors)
            for member in available_members[:needed]:
                member_id = member.get("public_id")
                if member_id and member_id not in used_distractor_ids:
                    distractors.append({
                        "public_id": member_id,
                        "name": member.get("name"),
                        "profile_image": member.get("profile_image")
                    })
                    used_distractor_ids.add(member_id)
        
        # Final validation: ensure all distractors are unique
        distractor_ids = [d.get("public_id") for d in distractors if d.get("public_id")]
        if len(distractor_ids) != len(set(distractor_ids)):
            log.warning(f"Duplicate distractor IDs detected! Removing duplicates.")
            # Remove duplicates, keeping first occurrence
            seen = set()
            unique_distractors = []
            for d in distractors:
                d_id = d.get("public_id")
                if d_id and d_id not in seen:
                    unique_distractors.append(d)
                    seen.add(d_id)
            distractors = unique_distractors
        
        return distractors[:count]
    
    @staticmethod
    def _shuffle_array(array: List[Any]) -> List[Any]:
        """Shuffle an array in place and return it"""
        shuffled = array.copy()
        random.shuffle(shuffled)
        return shuffled
    
    @staticmethod
    def _balanced_shuffle_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Shuffle questions using balanced distribution algorithm to prevent clustering.
        
        This algorithm ensures questions are evenly spaced based on their type ratio,
        preventing consecutive questions of the same type from clustering together.
        
        Args:
            questions: List of question dictionaries with 'type' field
            
        Returns:
            Shuffled list with balanced distribution of question types
        """
        if len(questions) <= 1:
            return questions.copy()
        
        def type_func(item: Dict[str, Any]) -> str:
            """Return 'T' for two-truths-lie, 'G' for guess-who"""
            return 'T' if item.get("type") == "two-truths-lie" else 'G'
        
        # Step 1: Separate and shuffle by type
        T_items = [x for x in questions if type_func(x) == 'T']
        G_items = [x for x in questions if type_func(x) == 'G']
        
        random.shuffle(T_items)
        random.shuffle(G_items)
        
        nT = len(T_items)
        nG = len(G_items)
        N = nT + nG
        
        # Step 2: Build evenly spaced T-pattern
        pattern = []
        prev_floor = 0
        for k in range(1, N + 1):
            cur_floor = (k * nT) // N  # floor division
            if cur_floor > prev_floor:
                pattern.append('T')
            else:
                pattern.append('G')
            prev_floor = cur_floor
        
        # Step 3: Random rotation of the pattern
        offset = random.randint(0, N - 1)
        rotated_pattern = [pattern[(i + offset) % N] for i in range(N)]
        
        # Step 4: Fill with shuffled items
        result = []
        t_idx = 0
        g_idx = 0
        for kind in rotated_pattern:
            if kind == 'T':
                result.append(T_items[t_idx])
                t_idx += 1
            else:
                result.append(G_items[g_idx])
                g_idx += 1
        
        log.info(f"Balanced shuffle: {nT} two-truths-lie, {nG} guess-who questions distributed")
        return result