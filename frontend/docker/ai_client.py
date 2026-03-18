import httpx
import structlog
import os
from typing import Tuple, Optional, Any
from utils import normalize_language_name, get_iso_language_code, encode_image_to_base64
from constants import DEFAULTS

logger = structlog.get_logger(__name__)

def _get_api_url(base_url: str, suffix: str = "/v1/chat/completions") -> str:
    """Helper to construct API URL with proper suffix."""
    base = base_url.rstrip('/')
    if not base.endswith(suffix):
        # Handle cases where /v1/ might already be in the URL but not the full endpoint
        if "/v1/" in base:
            return f"{base}{suffix.replace('/v1/', '/')}"
        return f"{base}{suffix}"
    return base

async def check_model(
    model_type: str, 
    url: str, 
    token: str, 
    model_name: Optional[str] = None
) -> Tuple[bool, str]:
    """Generic health check for model APIs."""
    if not url:
        return False, f"{model_type.capitalize()} URL is not configured"

    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        base_url = url.rstrip('/')
        logger.info("checking_model_health", type=model_type, url=base_url)

        if model_type == "medgemma" or model_type == "triage": # triage/medgemma are same
             return await check_triage_model(url, token, model_name)
        
        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.get(f"{base_url}/v1/models", headers=headers, timeout=10.0)
            if response.status_code == 200:
                data = response.json().get('data', [])
                if not data:
                    return False, f"{model_type.capitalize()} API returned empty models list"
                
                if model_name:
                    model_ids = [m['id'] for m in data]
                    if model_name in model_ids:
                        return True, f"{model_type.capitalize()} API is available and responding"
                    else:
                        return False, f"Model '{model_name}' not found in {model_type.capitalize()} API"
                return True, f"{model_type.capitalize()} API is available and responding"
            else:
                return False, f"{model_type.capitalize()} API returned status: {response.status_code}"                

    except Exception as e:
        logger.error("model_check_failed", error=str(e), model_type=model_type)
        return False, f"{model_type.capitalize()} API error: {str(e)}"

async def check_triage_model(
    url: str, 
    token: Optional[str] = None,
    model_name: Optional[str] = None
) -> Tuple[bool, str]:
    """Health check specifically for MedGemma model."""
    try:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        payload = {
            "model": model_name or DEFAULTS['medgemma']['model'],
            "messages": [
                {"role": "system", "content": "You are an elite radiologist."},
                {"role": "user", "content": [{"type": "text", "text": "Hello"}]}
            ],
            "max_tokens": 10,
            "temperature": 0.1
        }
        
        api_url = _get_api_url(url)
        logger.info("checking_medgemma_health", url=api_url, model=payload["model"])
        
        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(api_url, headers=headers, json=payload, timeout=10.0)
            logger.info("medgemma_health_response", status=response.status_code)
            if response.status_code == 200:
                return True, "MedGemma API is available and responding"
            else:
                return False, f"MedGemma API returned status: {response.status_code}: {response.text[:100]}"
                
    except Exception as e:
        logger.error("medgemma_check_failed", error=str(e))
        return False, f"MedGemma API error: {str(e)}"

async def transcribe_audio(
    audio_path: str, 
    auto_detect: bool, 
    expected_language: str, 
    whisper_url: str, 
    whisper_token: str, 
    model_name: Optional[str] = None
) -> Tuple[str, str]:
    """Transcribe audio using Whisper API."""
    if not whisper_url:
        return "Unset", "Whisper URL not configured"

    try:
        headers = {"Authorization": f"Bearer {whisper_token}"} if whisper_token else {}
        
        with open(audio_path, 'rb') as f:
            files = {'file': (os.path.basename(audio_path), f, 'audio/wav')}
            if model_name:
                files['model'] = (None, model_name)
            else:
                files['model'] = (None, DEFAULTS['whisper']['model'])
                
            files['task'] = (None, "transcribe")

            if not auto_detect:
                files['language'] = (None, get_iso_language_code(expected_language))
            
            api_url = f"{whisper_url.rstrip('/')}/v1/audio/transcriptions"
            logger.info("requesting_transcription", url=api_url)
            async with httpx.AsyncClient(verify=False) as client_http:
                response = await client_http.post(
                    api_url,
                    headers=headers, 
                    files=files,
                    timeout=300.0
                )
        
        if response.status_code == 200:
            result = response.json()
            det_lang = result.get('language') or result.get('detected_language') or 'Unknown'
            text = result.get('text', '')
            return normalize_language_name(det_lang), text
        else:
            logger.error("transcription_api_failed", status=response.status_code, text=response.text[:200])
            return "Unset", f"Transcription failed ({response.status_code})"
            
    except Exception as e:
        logger.error("transcription_exception", error=str(e))
        return "Unset", f"Error: {str(e)}"

