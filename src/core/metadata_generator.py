from openai import OpenAI
import re
import json

def generate_metadata(api_key, transcript, video_path, duration_func):
    """Génère les métadonnées optimisées"""
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
    duration_sec = duration_func(video_path)
    duration_min = duration_sec / 60
    
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{
            "role": "user",
            "content": f"""
            Transcription: {transcript[:2000]}
            Durée: {duration_min:.1f} minutes
            
            Génère un titre en MAJUSCULES, description courte avec max 3 hashtags,
            et chapitres si durée >5 min. Format JSON:
            {{
                "title": "...",
                "description": "...",
                "manualChapters": ["00:00 - Chap1"],
                "disableAutoChapters": true/false
            }}
            """
        }],
        response_format={"type": "json_object"},
        max_tokens=800
    )
    
    metadata = json.loads(response.choices[0].message.content)
    metadata["title"] = metadata["title"].upper()
    
    # Limiter les hashtags
    desc = metadata["description"]
    hashtags = re.findall(r'#\w+', desc)
    if len(hashtags) > 3:
        metadata["description"] = re.sub(r'(#\w+\s*){4,}', ' '.join(hashtags[:3]), desc)
    
    return metadata