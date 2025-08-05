import time
import jwt
import requests
import json
from griptape.artifacts import TextArtifact, UrlArtifact
from griptape_nodes.traits.options import Options

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api-singapore.klingai.com/v1/videos/text2video"

class VideoUrlArtifact(UrlArtifact):
    """
    Artifact that contains a URL to a video.
    """
    def __init__(self, url: str):
        super().__init__(url)


def encode_jwt_token(ak: str, sk: str) -> str:
    headers = {"alg": "HS256", "typ": "JWT"}

    payload = {
        "iss": ak,
        "exp": int(time.time()) + 1800,  # valid for 30 minutes
        "nbf": int(time.time()) - 5,  # valid 5 seconds ago
    }

    token = jwt.encode(payload, sk, algorithm="HS256", headers=headers)
    return token


class KlingAI_TextToVideo(ControlNode):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.add_parameter(
            Parameter(
                name="prompt",
                input_types=["str"],
                output_type="str",
                type="str",
                tooltip="Text prompt for video generation (max 2500 chars)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Describe the video you want..."},
            )
        )
        self.add_parameter(
            Parameter(
                name="model_name",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="kling-v1-6",
                tooltip="Model Name",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["kling-v1-6", "kling-v2-master", "kling-v2-1-master"])},
            )
        )
        self.add_parameter(
            Parameter(
                name="negative_prompt",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Negative text prompt (max 2500 chars)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True},
            )
        )
        self.add_parameter(
            Parameter(
                name="cfg_scale",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.5,
                tooltip="Flexibility in video generation (0-1). Higher value = lower flexibility, stronger prompt relevance.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        )
        self.add_parameter(
            Parameter(
                name="mode",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="std",
                tooltip="Video generation mode (std: Standard, pro: Professional)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["std", "pro"])}
            )
        )
        self.add_parameter(
            Parameter(
                name="aspect_ratio",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="16:9",
                tooltip="Aspect ratio of the generated video frame (width:height)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["16:9", "9:16", "1:1"])}
            )
        )
        self.add_parameter(
            Parameter(
                name="duration",
                input_types=["int"],
                output_type="int",
                type="int",
                default_value=5,
                tooltip="Video Length, unit: s (seconds)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=[5, 10])}
            )
        )
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
            Parameter(
                name="external_task_id",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Customized Task ID (must be unique within user account).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        callback_group.ui_options = {"hide": True}  # Hidden until Griptape supports callbacks
        self.add_node_element(callback_group)
        self.add_parameter(
            Parameter(
                name="video_url",
                output_type="VideoUrlArtifact",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="Video URL",
                ui_options={"placeholder_text": "", "is_full_width": True}
            )
        )
        self.add_parameter(
            Parameter(
                name="video_id",
                output_type="str",
                type="str",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="The Task ID of the generated video from Kling AI.",
                ui_options={"placeholder_text": "", "is_full_width": True}
            )
        )

    def validate_node(self) -> list[Exception] | None:
        """Validates that the Kling API keys are configured and model constraints.
        Returns:
            list[Exception] | None: List of exceptions if validation fails, None if validation passes.
        """
        access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
        secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)

        errors = []
        if not access_key:
            errors.append(
                ValueError(f"Kling access key not found. Please set the {API_KEY_ENV_VAR} environment variable.")
            )
        if not secret_key:
            errors.append(
                ValueError(f"Kling secret key not found. Please set the {SECRET_KEY_ENV_VAR} environment variable.")
            )

        # Negative prompt length validation
        negative_prompt = self.get_parameter_value("negative_prompt")
        if negative_prompt and len(negative_prompt) > 2500:
            errors.append(ValueError("negative_prompt exceeds 2500 characters (limit: 2500)."))

        return errors if errors else None

    def after_value_set(self, parameter: Parameter, value: any, modified_parameters_set: set[str] | None = None) -> None:
        """Update parameter visibility based on model selection."""
        if parameter.name == "model_name":
            # All current models (kling-v1-6, kling-v2-master, kling-v2-1-master) support all options
            # Show all parameters for these models
            self.show_parameter_by_name(["mode", "duration"])
                
            # Add all potentially modified parameters to the set if provided
            if modified_parameters_set is not None:
                modified_parameters_set.update(["mode", "duration"])

    def process(self) -> AsyncResult[None]:
        yield lambda: self._process()
    
    def _process(self):
        prompt = self.get_parameter_value("prompt")

        def generate_video() -> TextArtifact:
            access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
            secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)

            jwt_token = encode_jwt_token(access_key, secret_key)

            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

            payload = {
                "prompt": prompt,
                "model_name": self.get_parameter_value("model_name"),
                "duration": self.get_parameter_value("duration"),
                "cfg_scale": self.get_parameter_value("cfg_scale"),
                "mode": self.get_parameter_value("mode"),
                "aspect_ratio": self.get_parameter_value("aspect_ratio"),
            }

            negative_prompt_val = self.get_parameter_value("negative_prompt")
            if negative_prompt_val:
                payload["negative_prompt"] = negative_prompt_val
            
            callback_url_val = self.get_parameter_value("callback_url")
            if callback_url_val:
                payload["callback_url"] = callback_url_val

            external_task_id_val = self.get_parameter_value("external_task_id")
            if external_task_id_val:
                payload["external_task_id"] = external_task_id_val

            # Remove empty values to comply with Kling API spec
            payload = {k: v for k, v in payload.items() if v not in (None, "", {}, [])}
            
            logger.info(f"Kling Text-to-Video API Request Payload: {json.dumps(payload, indent=2)}")
            response = requests.post(BASE_URL, headers=headers, json=payload)  # noqa: S113 Collin is this ok to ignore?
            logger.info(f"Initial response status: {response.status_code}")
            logger.info(f"Initial response headers: {dict(response.headers)}")
            logger.info(f"Initial response text: {response.text[:500]}...")  # First 500 chars
            
            try:
                response.raise_for_status()
                response_data = response.json()
                task_id = response_data["data"]["task_id"]
                logger.info(f"Task created with ID: {task_id}")
            except requests.exceptions.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON from initial response. Status: {response.status_code}")
                logger.error(f"Response text: {response.text}")
                raise RuntimeError(f"Invalid JSON response from Kling API: {e}") from e

            poll_url = f"{BASE_URL}/{task_id}"
            video_url = None
            actual_video_id = None # Initialize variable to store the actual video ID

            max_retries = 120  # 120 retries * 5 seconds = 10 minutes timeout
            retry_count = 0
            
            while retry_count < max_retries:
                time.sleep(5)  # Increased from 3 to 5 seconds
                retry_count += 1
                
                try:
                    result_response = requests.get(poll_url, headers=headers, timeout=30)  # noqa: S113
                    logger.info(f"Polling response status: {result_response.status_code} (attempt {retry_count}/{max_retries})")
                    
                    if result_response.status_code != 200:
                        logger.warning(f"Non-200 status code: {result_response.status_code}")
                        logger.warning(f"Response text: {result_response.text[:500]}...")
                        continue  # Retry on non-200 status
                    
                    logger.info(f"Polling response headers: {dict(result_response.headers)}")
                    logger.info(f"Polling response text: {result_response.text[:500]}...")  # First 500 chars
                    
                    try:
                        result = result_response.json()
                    except requests.exceptions.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON from polling response. Status: {result_response.status_code}")
                        logger.error(f"Response text: {result_response.text}")
                        logger.error(f"Response headers: {dict(result_response.headers)}")
                        if retry_count < max_retries:
                            logger.info(f"Retrying in 5 seconds... (attempt {retry_count}/{max_retries})")
                            continue
                        else:
                            raise RuntimeError(f"Invalid JSON response from Kling API after {max_retries} attempts: {e}") from e
                    
                    status = result["data"]["task_status"]
                    logger.info(f"Video generation status: {status}")
                    if status == "succeed":
                        logger.info(f"Video generation succeeded: {result['data']['task_result']['videos'][0]['url']}")
                        video_url = result["data"]["task_result"]["videos"][0]["url"]
                        actual_video_id = result["data"]["task_result"]["videos"][0]["id"] # Extract the correct video ID
                        break
                    if status == "failed":
                        error_msg = f"Video generation failed: {result['data']['task_status_msg']}"
                        logger.error(error_msg)
                        raise RuntimeError(error_msg)
                    # Continue polling for "submitted", "processing", etc.
                    
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Request failed (attempt {retry_count}/{max_retries}): {e}")
                    if retry_count >= max_retries:
                        raise RuntimeError(f"Failed to poll task status after {max_retries} attempts: {e}") from e
                    logger.info(f"Retrying in 5 seconds...")
                    continue

            if not video_url:
                raise RuntimeError(f"Video generation timed out after {max_retries * 5 / 60:.1f} minutes. Task may still be processing.")

            self.publish_update_to_parameter("video_url", VideoUrlArtifact(video_url))
            if actual_video_id: # Publish the correct video ID if found
                self.publish_update_to_parameter("video_id", actual_video_id)
            logger.info(f"Video URL: {video_url}")
            logger.info(f"Video ID: {actual_video_id}")
            return VideoUrlArtifact(video_url)

        return generate_video()