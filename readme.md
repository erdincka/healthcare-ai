# HealthcareAI

## Overview

This application is designed to showcase a healthcare application ("HealthcareAI") built on top of HPE Private Cloud AI.

<img width="2984" height="1400" alt="image" src="https://github.com/user-attachments/assets/cbfbdfad-cf3b-4cca-a903-949b84babff7" />

For the backend, deploy the 3 models below according to the instruction.

Then deploy the frontend application by importing the framework found in the frontend folder. During the import process make sure to configure your serving endpoints either during import or later via the GUI by updating the values yaml via the user interface.

## Instructions to prepare models

Instructions to get medgemma working from MLIS:
    registry: none
    model format: custom
    image: vllm/vllm-openai:v0.9.0
    arguments: --model google/medgemma-4b-it --port 8080
    advanced options add parameter: HUGGING_FACE_HUB_TOKEN [mytoken]

Instructions to get translategemma working from MLIS:
    registry: none
    model format: custom
    image: vllm/vllm-openai:latest
    arguments: --model google/translategemma-2-9b --port 8080
    advanced options add parameter: HUGGING_FACE_HUB_TOKEN [mytoken]

Instructions to get whisper working from MLIS:
    registry: none
    model format: custom
    image: davemcmahon/vllm-with-audio:latest
    arguments: --model openai/whisper-large-v3 --port 8080
    
Alternative instructions to deploy models via specialized handlers:
    See the medgemma and translategemma sections above for vLLM deployment.

