import time
import jwt
import requests
import json
from griptape.artifacts import TextArtifact, UrlArtifact
from griptape_nodes.traits.options import Options

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger, GriptapeNodes

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api-singapore.klingai.com/v1/videos/video-extend"


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


class KlingAI_VideoExtension(ControlNode):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.category = "AI/Kling"
        self.description = "Extends existing videos by 4-5 seconds using Kling AI (V1.5 only). Max total: 3 minutes."

        # Basic Settings Group
        with ParameterGroup(name="Basic Settings") as basic_group:
            Parameter(
                name="video_id",
                input_types=["str"],
                output_type="str",
                type="str",
                tooltip="Video ID from previous Kling AI video generation (required).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"placeholder_text": "Enter video ID from previous Kling generation..."},
            )
            Parameter(
                name="prompt",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Text prompt for video extension (max 2500 chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Describe how to continue the video..."},
            )
            Parameter(
                name="negative_prompt",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Negative text prompt (max 2500 chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Describe what you don't want..."},
            )
        self.add_node_element(basic_group)

        # Extension Settings Group
        with ParameterGroup(name="Extension Settings") as extension_group:
            Parameter(
                name="cfg_scale",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.5,
                tooltip="Flexibility (0-1). Higher value = lower flexibility, stronger prompt relevance.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        self.add_node_element(extension_group)

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
                name="extended_video_url",
                output_type="VideoUrlArtifact",
                type="VideoUrlArtifact",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="Output URL of the extended video.",
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
                tooltip="The Task ID of the video extension from Kling AI.",
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

        # Check required video_id
        video_id = self.get_parameter_value("video_id")
        if not video_id or not video_id.strip():
            errors.append(ValueError("Video ID is required for video extension."))

        # Validate cfg_scale range
        cfg_scale = self.get_parameter_value("cfg_scale")
        if not (0.0 <= cfg_scale <= 1.0):
            errors.append(ValueError("cfg_scale must be between 0.0 and 1.0."))

        return errors if errors else None

    def process(self) -> AsyncResult:
        # Validate before yielding
        validation_errors = self.validate_node()
        if validation_errors:
            error_message = "; ".join(str(e) for e in validation_errors)
            raise ValueError(f"Validation failed: {error_message}")
            
        def extend_video() -> VideoUrlArtifact:
            access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
            secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)
            jwt_token = encode_jwt_token(access_key, secret_key)
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

            # Build payload - video_id is required, others optional
            payload = {
                "video_id": self.get_parameter_value("video_id").strip(),
                "cfg_scale": self.get_parameter_value("cfg_scale"),
            }

            # Add optional parameters
            prompt = self.get_parameter_value("prompt")
            if prompt and prompt.strip():
                payload["prompt"] = prompt.strip()

            negative_prompt = self.get_parameter_value("negative_prompt")
            if negative_prompt and negative_prompt.strip():
                payload["negative_prompt"] = negative_prompt.strip()

            # Add callback parameters
            callback_url = self.get_parameter_value("callback_url")
            if callback_url and callback_url.strip():
                payload["callback_url"] = callback_url.strip()

            logger.info(f"Kling Video Extension API Request Payload: {json.dumps(payload, indent=2)}")
            
            # Make request
            response = requests.post(BASE_URL, headers=headers, json=payload, timeout=30)
            if response.status_code != 200:
                try:
                    logger.error(f"Kling Video Extension error body: {json.dumps(response.json(), indent=2)}")
                except Exception:
                    logger.error(f"Kling Video Extension error text: {response.text}")
            response.raise_for_status()
            
            task_id = response.json()["data"]["task_id"]
            poll_url = f"{BASE_URL}/{task_id}"
            
            # Polling for completion
            max_retries = 120  # Video extension may take longer - up to 10 minutes
            retry_delay = 5
            
            for attempt in range(max_retries):
                try:
                    time.sleep(retry_delay)
                    result_response = requests.get(poll_url, headers=headers, timeout=30)
                    result_response.raise_for_status()
                    result = result_response.json()
                    
                    status = result["data"]["task_status"]
                    logger.info(f"Kling video extension status (Task ID: {task_id}): {status} (Attempt {attempt + 1}/{max_retries})")

                    if status == "succeed":
                        video_url = result["data"]["task_result"]["videos"][0]["url"]
                        actual_video_id = result["data"]["task_result"]["videos"][0]["id"]
                        logger.info(f"Kling video extension succeeded: {video_url}")
                        
                        # Download the generated video and save to static storage
                        try:
                            download_response = requests.get(video_url, timeout=60)
                            download_response.raise_for_status()
                            video_bytes = download_response.content
                        except requests.exceptions.RequestException as e:
                            raise RuntimeError(f"Failed to download extended video: {e}") from e

                        filename = f"kling_video_extension_{int(time.time())}.mp4"
                        static_files_manager = GriptapeNodes.StaticFilesManager()
                        saved_url = static_files_manager.save_static_file(video_bytes, filename)

                        # Create artifact and publish outputs
                        video_artifact = VideoUrlArtifact(url=saved_url, name=filename)
                        self.publish_update_to_parameter("extended_video_url", video_artifact)
                        if actual_video_id:
                            # Publish to correct parameter name declared for this node
                            self.publish_update_to_parameter("task_id", actual_video_id)
                        
                        return video_artifact
                        
                    if status == "failed":
                        error_msg = result["data"].get("task_status_msg", "Unknown error")
                        logger.error(f"Kling video extension failed: {error_msg}")
                        raise RuntimeError(f"Kling video extension failed: {error_msg}")

                except requests.exceptions.RequestException as e:
                    logger.warning(f"Polling request failed (Attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Failed to get video extension status after multiple retries: {e}") from e

            raise RuntimeError("Kling video extension task timed out.")

        yield extend_video 