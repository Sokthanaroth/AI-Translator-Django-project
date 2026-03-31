import os
try:
    import google.generativeai as genai
except ModuleNotFoundError:
    genai = None
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

# Configure Google Gemini
GOOGLE_API_KEY = config('GOOGLE_API_KEY', default=None)
MODEL_NAME = 'gemini-flash-latest'


def get_gemini_client():
    if genai is None:
        raise RuntimeError('google-generativeai is not installed. Install it with: pip install google-generativeai')
    if not GOOGLE_API_KEY:
        raise RuntimeError('GOOGLE_API_KEY environment variable is required for AI requests')
    genai.configure(api_key=GOOGLE_API_KEY)
    return genai.GenerativeModel(MODEL_NAME)

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

        if not GOOGLE_API_KEY:
            return Response({'error': 'AI service unavailable. Set GOOGLE_API_KEY in your environment.'}, status=503)

        model = get_gemini_client()
        if mode == 'translate':
            prompt = f"Translate the following text to {target_lang}. Just provide the exact translation and nothing else:\n\n{text}"
            response = model.generate_content(prompt)
            result_val = response.text.strip()
            
        elif mode == 'grammar':
            prompt = f"""You are an expert grammar editor. Fix the following text and explain your corrections. VERY IMPORTANT: You must reply in the exact same language as the input text (if the input is in Khmer, your fixes and explanations MUST be in Khmer). Output your answer EXACTLY in this format:

Fixed:
[The fixed text here]

Explanation:
[Bullet points of explanations here]

Text to fix:
{text}"""
            response = model.generate_content(prompt)
            resp_text = response.text
            try:
                parts = resp_text.split("Explanation:")
                result_val = parts[0].replace("Fixed:", "").strip()
                explanation_val = "Explanation:" + parts[1].strip() if len(parts) > 1 else ""
            except:
                result_val = resp_text
                explanation_val = "Could not parse explanation."
            
        elif mode == 'improve':
            prompt = f"Improve the following text to sound highly professional, polite, and well-written. VERY IMPORTANT: Maintain the EXACT SAME language as the original text (e.g. if the input is Khmer, the output must be Khmer). Just provide the improved text:\n\n{text}"
            response = model.generate_content(prompt)
            result_val = response.text.strip()
            explanation_val = 'Text has been professionally enhanced.'
            
        elif mode == 'tone':
            prompt = f"Rewrite the following text so that it sounds strictly {tone}. VERY IMPORTANT: Maintain the EXACT SAME language as the original text (e.g. if the input is Khmer, the output must be Khmer). Just provide the rewritten text:\n\n{text}"
            response = model.generate_content(prompt)
            result_val = response.text.strip()
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
    
    # Check file size (max 5MB)
    if uploaded_file.size > 5 * 1024 * 1024:
        return Response({'error': 'File size exceeds 5MB limit'}, status=400)
    
    # Check file extension
    allowed_extensions = ['.txt', '.doc', '.docx', '.pdf']
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in allowed_extensions:
        return Response({'error': f'File type not allowed. Allowed types: {", ".join(allowed_extensions)}'}, status=400)
    if ext == '.doc':
        return Response({'error': 'DOC files are currently not supported for text extraction. Please upload .txt, .pdf, or .docx.'}, status=400)

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
            return Response({'error': 'DOC files are currently not supported for text extraction. Please upload .txt, .pdf, or .docx.'}, status=400)

        return Response({
            'success': True,
            'filename': safe_filename,
            'file_path': file_path,
            'file_url': file_url,
            'text': content
        })
    except Exception as e:
        return Response({'error': str(e)}, status=500)
