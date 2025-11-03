"""
Utility functions for generating PostgreSQL full-text search vectors from user data.
"""
import json
from typing import Optional, Dict, List, Any
from sqlalchemy import text


def generate_search_text_from_user(user) -> str:
    """
    Generate a concatenated searchable text string from all user data fields.
    
    This function aggregates text from:
    - name, role, location, nickname, greeting, hi_yall_text, pronunciation_text
    - selected_prompts (array of prompt questions)
    - answers (dict of prompt -> answer pairs, extracting text fields)
    - bento_widgets (extracting any text content)
    
    Args:
        user: WelcomepageUser model instance
        
    Returns:
        String containing all searchable text, space-separated
    """
    search_parts = []
    
    # Basic text fields
    if user.name:
        search_parts.append(user.name)
    if user.role:
        search_parts.append(user.role)
    if user.location:
        search_parts.append(user.location)
    if user.nickname:
        search_parts.append(user.nickname)
    if user.greeting:
        search_parts.append(user.greeting)
    if user.hi_yall_text:
        search_parts.append(user.hi_yall_text)
    if user.pronunciation_text:
        search_parts.append(user.pronunciation_text)
    
    # Selected prompts (array of prompt question strings)
    if user.selected_prompts:
        if isinstance(user.selected_prompts, list):
            search_parts.extend(user.selected_prompts)
        elif isinstance(user.selected_prompts, str):
            try:
                prompts = json.loads(user.selected_prompts)
                if isinstance(prompts, list):
                    search_parts.extend(prompts)
            except (json.JSONDecodeError, TypeError):
                pass
    
    # Answers (dict: prompt -> {text, image, specialData})
    if user.answers:
        answers_dict = user.answers
        if isinstance(answers_dict, str):
            try:
                answers_dict = json.loads(answers_dict)
            except (json.JSONDecodeError, TypeError):
                answers_dict = {}
        
        if isinstance(answers_dict, dict):
            for prompt, answer in answers_dict.items():
                # Add the prompt question itself
                if prompt and isinstance(prompt, str):
                    search_parts.append(prompt)
                
                # Extract text from answer
                if isinstance(answer, dict):
                    answer_text = answer.get('text', '')
                    if answer_text and isinstance(answer_text, str):
                        search_parts.append(answer_text)
                    
                    # Extract text from specialData if it's a string or contains strings
                    special_data = answer.get('specialData')
                    if special_data:
                        special_text = extract_text_from_special_data(special_data)
                        if special_text:
                            search_parts.append(special_text)
                elif isinstance(answer, str):
                    search_parts.append(answer)
    
    # Bento widgets (array of widget configs)
    if user.bento_widgets:
        widgets = user.bento_widgets
        if isinstance(widgets, str):
            try:
                widgets = json.loads(widgets)
            except (json.JSONDecodeError, TypeError):
                widgets = []
        
        if isinstance(widgets, list):
            for widget in widgets:
                if isinstance(widget, dict):
                    # Extract text fields from widget config
                    widget_text = extract_text_from_dict(widget)
                    if widget_text:
                        search_parts.append(widget_text)
    
    # Join all parts with spaces and normalize
    search_text = ' '.join(search_parts)
    
    # Remove extra whitespace
    search_text = ' '.join(search_text.split())
    
    return search_text


def extract_text_from_special_data(data: Any) -> str:
    """
    Recursively extract text from specialData structures.
    
    Args:
        data: Can be dict, list, or string
        
    Returns:
        Concatenated string of all text values found
    """
    texts = []
    
    if isinstance(data, str):
        texts.append(data)
    elif isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, (dict, list)):
                nested_text = extract_text_from_special_data(value)
                if nested_text:
                    texts.append(nested_text)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, (dict, list)):
                nested_text = extract_text_from_special_data(item)
                if nested_text:
                    texts.append(nested_text)
    
    return ' '.join(texts)


def extract_text_from_dict(d: Dict[str, Any]) -> str:
    """
    Extract all string values from a dictionary recursively.
    
    Args:
        d: Dictionary to extract text from
        
    Returns:
        Concatenated string of all text values
    """
    texts = []
    
    for key, value in d.items():
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            nested_text = extract_text_from_dict(value)
            if nested_text:
                texts.append(nested_text)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict):
                    nested_text = extract_text_from_dict(item)
                    if nested_text:
                        texts.append(nested_text)
    
    return ' '.join(texts)


def update_search_vector(db, user):
    """
    Update the search_vector column for a user by generating search text
    and converting it to a tsvector.
    
    This should be called whenever user data changes.
    
    Args:
        db: SQLAlchemy database session
        user: WelcomepageUser model instance (must be in the session)
    """
    from sqlalchemy import text
    
    search_text = generate_search_text_from_user(user)
    
    # Use PostgreSQL's to_tsvector function to create the search vector
    # Using 'english' language config for stemming
    # Handle empty search text by using empty string
    if not search_text or not search_text.strip():
        search_text = ""
    
    db.execute(
        text("""
            UPDATE welcomepage_users 
            SET search_vector = to_tsvector('english', :search_text)
            WHERE id = :user_id
        """),
        {"search_text": search_text, "user_id": user.id}
    )
    
    # Refresh the user object to get the updated search_vector
    db.refresh(user)

