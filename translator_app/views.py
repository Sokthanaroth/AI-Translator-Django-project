import os
import re
from groq import Groq
from deep_translator import GoogleTranslator
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import get_valid_filename
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import TranslationHistory
from django.core.files.storage import default_storage
from PyPDF2 import PdfReader
from docx import Document
from decouple import config

# Configure Groq (used for grammar, improve, tone — English only)
GROQ_API_KEY = config('GROQ_API_KEY', default=None)
MODEL_NAME = 'llama-3.1-8b-instant'


def get_groq_client():
    if not GROQ_API_KEY:
        raise RuntimeError('GROQ_API_KEY environment variable is required for AI requests')
    return Groq(api_key=GROQ_API_KEY)

def generate_ai_response(prompt):
    client = get_groq_client()
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content

def is_khmer(text):
    """Detect if text contains Khmer characters."""
    khmer_pattern = re.compile(r'[\u1780-\u17FF]')
    return bool(khmer_pattern.search(text))

def google_translate(text):
    """Translate between English and Khmer using Google Translate.
    Auto-detects the input language. Falls back to Groq AI if Google Translate fails."""
    source = 'km' if is_khmer(text) else 'en'
    target = 'en' if source == 'km' else 'km'

    def _translate_chunk(chunk):
        """Translate a single chunk, with Groq AI fallback."""
        try:
            result = GoogleTranslator(source=source, target=target).translate(chunk)
            if not result or not result.strip():
                raise ValueError("Empty translation returned")
            return result
        except Exception:
            # Fallback: use Groq AI for translation
            try:
                lang_name = 'Khmer' if target == 'km' else 'English'
                prompt = f"Translate the following text to {lang_name}. Return ONLY the translated text, nothing else:\n\n{chunk}"
                return generate_ai_response(prompt)
            except Exception:
                return chunk  # Last resort: return original text

    # Google Translate has a ~5000 char limit per request, so chunk large texts
    MAX_CHUNK = 4500
    if len(text) <= MAX_CHUNK:
        return _translate_chunk(text)

    # Split by paragraphs to preserve formatting
    paragraphs = text.split('\n')
    translated_parts = []
    current_chunk = ''

    for para in paragraphs:
        if len(current_chunk) + len(para) + 1 > MAX_CHUNK and current_chunk:
            translated_parts.append(_translate_chunk(current_chunk))
            current_chunk = para
        else:
            current_chunk = current_chunk + '\n' + para if current_chunk else para

    if current_chunk:
        translated_parts.append(_translate_chunk(current_chunk))

    return '\n'.join(translated_parts)

def index(request):
    return render(request, 'translator_app/index.html')

@api_view(['POST'])
def process_text(request):
    mode = request.data.get('mode')
    text = request.data.get('text')
    target_lang = request.data.get('target_language', 'English')
    tone = request.data.get('tone', 'Friendly')
    
    if not text:
        return Response({'error': 'No text provided'}, status=400)
        
    try:
        explanation_val = ""
        result_val = ""

        # --- TRANSLATE: Uses Google Translate (fast & accurate) ---
        if mode == 'translate':
            result_val = google_translate(text)
            
        # --- GRAMMAR / IMPROVE / TONE: Uses Groq AI (English only) ---
        elif mode == 'grammar':
            if not GROQ_API_KEY:
                return Response({'error': 'AI service unavailable. Set GROQ_API_KEY in your environment.'}, status=503)

            if is_khmer(text):
                return Response({'result': 'Error: Fix Grammar only supports English text. Please use the Translate feature for Khmer.', 'explanation': ''})

            prompt = f"""You are an expert English grammar editor. Fix the grammar of the following English text and explain your corrections.

Output your answer EXACTLY in this format:

Fixed:
[The corrected English text here]

Explanation:
[Bullet points explaining each correction]

Text to fix:
{text}"""
            resp_text = generate_ai_response(prompt)
            try:
                parts = resp_text.split("Explanation:")
                result_val = parts[0].replace("Fixed:", "").strip()
                explanation_val = "Explanation:" + parts[1].strip() if len(parts) > 1 else ""
            except:
                result_val = resp_text
                explanation_val = "Could not parse explanation."
            
        elif mode == 'improve':
            if not GROQ_API_KEY:
                return Response({'error': 'AI service unavailable. Set GROQ_API_KEY in your environment.'}, status=503)

            if is_khmer(text):
                return Response({'result': 'Error: Improve Writing only supports English text. Please use the Translate feature for Khmer.', 'explanation': ''})

            prompt = f"Improve the following English text to sound highly professional, polite, and well-written. Just provide the improved text and nothing else:\n\n{text}"
            resp_text = generate_ai_response(prompt)
            result_val = resp_text.strip()
            explanation_val = 'Text has been professionally enhanced.'
            
        elif mode == 'tone':
            if not GROQ_API_KEY:
                return Response({'error': 'AI service unavailable. Set GROQ_API_KEY in your environment.'}, status=503)

            if is_khmer(text):
                return Response({'result': 'Error: Tone Adjustment only supports English text. Please use the Translate feature for Khmer.', 'explanation': ''})

            prompt = f"Rewrite the following English text so that it sounds strictly {tone}. Just provide the rewritten text and nothing else:\n\n{text}"
            resp_text = generate_ai_response(prompt)
            result_val = resp_text.strip()
            explanation_val = f'Tone adjusted to {tone}.'
            
        else:
            return Response({'error': 'Invalid mode'}, status=400)
            
        # Save to history
        TranslationHistory.objects.create(
            mode=mode,
            source_text=text,
            result_text=result_val,
            explanation=explanation_val
        )

        return Response({'result': result_val, 'explanation': explanation_val})            

    except Exception as e:
        error_msg = str(e)
        if '429' in error_msg:
            # We hit the rate limit! Let's extract how long to wait.
            import re
            wait_time = 60 # Default to 60 seconds
            match = re.search(r'Please retry in ([\d\.]+)s', error_msg)
            if match:
                wait_time = int(float(match.group(1))) + 1 # Add 1 second to be safe
                
            return Response({
                'error': 'rate_limit',
                'wait_seconds': wait_time,
                'message': f'AI is taking a breather! Automatically retrying in {wait_time} seconds...'
            }, status=429)
            
        return Response({'error': error_msg}, status=500)