async def translate_text(
    text: str, 
    source_lang: str, 
    target_lang: str, 
    translategemma_url: str, 
    translategemma_token: Optional[str] = None,
    model_name: Optional[str] = None
) -> str:
    """Translate text using TranslateGemma API."""
    if not translategemma_url or not text.strip():
        return text

    try:
        headers = {"Content-Type": "application/json"}
        if translategemma_token:
            headers["Authorization"] = f"Bearer {translategemma_token}"
        
        s_lang_name = normalize_language_name(source_lang)
        t_lang_name = normalize_language_name(target_lang)
        
        system_msg = (
            f"You are a professional {s_lang_name} ({source_lang}) to {t_lang_name} ({target_lang}) translator. "
            f"Produce only the {t_lang_name} translation. \n\n{text}"
        )

        payload = {
            "model": model_name or DEFAULTS['translategemma']['model'],
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": [{"type": "text", "text": text}]}
            ],
            "max_tokens": 2048,
            "temperature": 0.1
        }
        
        api_url = _get_api_url(translategemma_url)
        logger.info("requesting_translation", url=api_url, model=payload["model"])

        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(api_url, headers=headers, json=payload, timeout=300.0)
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content'] if 'choices' in result else str(result)
        
        logger.error("translation_api_failed", status=response.status_code)
        return f"Translation failed: {response.status_code}"
            
    except Exception as e:
        logger.error("translation_exception", error=str(e))
        return f"Error: {str(e)}"

async def analyze_xray_with_medgemma(
    image_path: str, 
    medgemma_url: str, 
    medgemma_token: Optional[str] = None, 
    model_name: Optional[str] = None
) -> str:
    """Analyze X-ray image using MedGemma."""
    if not medgemma_url:
        return "MedGemma URL not configured"

    try:
        ext = os.path.splitext(image_path)[1].lower().lstrip('.')
        mime_type = f"image/{ext}" if ext in ['png', 'jpeg', 'jpg', 'webp'] else "image/png"
        if ext == 'jpg': mime_type = "image/jpeg"
        
        base64_image = encode_image_to_base64(image_path)
        logger.info("requesting_xray_analysis", path=image_path)
        
        headers = {"Content-Type": "application/json"}
        if medgemma_token:
            headers["Authorization"] = f"Bearer {medgemma_token}"
        
        prompt = "Analyze this X-ray image. Provide a structured analysis."
        payload = {
            "model": model_name or DEFAULTS['medgemma']['model'],
            "messages": [
                {"role": "system", "content": "You are an expert radiologist."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 1000,
            "temperature": 0.1
        }
        
        api_url = _get_api_url(medgemma_url)
        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(api_url, headers=headers, json=payload, timeout=120.0)
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            
            logger.error("xray_analysis_failed", status=response.status_code)
            return f"Error: status {response.status_code}"
                
    except Exception as e:
        logger.error("xray_analysis_exception", error=str(e))
        return f"Error: {str(e)}"

async def analyze_text_with_medgemma(
    text: str, 
    medgemma_url: str, 
    medgemma_token: Optional[str] = None, 
    model_name: Optional[str] = None
) -> str:
    """Analyze medical text/notes using MedGemma."""
    if not medgemma_url:
        return "MedGemma URL not configured"

    try:
        headers = {"Content-Type": "application/json"}
        if medgemma_token:
            headers["Authorization"] = f"Bearer {medgemma_token}"
        
        sys_prompt = (
            "You are a highly skilled medical diagnostician. "
            "Analyze clinical notes and provide a structured diagnosis in JSON format. "
            "The JSON MUST include these keys: "
            "patient_name, date_of_birth (YYYY-MM-DD), visit_time (YYYY-MM-DD HH:MM:SS), "
            "severity (Mild, Moderate, Severe, or Critical), primary_diagnosis, "
            "secondary_diagnoses, recommended_tests, recommended_treatment, follow_up, medical_reasoning. "
            "Return ONLY the raw JSON object without any markdown formatting or explanation."
        )
        payload = {
            "model": model_name or DEFAULTS['medgemma']['model'],
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"Analyze these notes and return JSON: {text}"}
            ],
            "max_tokens": 1024,
            "temperature": 0.1
        }
        
        api_url = _get_api_url(medgemma_url)
        logger.info("requesting_text_analysis", url=api_url, model=payload["model"])
        async with httpx.AsyncClient(verify=False) as client_http:
            response = await client_http.post(api_url, headers=headers, json=payload, timeout=120.0)
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            
            logger.error("text_analysis_failed", status=response.status_code)
            return f"Error: status {response.status_code}"
                
    except Exception as e:
        logger.error("text_analysis_exception", error=str(e))
        return f"Error: {str(e)}"
