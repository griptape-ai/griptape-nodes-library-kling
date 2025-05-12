import time
import jwt
import requests
import json # Added for payload logging, though not strictly needed for request itself

from griptape.artifacts import TextArtifact, UrlArtifact # TextArtifact for task_id potentially
from griptape_nodes.traits.options import Options # Not strictly needed for this node based on docs, but good to have

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger

# Re-use VideoUrlArtifact if it's in a shared utils or define locally if not.
# Assuming it's defined in the other Kling files and can be imported or redefined.
class VideoUrlArtifact(UrlArtifact):
    """
    Artifact that contains a URL to a video.
    """
    def __init__(self, url: str, name: str | None = None):
        super().__init__(value=url, name=name or self.__class__.__name__)

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api.klingai.com/v1/videos/video-extend"

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
        self.description = "Extends an existing Kling AI video."

        # Core Input Group
        with ParameterGroup(name="Core Input") as core_input_group:
            Parameter(
                name="video_id",
                input_types=["str"],
                type="str",
                tooltip="Required. The ID of the Kling video to extend.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                 ui_options={"placeholder_text": "Enter existing Kling video ID..."},
            )
        self.add_node_element(core_input_group)

        # Prompts Group
        with ParameterGroup(name="Prompts") as prompts_group:
            Parameter(
                name="prompt",
                input_types=["str"],
                type="str",
                default_value="",
                tooltip="Optional. Text prompt for the extension (max 2500 chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Describe desired changes or continuation..."},
            )
            Parameter(
                name="negative_prompt",
                input_types=["str"],
                type="str",
                default_value="",
                tooltip="Optional. Negative text prompt (max 2500 chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True},
            )
        prompts_group.ui_options = {"hide": True} # Collapse by default
        self.add_node_element(prompts_group)

        # Generation Settings Group
        with ParameterGroup(name="Generation Settings") as gen_settings_group:
            Parameter(
                name="cfg_scale",
                input_types=["float"],
                type="float",
                default_value=0.5,
                tooltip="Optional. Flexibility (0-1). Higher value = lower flexibility, stronger prompt relevance.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        gen_settings_group.ui_options = {"hide": True} # Collapse by default
        self.add_node_element(gen_settings_group)
        
        # Callback Parameters Group
        with ParameterGroup(name="Callback") as callback_group:
            Parameter(
                name="callback_url",
                input_types=["str"],
                type="str",
                default_value="",
                tooltip="Optional. Callback notification address for task status changes.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter( # Not in docs for extend, but good for consistency
                name="external_task_id",
                input_types=["str"],
                type="str",
                default_value="",
                tooltip="Optional. Customized Task ID for user tracking.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        callback_group.ui_options = {"hide": True} # Collapse by default
        self.add_node_element(callback_group)

        # Output Parameters
        self.add_parameter(
            Parameter(
                name="extended_video_url",
                output_type="VideoUrlArtifact",
                type="VideoUrlArtifact", # Hint for UI
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="URL of the extended video segment.",
                ui_options={"placeholder_text": "", "is_full_width": True} 
            )
        )
        self.add_parameter(
            Parameter(
                name="extended_video_id",
                output_type="str",
                type="str",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="ID of the newly generated extended video segment.",
                 ui_options={"placeholder_text": ""}
            )
        )
        self.add_parameter(
            Parameter(
                name="extension_task_id",
                output_type="str",
                type="str",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="Task ID for the video extension job.",
                 ui_options={"placeholder_text": ""}
            )
        )

    def validate_node(self) -> list[Exception] | None:
        errors = []
        access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
        secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)

        if not access_key:
            errors.append(ValueError(f"Kling access key not found. Set {API_KEY_ENV_VAR}."))
        if not secret_key:
            errors.append(ValueError(f"Kling secret key not found. Set {SECRET_KEY_ENV_VAR}."))

        cfg_scale_val = self.get_parameter_value("cfg_scale")
        if not (0 <= cfg_scale_val <= 1): # type: ignore[operator]
            errors.append(ValueError("cfg_scale must be between 0.0 and 1.0."))
        
        return errors if errors else None

    def process(self) -> AsyncResult:
        validation_errors = self.validate_node()
        if validation_errors:
            error_message = "; ".join(str(e) for e in validation_errors)
            raise ValueError(f"Validation failed: {error_message}")

        def extend_video_task() -> VideoUrlArtifact:
            video_id_val = self.get_parameter_value("video_id")
            if not video_id_val or not str(video_id_val).strip():
                raise ValueError("'video_id' is required for extension and cannot be empty. Ensure it is connected from a previous node.")

            access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
            secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)
            if not access_key or not secret_key: # Redundant if validate_node is called by framework, but safe
                 raise ValueError("API keys are missing for JWT encoding.")

            jwt_token = encode_jwt_token(access_key, secret_key)
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

            payload: dict[str, any] = {
                "video_id": str(self.get_parameter_value("video_id")).strip(),
                "cfg_scale": self.get_parameter_value("cfg_scale"),
            }

            prompt_val = self.get_parameter_value("prompt")
            if prompt_val and prompt_val.strip():
                payload["prompt"] = prompt_val.strip()
            
            neg_prompt_val = self.get_parameter_value("negative_prompt")
            if neg_prompt_val and neg_prompt_val.strip():
                payload["negative_prompt"] = neg_prompt_val.strip()
            
            callback_url_val = self.get_parameter_value("callback_url")
            if callback_url_val and callback_url_val.strip():
                payload["callback_url"] = callback_url_val.strip()
            
            external_task_id_val = self.get_parameter_value("external_task_id")
            if external_task_id_val and external_task_id_val.strip():
                payload["external_task_id"] = external_task_id_val.strip() # API might ignore, but good to send

            logger.info(f"Kling Video Extension API Request Payload: {json.dumps(payload, indent=2)}")
            response = requests.post(BASE_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            response_data = response.json().get("data", {})
            task_id = response_data.get("task_id")

            if not task_id:
                logger.error(f"Kling video extension task ID not found in response: {response.json()}")
                raise ValueError("Task ID not found in Kling API response for video extension.")

            self.publish_update_to_parameter("extension_task_id", task_id)

            # Polling logic (using BASE_URL for polling, consistent with other Kling nodes)
            poll_url = f"{BASE_URL}/{task_id}" 
            
            final_video_url = None
            final_video_id = None
            max_retries = 60  # ~5 minutes
            retry_delay = 5   # seconds

            for attempt in range(max_retries):
                try:
                    time.sleep(retry_delay)
                    result_response = requests.get(poll_url, headers=headers, timeout=30)
                    result_response.raise_for_status()
                    result = result_response.json()
                    
                    current_task_status = result.get("data", {}).get("task_status")
                    logger.info(f"Kling video extension status (Task ID: {task_id}): {current_task_status} (Attempt {attempt + 1}/{max_retries})")

                    if current_task_status == "succeed":
                        task_result = result.get("data", {}).get("task_result", {})
                        videos_list = task_result.get("videos", [])
                        if videos_list:
                            final_video_url = videos_list[0].get("url")
                            final_video_id = videos_list[0].get("id")
                            logger.info(f"Kling video extension succeeded. New Video URL: {final_video_url}, New Video ID: {final_video_id}")
                        else:
                            logger.error(f"Kling video extension task succeeded but no videos found in result: {result}")
                            raise RuntimeError("Kling video extension task succeeded but no video data returned.")
                        break
                    elif current_task_status == "failed":
                        error_msg = result.get("data", {}).get("task_status_msg", "Unknown error")
                        logger.error(f"Kling video extension failed: {error_msg}")
                        raise RuntimeError(f"Kling video extension failed: {error_msg}")
                
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Polling request failed for video extension (Attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Failed to get video extension status after multiple retries: {e}") from e

            if not final_video_url or not final_video_id:
                raise RuntimeError("Kling video extension task finished but no video URL/ID was found or task timed out.")

            self.publish_update_to_parameter("extended_video_url", VideoUrlArtifact(url=final_video_url))
            self.publish_update_to_parameter("extended_video_id", final_video_id)
            
            return VideoUrlArtifact(url=final_video_url)

        yield extend_video_task 