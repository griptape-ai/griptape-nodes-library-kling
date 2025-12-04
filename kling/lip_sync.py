import time
import jwt
import requests
import json
import base64
from griptape.artifacts import TextArtifact, UrlArtifact, ImageArtifact, ImageUrlArtifact, BlobArtifact
from griptape_nodes.traits.options import Options

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger, GriptapeNodes
from griptape_nodes.retained_mode.events.os_events import ExistingFilePolicy
from griptape_nodes.traits.file_system_picker import FileSystemPicker

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

        # Model Selection
        self.add_parameter(
            Parameter(
                name="model_name",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="kling-v2-1",
                tooltip="Model for lip sync generation.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["kling-v1-5", "kling-v1-6", "kling-v2", "kling-v2-1"])},
                ui_options={"display_name": "Model"}
            )
        )

        # Video Input Parameters
        self.add_parameter(
            Parameter(
                name="video_input_type",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="video_id",
                tooltip="Video input type: 'video_id' for Kling AI generated videos or 'video_url' for uploaded videos.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["video_id", "video_url"])},
                ui_options={"display_name": "Video Input Type"}
            )
        )
        self.add_parameter(
            Parameter(
                name="video_id",
                input_types=["str"],
                output_type="str",
                type="str",
                tooltip="Video ID from previous Kling AI video generation (required when using video_id input type).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "Enter video ID from previous Kling generation..."},
            )
        )
        self.add_parameter(
            Parameter(
                name="video_url",
                input_types=["VideoUrlArtifact", "BlobArtifact", "VideoArtifact", "str"],
                output_type="str",
                type="str",
                tooltip="Video file or URL for lip sync (required when using video_url input type).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "Upload video file or enter URL..."},
            )
        )

        # Set initial parameter visibility based on defaults
        self.hide_parameter_by_name("video_url")  # Hide video_url since default is "video_id"
        # Hide audio parameters since default mode is "text2video"
        self.hide_parameter_by_name(["audio_type", "audio_file", "audio_url"])
        # Hide audio_url since default audio_type is "file" but audio mode is hidden initially
        self.hide_parameter_by_name("audio_url")

        # Mode Selection
        self.add_parameter(
            Parameter(
                name="mode",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="text2video",
                tooltip="Lip-sync generation mode: 'text2video' for text-to-speech or 'audio2video' for audio file input.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["text2video", "audio2video"])},
                ui_options={"display_name": "Mode"}
            )
        )

        # Text-to-Speech Parameters (for text2video mode)
        self.add_parameter(
            Parameter(
                name="text",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Text content for lip-sync video generation (required for text2video mode). Maximum 120 characters.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Enter text to be spoken (max 120 chars)..."}
            )
        )
        self.add_parameter(
            Parameter(
                name="voice_id",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="oversea_male1 (en)",
                tooltip="Voice selection for text-to-speech (required for text2video mode).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=[
                    # English voices first (alphabetical)
                    "ai_chenjiahao_712 (en)", "ai_huangzhong_712 (en)", "ai_huangyaoshi_712 (en)", 
                    "ai_kaiya (en)", "ai_laoguowang_712 (en)", "ai_shatang (en)", "AOT (en)", 
                    "calm_story1 (en)", "cartoon-boy-07 (en)", "cartoon-girl-01 (en)", 
                    "chat1_female_new-3 (en)", "chat_0407_5-1 (en)", "chengshu_jiejie (en)", 
                    "commercial_lady_en_f-v1 (en)", "genshin_klee2 (en)", "genshin_kirara (en)", 
                    "genshin_vindi2 (en)", "girlfriend_4_speech02 (en)", "heainainai_speech02 (en)", 
                    "laopopo_speech02 (en)", "oversea_male1 (en)", "PeppaPig_platform (en)", 
                    "reader_en_m-v1 (en)", "uk_boy1 (en)", "uk_man2 (en)", "you_pingjing (en)", 
                    "zhinen_xuesheng (en)",
                    # Chinese voices (alphabetical)
                    "ai_chenjiahao_712 (zh)", "ai_huangyaoshi_712 (zh)", "ai_kaiya (zh)", 
                    "ai_laoguowang_712 (zh)", "ai_shatang (zh)", "ai_taiwan_man2_speech02 (zh)", 
                    "cartoon-boy-07 (zh)", "cartoon-girl-01 (zh)", "chaoshandashu_speech02 (zh)", 
                    "chat1_female_new-3 (zh)", "chengshu_jiejie (zh)", "chongqingxiaohuo_speech02 (zh)", 
                    "chuanmeizi_speech02 (zh)", "daopianyansang-v1 (zh)", "diyinnansang_DB_CN_M_04-v2 (zh)", 
                    "dongbeilaotie_speech02 (zh)", "genshin_klee2 (zh)", "genshin_kirara (zh)", 
                    "genshin_vindi2 (zh)", "girlfriend_1_speech02 (zh)", "girlfriend_2_speech02 (zh)", 
                    "guanxiaofang-v2 (zh)", "heainainai_speech02 (zh)", "laopopo_speech02 (zh)", 
                    "mengwa-v1 (zh)", "tianmeixuemei-v1 (zh)", "tianjinjiejie_speech02 (zh)", 
                    "tiexin_nanyou (zh)", "tiyuxi_xuedi (zh)", "uk_oldman3 (zh)", 
                    "xianzhanggui_speech02 (zh)", "yizhipiannan-v1 (zh)", "you_pingjing (zh)", 
                    "zhinen_xuesheng (zh)", "zhuxi_speech02 (zh)"
                ])},
                ui_options={"display_name": "Voice"}
            )
        )
        self.add_parameter(
            Parameter(
                name="voice_speed",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=1.0,
                tooltip="Speech rate (0.8-2.0). Valid range: 0.8-2.0, accurate to one decimal place.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"slider": {"min_val": 0.8, "max_val": 2.0, "step": 0.1}}
            )
        )

        # Audio Parameters (for audio2video mode)
        self.add_parameter(
            Parameter(
                name="audio_type",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="file",
                tooltip="Method of transmitting audio files for lip-sync video generation by audio file (required for audio2video mode).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["file", "url"])},
                ui_options={"display_name": "Audio Type"}
            )
        )
        
        # Audio file picker parameter
        audio_file = Parameter(
            name="audio_file",
            type="str",
            default_value="",
            tooltip="Select an audio file from your local filesystem (required when audio_type is 'file'). Supported formats: .mp3/.wav/.m4a/.aac, max 5MB.",
            allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            ui_options={"clickable_file_browser": True, "display_name": "Audio File"}
        )
        audio_file.add_trait(FileSystemPicker(
            allow_files=True,
            allow_directories=False,
            file_extensions=[".mp3", ".wav", ".m4a", ".aac"],
            max_file_size=5242880,  # 5MB in bytes
            workspace_only=True
        ))
        self.add_parameter(audio_file)
        
        self.add_parameter(
            Parameter(
                name="audio_url",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Audio file download URL (required when audio_type is 'url'). Supported formats: .mp3/.wav/.m4a/.aac, max 5MB.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "https://example.com/audio.mp3"}
            )
        )

        # Callback Parameter
        self.add_parameter(
            Parameter(
                name="callback_url",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Callback notification address for task status changes.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"hide": True}
            )
        )

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
        access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)

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

        # Validate mode-specific parameters
        mode = self.get_parameter_value("mode")
        if mode == "text2video":
            text = self.get_parameter_value("text")
            if not text or not text.strip():
                errors.append(ValueError("Text is required when mode is 'text2video'."))
            elif len(text.strip()) > 120:
                errors.append(ValueError("Text content cannot exceed 120 characters."))
                
            voice_id = self.get_parameter_value("voice_id")
            if not voice_id or not voice_id.strip():
                errors.append(ValueError("Voice ID is required when mode is 'text2video'."))
                
        elif mode == "audio2video":
            audio_type = self.get_parameter_value("audio_type")
            if audio_type == "file":
                audio_file = self.get_parameter_value("audio_file")
                if not audio_file:
                    errors.append(ValueError("Audio file is required when audio_type is 'file'."))
            elif audio_type == "url":
                audio_url = self.get_parameter_value("audio_url")
                if not audio_url or not audio_url.strip():
                    errors.append(ValueError("Audio URL is required when audio_type is 'url'."))

        # Validate voice speed range
        voice_speed = self.get_parameter_value("voice_speed")
        if not (0.8 <= voice_speed <= 2.0):
            errors.append(ValueError("Voice speed must be between 0.8 and 2.0."))

        return errors if errors else None

    def after_value_set(self, parameter: Parameter, value: any, modified_parameters_set: set[str] | None = None) -> None:
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
                
            if modified_parameters_set is not None:
                modified_parameters_set.update(["video_id", "video_url"])
            
        elif parameter.name == "mode":
            if value == "text2video":
                # Show text-to-speech parameters, hide audio parameters
                self.show_parameter_by_name(["text", "voice_id", "voice_speed"])
                self.hide_parameter_by_name(["audio_type", "audio_file", "audio_url"])
            elif value == "audio2video":
                # Show audio parameters, hide text-to-speech parameters
                self.show_parameter_by_name(["audio_type", "audio_file", "audio_url"])
                self.hide_parameter_by_name(["text", "voice_id", "voice_speed"])
                
            if modified_parameters_set is not None:
                modified_parameters_set.update(["text", "voice_id", "voice_speed", "audio_type", "audio_file", "audio_url"])
                
        elif parameter.name == "audio_type":
            if value == "file":
                # Show audio file input, hide audio URL
                self.show_parameter_by_name("audio_file")
                self.hide_parameter_by_name("audio_url")
            elif value == "url":
                # Show audio URL input, hide audio file
                self.show_parameter_by_name("audio_url")
                self.hide_parameter_by_name("audio_file")
                
            if modified_parameters_set is not None:
                modified_parameters_set.update(["audio_file", "audio_url"])

    def process(self) -> AsyncResult[None]:
        yield lambda: self._process()
        
    def _process(self):
        # Validate before processing
        validation_errors = self.validate_node()
        if validation_errors:
            error_message = "; ".join(str(e) for e in validation_errors)
            raise ValueError(f"Validation failed: {error_message}")
            
        def create_lip_sync() -> VideoUrlArtifact:
            access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
            secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)
            jwt_token = encode_jwt_token(access_key, secret_key)
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

            # Build input object for new API structure
            input_obj = {
                "model_name": self.get_parameter_value("model_name"),
                "mode": self.get_parameter_value("mode")
            }
            
            mode = self.get_parameter_value("mode")

            # Add mode-specific parameters
            if mode == "text2video":
                # Parse voice_id which includes language in format "voice_id (lang)"
                voice_selection = self.get_parameter_value("voice_id").strip()
                if " (" in voice_selection and voice_selection.endswith(")"):
                    voice_id = voice_selection.split(" (")[0]
                    voice_language = voice_selection.split(" (")[1][:-1]  # Remove closing parenthesis
                else:
                    # Fallback if format is unexpected
                    voice_id = voice_selection
                    voice_language = "en"
                    
                input_obj.update({
                    "text": self.get_parameter_value("text").strip(),
                    "voice_id": voice_id,
                    "voice_language": voice_language,
                    "voice_speed": self.get_parameter_value("voice_speed")
                })
            elif mode == "audio2video":
                audio_type = self.get_parameter_value("audio_type")
                input_obj["audio_type"] = audio_type
                
                if audio_type == "file":
                    audio_file = self.get_parameter_value("audio_file")
                    # Handle file upload - for now use placeholder
                    # In production, you'd upload the file and get a URL
                    input_obj["audio_file"] = str(audio_file)  # Simplified for now
                elif audio_type == "url":
                    input_obj["audio_url"] = self.get_parameter_value("audio_url").strip()
            else:
                raise ValueError(f"Unknown mode: {mode}")

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

            # Create final payload with input wrapper
            payload = {"input": input_obj}
            
            # Add callback parameters outside of input
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
            max_retries = 120  # Lip-sync may take longer - up to 10 minutes
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
                        
                        # Download the generated video and save to static storage
                        try:
                            download_response = requests.get(video_url, timeout=60)
                            download_response.raise_for_status()
                            video_bytes = download_response.content
                        except requests.exceptions.RequestException as e:
                            raise RuntimeError(f"Failed to download generated lip-sync video: {e}") from e

                        filename = f"kling_lip_sync_{int(time.time())}.mp4"
                        static_files_manager = GriptapeNodes.StaticFilesManager()
                        saved_url = static_files_manager.save_static_file(video_bytes, filename, ExistingFilePolicy.CREATE_NEW)

                        # Create artifact and publish outputs
                        video_artifact = VideoUrlArtifact(url=saved_url, name=filename)
                        self.publish_update_to_parameter("lip_sync_video_url", video_artifact)
                        if actual_video_id:
                            self.publish_update_to_parameter("task_id", actual_video_id)
                        
                        return video_artifact
                        
                    if status == "failed":
                        error_msg = result["data"].get("task_status_msg", "Unknown error")
                        logger.error(f"Kling lip-sync failed: {error_msg}")
                        
                        # Publish error message to output instead of crashing the node
                        error_artifact = VideoUrlArtifact(url="")
                        error_artifact.name = f"Lip-sync failed: {error_msg}"
                        self.publish_update_to_parameter("lip_sync_video_url", error_artifact)
                        self.publish_update_to_parameter("task_id", f"FAILED: {error_msg}")
                        
                        logger.info(f"Lip-sync task failed gracefully with message: {error_msg}")
                        return error_artifact

                except requests.exceptions.RequestException as e:
                    logger.warning(f"Polling request failed (Attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Failed to get lip-sync status after multiple retries: {e}") from e

            raise RuntimeError("Kling lip-sync task timed out.")

        return create_lip_sync() 