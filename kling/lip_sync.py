import time
import jwt
import requests
import json
import base64
from griptape.artifacts import TextArtifact, UrlArtifact, ImageArtifact, ImageUrlArtifact, BlobArtifact
from griptape_nodes.traits.options import Options

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api-singapore.klingai.com/v1/videos/lip-sync"


class VideoUrlArtifact(UrlArtifact):
    """
    Artifact that contains a URL to a video.
    """
    def __init__(self, url: str, name: str | None = None):
        super().__init__(value=url, name=name or self.__class__.__name__)


def encode_jwt_token(ak: str, sk: str) -> str:
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ak,
        "exp": int(time.time()) + 1800,  # valid for 30 minutes
        "nbf": int(time.time()) - 5,  # valid 5 seconds ago
    }
    token = jwt.encode(payload, sk, algorithm="HS256", headers=headers)
    return token


class KlingAI_LipSync(ControlNode):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.category = "AI/Kling"
        self.description = "Creates lip-sync videos by synchronizing speech to video using Kling AI. Supports both Kling AI generated videos (via video ID) and uploaded videos (via video URL)."

        # Basic Settings Group
        with ParameterGroup(name="Video Input") as video_group:
            Parameter(
                name="video_input_type",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="video_id",
                tooltip="Video input type: 'video_id' for Kling AI generated videos or 'video_url' for uploaded videos.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["video_id", "video_url"])},
            )
            Parameter(
                name="video_id",
                input_types=["str"],
                output_type="str",
                type="str",
                tooltip="Video ID from previous Kling AI video generation (required when using video_id input type).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "Enter video ID from previous Kling generation..."},
            )
            Parameter(
                name="video_url",
                input_types=["VideoUrlArtifact", "BlobArtifact", "VideoArtifact", "str"],
                output_type="str",
                type="str",
                tooltip="Video file or URL for lip sync (required when using video_url input type).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "Upload video file or enter URL..."},
            )
        video_group.ui_options = {"hide": False}
        self.add_node_element(video_group)

        # Voice Settings Group
        with ParameterGroup(name="Voice Settings") as voice_group:
            Parameter(
                name="voice_type",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="text",
                tooltip="Voice input type: 'text' for text-to-speech or 'audio' for audio file.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["text", "audio"])},
            )
            Parameter(
                name="voice_text",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Text to convert to speech (used when voice_type is 'text').",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Enter text to be spoken..."},
            )
            Parameter(
                name="voice_audio_url",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="URL to audio file (used when voice_type is 'audio').",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "https://example.com/audio.mp3"},
            )
        voice_group.ui_options = {"hide": False}
        self.add_node_element(voice_group)

        # TTS Settings Group (for text-to-speech)
        with ParameterGroup(name="Text-to-Speech Settings") as tts_group:
            Parameter(
                name="voice_speaker",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="ai_shatang",
                tooltip="TTS voice speaker (used when voice_type is 'text').",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["ai_shatang", "ai_kaiya", "ai_chenjiahao_712", "ai_huangzhong_712", "ai_huangyaoshi_712", "ai_laoguowang_712", "uk_boy1", "uk_man2", "uk_oldman3", "oversea_male1", "commercial_lady_en_f-v1", "reader_en_m-v1"])},
            )
            Parameter(
                name="voice_speed",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=1.0,
                tooltip="Speech speed multiplier (0.5-2.0). 1.0 = normal speed.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="voice_volume",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=1.0,
                tooltip="Speech volume multiplier (0.1-2.0). 1.0 = normal volume.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        tts_group.ui_options = {"hide": False}
        self.add_node_element(tts_group)

        # Callback Parameters Group
        with ParameterGroup(name="Callback") as callback_group:
            Parameter(
                name="callback_url",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Callback notification address for task status changes.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        callback_group.ui_options = {"hide": True}
        self.add_node_element(callback_group)

        # Output Parameters
        self.add_parameter(
            Parameter(
                name="lip_sync_video_url",
                output_type="VideoUrlArtifact",
                type="VideoUrlArtifact",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="Output URL of the lip-synced video.",
                ui_options={"placeholder_text": "", "is_full_width": True}
            )
        )
        self.add_parameter(
            Parameter(
                name="task_id",
                output_type="str",
                type="str",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="The Task ID of the lip-sync video from Kling AI.",
                ui_options={"placeholder_text": ""}
            )
        )

    def validate_node(self) -> list[Exception] | None:
        """Validates that the Kling API keys are configured and parameters are valid."""
        errors = []
        access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
        secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)

        if not access_key:
            errors.append(ValueError(f"Kling access key not found. Set {API_KEY_ENV_VAR}."))
        if not secret_key:
            errors.append(ValueError(f"Kling secret key not found. Set {SECRET_KEY_ENV_VAR}."))

        # Check required video input based on type
        video_input_type = self.get_parameter_value("video_input_type")
        if video_input_type == "video_id":
            video_id = self.get_parameter_value("video_id")
            if not video_id or not video_id.strip():
                errors.append(ValueError("Video ID is required when using video_id input type."))
        elif video_input_type == "video_url":
            video_url = self.get_parameter_value("video_url")
            if not video_url:
                errors.append(ValueError("Video URL or file is required when using video_url input type."))

        # Validate voice settings based on type
        voice_type = self.get_parameter_value("voice_type")
        if voice_type == "text":
            voice_text = self.get_parameter_value("voice_text")
            if not voice_text or not voice_text.strip():
                errors.append(ValueError("Voice text is required when voice_type is 'text'."))
        elif voice_type == "audio":
            voice_audio_url = self.get_parameter_value("voice_audio_url")
            if not voice_audio_url or not voice_audio_url.strip():
                errors.append(ValueError("Voice audio URL is required when voice_type is 'audio'."))

        # Validate TTS parameters
        voice_speed = self.get_parameter_value("voice_speed")
        if not (0.5 <= voice_speed <= 2.0):
            errors.append(ValueError("Voice speed must be between 0.5 and 2.0."))

        voice_volume = self.get_parameter_value("voice_volume")
        if not (0.1 <= voice_volume <= 2.0):
            errors.append(ValueError("Voice volume must be between 0.1 and 2.0."))

        return errors if errors else None

    def after_value_set(self, parameter: Parameter, value: any, modified_parameters_set: set[str]) -> None:
        """Update parameter visibility based on video input type and voice type selection."""
        if parameter.name == "video_input_type":
            if value == "video_id":
                # Show video ID input, hide video URL
                self.show_parameter_by_name("video_id")
                self.hide_parameter_by_name("video_url")
            elif value == "video_url":
                # Show video URL input, hide video ID
                self.show_parameter_by_name("video_url")
                self.hide_parameter_by_name("video_id")
                
            modified_parameters_set.update(["video_id", "video_url"])
            
        elif parameter.name == "voice_type":
            if value == "text":
                # Show text input and TTS settings, hide audio URL
                self.show_parameter_by_name(["voice_text", "voice_speaker", "voice_speed", "voice_volume"])
                self.hide_parameter_by_name("voice_audio_url")
            elif value == "audio":
                # Show audio URL, hide text input and TTS settings
                self.show_parameter_by_name("voice_audio_url")
                self.hide_parameter_by_name(["voice_text", "voice_speaker", "voice_speed", "voice_volume"])
                
            modified_parameters_set.update(["voice_text", "voice_audio_url", "voice_speaker", "voice_speed", "voice_volume"])

    def process(self) -> AsyncResult:
        # Validate before yielding
        validation_errors = self.validate_node()
        if validation_errors:
            error_message = "; ".join(str(e) for e in validation_errors)
            raise ValueError(f"Validation failed: {error_message}")
            
        def create_lip_sync() -> VideoUrlArtifact:
            access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
            secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)
            jwt_token = encode_jwt_token(access_key, secret_key)
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

            voice_type = self.get_parameter_value("voice_type")

            # Build nested input object based on voice type
            if voice_type == "text":
                input_obj = {
                    "mode": "text2video",
                    "text": self.get_parameter_value("voice_text").strip(),
                    "voice_id": self.get_parameter_value("voice_speaker"),
                    "voice_language": "en",
                    "voice_speed": self.get_parameter_value("voice_speed")
                }
            elif voice_type == "audio":
                input_obj = {
                    "mode": "audio2video",
                    "audio_type": "url",
                    "audio_url": self.get_parameter_value("voice_audio_url").strip()
                }
            else:
                raise ValueError(f"Unknown voice type: {voice_type}")

            # Build payload based on video input type
            video_input_type = self.get_parameter_value("video_input_type")
            
            logger.info(f"Video input type: {video_input_type}")
            
            if video_input_type == "video_id":
                video_id = self.get_parameter_value("video_id").strip()
                input_obj["video_id"] = video_id
                logger.info(f"Using video_id: {video_id}")
            elif video_input_type == "video_url":
                video_url_input = self.get_parameter_value("video_url")
                logger.info(f"Raw video_url input: {video_url_input} (type: {type(video_url_input)})")
                
                # Handle VideoUrlArtifact, BlobArtifact, VideoArtifact, or string input
                if hasattr(video_url_input, 'value') and video_url_input.value:
                    # VideoUrlArtifact or VideoArtifact with URL
                    video_url = video_url_input.value
                    logger.info(f"Extracted video_url from artifact.value: {video_url}")
                elif hasattr(video_url_input, 'to_bytes'):
                    # BlobArtifact or VideoArtifact with binary data - need to upload to get URL
                    # For now, we'll use the artifact directly and let the API handle it
                    # In a production setup, you might want to upload to a file service first
                    raise ValueError("Binary video artifacts require file upload implementation. Please use VideoUrlArtifact or direct URL string.")
                else:
                    # String URL
                    video_url = str(video_url_input)
                    logger.info(f"Using video_url as string: {video_url}")
                
                if not video_url or not video_url.strip():
                    raise ValueError("video_url is empty or invalid")
                    
                input_obj["video_url"] = video_url.strip()
                logger.info(f"Final video_url in input object: {input_obj['video_url']}")
            else:
                raise ValueError(f"Unknown video input type: {video_input_type}")
            
            payload = {"input": input_obj}

            # Add callback parameters
            callback_url = self.get_parameter_value("callback_url")
            if callback_url and callback_url.strip():
                payload["callback_url"] = callback_url.strip()

            logger.info(f"Kling Lip-Sync API Request Payload: {json.dumps(payload, indent=2)}")
            
            # Make request
            response = requests.post(BASE_URL, headers=headers, json=payload, timeout=30)
            
            # Log response details for debugging
            logger.info(f"Kling API Response Status: {response.status_code}")
            logger.info(f"Kling API Response Headers: {dict(response.headers)}")
            
            response_json = None
            try:
                response_json = response.json()
                logger.info(f"Kling API Response Body: {json.dumps(response_json, indent=2)}")
            except:
                logger.info(f"Kling API Response Text: {response.text}")
            
            response.raise_for_status()
            
            if not response_json:
                response_json = response.json()  # Try again after raise_for_status
            task_id = response_json["data"]["task_id"]
            
            poll_url = f"{BASE_URL}/{task_id}"
            
            # Polling for completion
            max_retries = 80  # Lip-sync may take longer - up to 7 minutes
            retry_delay = 5
            
            for attempt in range(max_retries):
                try:
                    time.sleep(retry_delay)
                    result_response = requests.get(poll_url, headers=headers, timeout=30)
                    result_response.raise_for_status()
                    result = result_response.json()
                    
                    status = result["data"]["task_status"]
                    logger.info(f"Kling lip-sync status (Task ID: {task_id}): {status} (Attempt {attempt + 1}/{max_retries})")

                    if status == "succeed":
                        video_url = result["data"]["task_result"]["videos"][0]["url"]
                        actual_video_id = result["data"]["task_result"]["videos"][0]["id"]
                        logger.info(f"Kling lip-sync succeeded: {video_url}")
                        
                        # Create artifact and publish outputs
                        video_artifact = VideoUrlArtifact(url=video_url)
                        self.publish_update_to_parameter("lip_sync_video_url", video_artifact)
                        if actual_video_id:
                            self.publish_update_to_parameter("video_id", actual_video_id)
                        
                        return video_artifact
                        
                    if status == "failed":
                        error_msg = result["data"].get("task_status_msg", "Unknown error")
                        logger.error(f"Kling lip-sync failed: {error_msg}")
                        raise RuntimeError(f"Kling lip-sync failed: {error_msg}")

                except requests.exceptions.RequestException as e:
                    logger.warning(f"Polling request failed (Attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Failed to get lip-sync status after multiple retries: {e}") from e

            raise RuntimeError("Kling lip-sync task timed out.")

        yield create_lip_sync 