@api_view(['GET', 'DELETE'])
def get_history(request):
    if request.method == 'DELETE':
        TranslationHistory.objects.all().delete()
        return Response({'success': True})

    history = TranslationHistory.objects.all().order_by('-created_at')[:20]  # Get last 20
    data = []
    for item in history:
        local_time = timezone.localtime(item.created_at)
        data.append({
            'id': item.id,
            'mode': item.mode,
            'source_text': item.source_text,
            'result_text': item.result_text,
            'explanation': item.explanation,
            'created_at': local_time.strftime("%Y-%m-%d %H:%M")
        })
    return Response(data)

@api_view(['DELETE'])
def delete_history(request, item_id):
    try:
        item = TranslationHistory.objects.get(id=item_id)
        item.delete()
        return Response({'success': True})
    except TranslationHistory.DoesNotExist:
        return Response({'error': 'Item not found'}, status=404)
    except Exception as e:
        return Response({'error': str(e)}, status=500)

@api_view(['POST'])
def upload_file(request):
    if 'file' not in request.FILES:
        return Response({'error': 'No file provided'}, status=400)
    
    uploaded_file = request.FILES['file']
    
    # Check file size (max 20MB)
    if uploaded_file.size > 20 * 1024 * 1024:
        return Response({'error': 'File size exceeds 20MB limit'}, status=400)
    
    # Check file extension
    allowed_extensions = ['.txt', '.doc', '.docx', '.pdf', '.png', '.jpg', '.jpeg']
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in allowed_extensions:
        return Response({'error': f'File type not allowed. Allowed types: {", ".join(allowed_extensions)}'}, status=400)
    if ext == '.doc':
        return Response({'error': 'DOC files are currently not supported for text extraction. Please upload .txt, .pdf, .docx, or images.'}, status=400)

    safe_filename = get_valid_filename(os.path.basename(uploaded_file.name))
    stored_path = f'uploads/{safe_filename}'

    try:
        uploaded_file.seek(0)
        file_path = default_storage.save(stored_path, uploaded_file)
        file_url = default_storage.url(file_path)

        uploaded_file.seek(0)
        content = ''
        if ext == '.txt':
            content = uploaded_file.read().decode('utf-8', errors='replace')
        elif ext == '.pdf':
            try:
                reader = PdfReader(uploaded_file)
                content = '\n'.join((page.extract_text() or '') for page in reader.pages)
            except Exception as pdf_error:
                return Response({'error': f'Unable to extract text from PDF: {pdf_error}'}, status=400)
        elif ext == '.docx':
            try:
                document = Document(uploaded_file)
                content = '\n'.join(paragraph.text for paragraph in document.paragraphs)
            except Exception as docx_error:
                return Response({'error': f'Unable to extract text from DOCX: {docx_error}'}, status=400)
        elif ext == '.doc':
            return Response({'error': 'DOC files are currently not supported for text extraction. Please upload .txt, .pdf, .docx, or images.'}, status=400)
        elif ext in ['.png', '.jpg', '.jpeg']:
            import base64
            file_bytes = uploaded_file.read()
            base64_image = base64.b64encode(file_bytes).decode('utf-8')
            image_format = "jpeg" if ext in [".jpg", ".jpeg"] else "png"
            
            try:
                client = get_groq_client()
                completion = client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Extract all the text from this image. Only return the extracted text, do not add any extra comments or introduction."
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/{image_format};base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ],
                    temperature=0.1,
                )
                content = completion.choices[0].message.content.strip()
                if not content:
                    return Response({'error': 'Could not find any readable text in this image.'}, status=400)
            except Exception as vision_error:
                return Response({'error': f'Unable to extract text from image: {vision_error}'}, status=400)

        return Response({
            'success': True,
            'text': content
        })
    except Exception as e:
        return Response({'error': str(e)}, status=500)
