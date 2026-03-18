import os
import asyncio
import logging
import structlog
import urllib3
import gradio as gr
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
from dotenv import load_dotenv

import ai_client
import db_client
from constants import LANGUAGES, DEFAULTS
from config_manager import load_config, save_config
from utils import (
    get_iso_language_code, 
    normalize_language_name, 
    check_logo_exists, 
    encode_image_to_base64
)

# Load environment variables
load_dotenv()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger(__name__)

# Disable SSL warnings for self-signed certificates in local/demo environments
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

APP_DIR = Path(__file__).parent

# Theme configuration
hpe_theme = gr.themes.Soft(
    primary_hue="emerald",
    neutral_hue="slate",
).set(
    body_background_fill="#f8fafc",
    body_text_color="#1e293b",
    block_title_text_color="#1e293b",
    block_label_text_color="#475569",
    input_background_fill="#ffffff",
)

def is_configured(url: Any) -> bool:
    """Check if a URL is configured."""
    return bool(url and str(url).strip())

def create_interface() -> gr.Blocks:
    """Create Gradio interface."""
    config = load_config()

    with gr.Blocks(title="HealthcareAI powered by HPE Private Cloud AI") as demo:
        # Header Section
        with gr.Row(elem_id="header-row"):
            logo_path = check_logo_exists(str(APP_DIR / "logo.png"))
            logo_html = ""
            if logo_path:
                b64_logo = encode_image_to_base64(logo_path)
                logo_html = f'<img src="data:image/png;base64,{b64_logo}" style="height: 40px; margin-right: 16px;">'
            
            header_html = f"""
            <div style="display: flex; align-items: center; gap: 10px;">
                {logo_html}
                <h1 style="margin: 0; font-size: 24px; white-space: nowrap;">HealthcareAI powered by HPE Private Cloud AI</h1>
            </div>
            """
            gr.HTML(header_html)

        with gr.Tabs():
            # Tab: About
            with gr.TabItem("About", id="about"):
                gr.Markdown("### About")
                gr.Markdown("""
                This application is designed to showcase a healthcare application built on top of HPE Private Cloud AI.
                
                This tool is designed to support hospitals and clinics in the pursuit of providing superior healthcare treatment to patients.
                
                In this scenario we support the healthcare process by augmenting existing tools & expertise with AI powered intelligence.
                """)
                
                gr.Markdown("## Architecture Diagram")
                diag_path = check_logo_exists(str(APP_DIR / "architecture_diagram.png"))
                diag_html = "<i>Architecture diagram not found.</i>"
                if diag_path:
                    logger.info("loading_diagram_asset", path=diag_path)
                    b64_diag = encode_image_to_base64(diag_path)
                    diag_html = (
                        f'<img src="data:image/png;base64,{b64_diag}" '
                        f'alt="Architecture Diagram" style="width:100%;">'
                    )
                else:
                    logger.error("diagram_asset_missing", path=str(APP_DIR / "architecture_diagram.png"))
                gr.HTML(diag_html)
            
            # Tab: TranslationAI
            with gr.TabItem("TranslationAI", id="translation_ai"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### Patient Audio")
                        trans_input_mode = gr.Radio(["Upload", "Record"], label="Mode", value="Upload")
                        trans_audio_file = gr.Audio(type="filepath", label="Upload", visible=True)
                        trans_audio_mic = gr.Audio(
                            type="filepath", label="Record", sources=["microphone"], visible=False
                        )
                        with gr.Row():
                            patient_lang = gr.Dropdown(LANGUAGES, label="Patient", value="")
                            doctor_lang = gr.Dropdown(LANGUAGES, label="Physician", value="English (en)")
                        
                        whisper_warn = gr.Markdown("⚠️ **Whisper URL not configured.** Transcription disabled. Set URL in Settings.", visible=not is_configured(config['whisper']['url']))
                        transcribe_btn = gr.Button("Transcribe Audio", variant="primary", interactive=is_configured(config['whisper']['url']))
                        
                        translate_warn = gr.Markdown("⚠️ **TranslateGemma URL not configured.** Translation disabled. Set URL in Settings.", visible=not is_configured(config['translategemma']['url']))
                        translate_btn = gr.Button("Translate Text", variant="primary", interactive=is_configured(config['translategemma']['url']))
                    
                    with gr.Column():
                        gr.Markdown("### Results")
                        transcription_out = gr.Textbox(label="Transcription", lines=8)
                        translation_out = gr.Textbox(label="Translation", lines=8)
                        processing_status = gr.Textbox(label="Processing Status")

            # Tab: TriageAI
            with gr.TabItem("TriageAI", id="triage_ai"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### Physician Clinical Notes")
                        triage_input_mode = gr.Radio(["Upload", "Record"], label="Mode", value="Upload")
                        triage_audio_file = gr.Audio(type="filepath", label="Upload", visible=True)
                        triage_audio_mic = gr.Audio(
                            type="filepath", label="Record", sources=["microphone"], visible=False
                        )
                        whisper_warn_triage = gr.Markdown("⚠️ **Whisper URL not configured.** Transcription disabled.", visible=not is_configured(config['whisper']['url']))
                        transcribe_triage_btn = gr.Button("Transcribe Clinical Notes", variant="primary", interactive=is_configured(config['whisper']['url']))
                        triage_transcription = gr.Textbox(label="Transcription", lines=8)
                    
                    with gr.Column():
                        gr.Markdown("### Analysis & Diagnostic Recommendation")
                        medgemma_warn_triage = gr.Markdown("⚠️ **MedGemma URL not configured.** AI analysis disabled. Set URL in Settings.", visible=not is_configured(config['medgemma']['url']))
                        diagnose_triage_btn = gr.Button("Generate AI Analysis", variant="primary", interactive=is_configured(config['medgemma']['url']))
                        triage_diagnosis_output = gr.Textbox(label="MedGemma Recommendation", lines=18)
                        triage_status = gr.Textbox(label="Status")

                        save_db_btn = gr.Button("Save to Database")
                        db_status = gr.Textbox(label="Database Status", show_label=False)

            # Tab: XrayAI
            with gr.TabItem("XrayAI", id="xray_ai"):
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### Radiography Upload")
                        xray_image = gr.Image(type="filepath", label="X-ray", height=400)
                        medgemma_warn_xray = gr.Markdown("⚠️ **MedGemma URL not configured.** X-ray analysis disabled. Set URL in Settings.", visible=not is_configured(config['medgemma']['url']))
                        diagnose_xray_btn = gr.Button("Analyze X-ray", variant="primary", interactive=is_configured(config['medgemma']['url']))
                        xray_status = gr.Textbox(label="Status")
                    
                    with gr.Column():
                        gr.Markdown("### Radiologic Analysis")
                        xray_analysis_out = gr.Textbox(label="Analysis", lines=25)

            # Tab: Settings
            with gr.TabItem("Settings", id="settings"):
                gr.Markdown("### Service Configuration")
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### Whisper (STT)")
                        whisper_url = gr.Textbox(label="URL", value=config['whisper']['url'])
                        whisper_token = gr.Textbox(label="Token", type="password", value=config['whisper']['token'])
                        whisper_model = gr.Textbox(label="Model ID", value=config['whisper']['model'])
                    with gr.Column():
                        gr.Markdown("#### TranslateGemma")
                        translategemma_url = gr.Textbox(label="URL", value=config['translategemma']['url'])
                        translategemma_token = gr.Textbox(label="Token", type="password", value=config['translategemma']['token'])
                        translategemma_model = gr.Textbox(label="Model ID", value=config['translategemma']['model'])
                    with gr.Column():
                        gr.Markdown("#### MedGemma")
                        medgemma_url = gr.Textbox(label="URL", value=config['medgemma']['url'])
                        medgemma_token = gr.Textbox(label="Token", type="password", value=config['medgemma']['token'])
                        medgemma_model = gr.Textbox(label="Model ID", value=config['medgemma']['model'])
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### Database (PostgreSQL)")
                        db_conn_str = gr.Textbox(
                            label="Connection String", 
                            value=config.get('database', {}).get('connection_string', DEFAULTS['database']['connection_string']),
                            placeholder="postgresql://user:password@host:port/dbname"
                        )
                
                with gr.Row(visible=False) as init_db_row:
                    with gr.Column():
                        gr.Markdown("⚠️ **Table 'triage' not found.** Click below to create the table and populate it with 200 sample medical records.")
                        init_btn = gr.Button("Initialize Database", variant="secondary")

                with gr.Row():
                    check_btn = gr.Button("Check Health")
                    save_btn = gr.Button("Save Configuration", variant="primary")
                status_box = gr.Textbox(label="Health Status", lines=6)

        # Event Handlers
        def toggle_mode(choice: str) -> Tuple[gr.update, gr.update]:
            return gr.update(visible=(choice == "Upload")), gr.update(visible=(choice == "Record"))

        triage_input_mode.change(toggle_mode, triage_input_mode, [triage_audio_file, triage_audio_mic])
        trans_input_mode.change(toggle_mode, trans_input_mode, [trans_audio_file, trans_audio_mic])

        async def check_all(
            w_url, w_tok, w_mod, n_url, n_tok, n_mod, m_url, m_tok, m_mod, db_conn
        ) -> Tuple[str, gr.update]:
            results = []
            
            # Whisper Check
            _, msg_w = await ai_client.check_model('whisper', w_url, w_tok, w_mod)
            results.append(f"STT: {msg_w}")
            
            # TranslateGemma Check
            _, msg_n = await ai_client.check_model('translategemma', n_url, n_tok, n_mod)
            results.append(f"Translate: {msg_n}")
            
            # MedGemma Check
            _, msg_m = await ai_client.check_model('medgemma', m_url, m_tok, m_mod)
            results.append(f"Triage: {msg_m}")
            
            # Database Check
            db_ok, msg_db = await db_client.check_database(db_conn)
            results.append(f"Database: {msg_db}")
            
            show_init = "NOT found" in msg_db
            return "\n\n".join(results), gr.update(visible=show_init)

        async def save_and_check(
            w_url, w_tok, w_mod, n_url, n_tok, n_mod, m_url, m_tok, m_mod, db_conn
        ) -> Tuple[str, gr.update]:
            new_config = {
                "whisper": {"url": w_url, "token": w_tok, "model": w_mod},
                "translategemma": {"url": n_url, "token": n_tok, "model": n_mod},
                "medgemma": {"url": m_url, "token": m_tok, "model": m_mod},
                "database": {"connection_string": db_conn}
            }
            save_msg = save_config(new_config)
            statuses, init_visibility = await check_all(
                w_url, w_tok, w_mod, n_url, n_tok, n_mod, m_url, m_tok, m_mod, db_conn
            )
            return f"{statuses}\n\n{save_msg}", init_visibility

        check_btn.click(
            check_all, 
            [
                whisper_url, whisper_token, whisper_model, 
                translategemma_url, translategemma_token, translategemma_model, 
                medgemma_url, medgemma_token, medgemma_model,
                db_conn_str
            ], 
            [status_box, init_db_row]
        )
        save_btn.click(
            save_and_check, 
            [
                whisper_url, whisper_token, whisper_model, 
                translategemma_url, translategemma_token, translategemma_model, 
                medgemma_url, medgemma_token, medgemma_model,
                db_conn_str
            ], 
            [status_box, init_db_row]
        )

        async def run_db_init(db_conn, w_url, w_tok, w_mod, n_url, n_tok, n_mod, m_url, m_tok, m_mod):
            ok, msg = await db_client.initialize_database(db_conn)
            if ok:
                res, _ = await check_all(
                    w_url, w_tok, w_mod, n_url, n_tok, n_mod, m_url, m_tok, m_mod, db_conn
                )
                return f"{msg}\n\n{res}", gr.update(visible=False)
            return msg, gr.update(visible=True)

        init_btn.click(
            run_db_init,
            [
                db_conn_str,
                whisper_url, whisper_token, whisper_model,
                translategemma_url, translategemma_token, translategemma_model,
                medgemma_url, medgemma_token, medgemma_model
            ],
            [status_box, init_db_row]
        )

        async def run_trans(
            mode, file, mic, lang, url, tok, mod, progress=gr.Progress()
        ) -> Tuple[str, str, str]:
            path = file if mode == "Upload" else mic
            if not path:
                return "", "No audio provided.", lang
            
            is_auto = (lang == "")
            progress(0.2, desc="Transcribing...")
            detected_lang, text = await ai_client.transcribe_audio(
                path, is_auto, lang, url, tok, mod
            )
            
            status_msg = f"Transcribed{' (Detected: ' + detected_lang + ')' if is_auto else ''}."
            return text, status_msg, lang

        async def run_translate(
            text, s_lang, t_lang, url, tok, mod, progress=gr.Progress()
        ) -> Tuple[str, str]:
            if not text.strip():
                return "", "No text to translate."
            if s_lang == "":
                return text, "Please select Patient language."
            
            progress(0.5, desc="Translating...")
            res = await ai_client.translate_text(
                text, 
                get_iso_language_code(s_lang), 
                get_iso_language_code(t_lang), 
                url, tok, mod
            )
            return res, f"Translated to {t_lang}"

        transcribe_btn.click(
            run_trans, 
            [
                trans_input_mode, trans_audio_file, trans_audio_mic, 
                patient_lang, whisper_url, whisper_token, whisper_model
            ], 
            [transcription_out, processing_status, patient_lang]
        )
        translate_btn.click(
            run_translate, 
            [
                transcription_out, patient_lang, doctor_lang, 
                translategemma_url, translategemma_token, translategemma_model
            ], 
            [translation_out, processing_status]
        )

        async def run_triage_trans(
            mode, file, mic, url, tok, mod, progress=gr.Progress()
        ) -> Tuple[str, str]:
            path = file if mode == "Upload" else mic
            if not path:
                return "", "No audio provided."
            progress(0.1, desc="Transcribing notes...")
            _, text = await ai_client.transcribe_audio(
                path, False, "English (en)", url, tok, mod
            )
            return text, "Transcription complete."

        async def run_analysis(notes, url, tok, mod, progress=gr.Progress()) -> Tuple[str, str]:
            if not notes.strip():
                return "Empty notes provided.", "Please provide clinical notes."
            progress(0.4, desc="Analyzing...")
            ans = await ai_client.analyze_text_with_medgemma(notes, url, tok, mod)
            return ans, "Analysis complete."

        transcribe_triage_btn.click(
            run_triage_trans, 
            [
                triage_input_mode, triage_audio_file, triage_audio_mic, 
                whisper_url, whisper_token, whisper_model
            ], 
            [triage_transcription, triage_status]
        )
        diagnose_triage_btn.click(
            run_analysis, 
            [
                triage_transcription, medgemma_url, medgemma_token, medgemma_model
            ], 
            [triage_diagnosis_output, triage_status]
        )

        async def save_to_db_click(json_data, db_conn) -> str:
            _, msg = await db_client.save_diagnosis_to_db(json_data, db_conn)
            return msg

        save_db_btn.click(save_to_db_click, [triage_diagnosis_output, db_conn_str], [db_status])

        async def run_xray(path, url, tok, mod, progress=gr.Progress()) -> Tuple[str, str]:
            if not path:
                return "No image provided.", ""
            progress(0.3, desc="Analyzing X-ray...")
            ans = await ai_client.analyze_xray_with_medgemma(path, url, tok, mod)
            return "Analysis complete", ans

        diagnose_xray_btn.click(
            run_xray, 
            [xray_image, medgemma_url, medgemma_token, medgemma_model], 
            [xray_status, xray_analysis_out]
        )

        # Reactive Interactivity Updates
        def update_whisper_status(url: str):
            active = is_configured(url)
            return (gr.update(interactive=active), gr.update(interactive=active), gr.update(visible=not active), gr.update(visible=not active))

        def update_translate_status(url: str):
            active = is_configured(url)
            return gr.update(interactive=active), gr.update(visible=not active)

        def update_medgemma_status(url: str):
            active = is_configured(url)
            return (gr.update(interactive=active), gr.update(interactive=active), gr.update(visible=not active), gr.update(visible=not active))

        whisper_url.change(update_whisper_status, whisper_url, [transcribe_btn, transcribe_triage_btn, whisper_warn, whisper_warn_triage])
        translategemma_url.change(update_translate_status, translategemma_url, [translate_btn, translate_warn])
        medgemma_url.change(update_medgemma_status, medgemma_url, [diagnose_triage_btn, diagnose_xray_btn, medgemma_warn_triage, medgemma_warn_xray])

        # Persistence & Sync Logic (runs on every page load/refresh)
        async def sync_on_load():
            """Refresh UI components with latest configuration from disk."""
            current_config = load_config()
            
            # Extract values
            w_url = current_config['whisper']['url']
            w_tok = current_config['whisper']['token']
            w_mod = current_config['whisper']['model']
            
            n_url = current_config['translategemma']['url']
            n_tok = current_config['translategemma']['token']
            n_mod = current_config['translategemma']['model']
            
            m_url = current_config['medgemma']['url']
            m_tok = current_config['medgemma']['token']
            m_mod = current_config['medgemma']['model']
            
            db_conn = current_config.get('database', {}).get('connection_string', DEFAULTS['database']['connection_string'])
            
            # Sync values and apply interactivity logic
            return [
                w_url, w_tok, w_mod,
                n_url, n_tok, n_mod,
                m_url, m_tok, m_mod,
                db_conn,
                # Pass URLs to update visibility/interactivity state on load
                *update_whisper_status(w_url),
                *update_translate_status(n_url),
                *update_medgemma_status(m_url)
            ]

        demo.load(
            sync_on_load,
            inputs=None,
            outputs=[
                whisper_url, whisper_token, whisper_model,
                translategemma_url, translategemma_token, translategemma_model,
                medgemma_url, medgemma_token, medgemma_model,
                db_conn_str,
                # Dynamic Interactivity/Warnings
                transcribe_btn, transcribe_triage_btn, whisper_warn, whisper_warn_triage,
                translate_btn, translate_warn,
                diagnose_triage_btn, diagnose_xray_btn, medgemma_warn_triage, medgemma_warn_xray
            ]
        )

    return demo

if __name__ == "__main__":
    demo = create_interface()
    demo.launch(
        server_name="0.0.0.0", 
        server_port=7860, 
        theme=hpe_theme, 
        allowed_paths=['/app']
    )