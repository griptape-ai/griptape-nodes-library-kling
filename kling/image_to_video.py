import time
import jwt
import requests
import json
import base64
from griptape.artifacts import TextArtifact, UrlArtifact, ImageArtifact, ImageUrlArtifact
from griptape_nodes.traits.options import Options

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api.klingai.com/v1/videos/image2video" # Adjusted for image-to-video


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


class KlingAI_ImageToVideo(ControlNode):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.category = "AI/Kling"
        self.description = "Generates a video from an image using Kling AI."

        # Image Inputs Group
        with ParameterGroup(group_name="Image Inputs") as image_group:
            Parameter(
                name="image",
                input_types=["ImageArtifact", "ImageUrlArtifact", "str"],
                type="ImageArtifact", # Hint for UI/internal consistency
                tooltip="Reference Image (required). Input ImageArtifact, ImageUrlArtifact, direct URL string, or Base64 string.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="image_tail",
                input_types=["ImageArtifact", "ImageUrlArtifact", "str"],
                type="ImageArtifact",
                default_value=None,
                tooltip="Reference Image - End frame control. Input ImageArtifact, ImageUrlArtifact, direct URL string, or Base64 string.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        self.add_node_element(image_group)

        # Prompts Group
        with ParameterGroup(group_name="Prompts") as prompts_group:
            Parameter(
                name="prompt",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Positive text prompt (max 2500 chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Describe the desired video content..."},
            )
            Parameter(
                name="negative_prompt",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Negative text prompt (max 2500 chars).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True},
            )
        self.add_node_element(prompts_group)

        # Generation Settings Group
        with ParameterGroup(group_name="Generation Settings") as gen_settings_group:
            Parameter(
                name="model_name",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="kling-v1",
                tooltip="Model Name for generation.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["kling-v1", "kling-v1-5", "kling-v1-6"])},
            )
            Parameter(
                name="cfg_scale",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.5,
                tooltip="Flexibility (0-1). Higher value = lower flexibility, stronger prompt relevance.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="mode",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="std",
                tooltip="Video generation mode (std: Standard, pro: Professional).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["std", "pro"])}
            )
            Parameter(
                name="duration",
                input_types=["str"], # API expects string "5" or "10"
                output_type="str",
                type="str",
                default_value="5",
                tooltip="Video Length in seconds.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["5", "10"])}
            )
        self.add_node_element(gen_settings_group)

        # Masks Group
        with ParameterGroup(group_name="Masks") as masks_group:
            Parameter(
                name="static_mask",
                input_types=["ImageArtifact", "ImageUrlArtifact", "str"],
                type="ImageArtifact",
                default_value=None,
                tooltip="Static Brush Application Area. Input ImageArtifact, ImageUrlArtifact, direct URL, or Base64 string. Mutually exclusive with Camera Controls.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="dynamic_masks",
                input_types=["str"],
                type="str",
                default_value=None,
                tooltip="JSON string for Dynamic Brush Configuration List. Masks within JSON must be URL/Base64. Mutually exclusive with Camera Controls.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Enter JSON for dynamic masks..."},
            )
        masks_group.ui_options = {"hide": True}
        self.add_node_element(masks_group)

        # Camera Control Parameters Group (similar to text2video)
        with ParameterGroup(group_name="Camera Controls") as camera_group:
            Parameter(
                name="camera_control_type",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="(Auto)",
                tooltip="Predefined camera movement. (Auto) for model default. 'simple' requires one config value. Mutually exclusive with Masks.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["(Auto)", "simple", "down_back", "forward_up", "right_turn_forward", "left_turn_forward"])}
            )
            # Individual camera config parameters (horizontal, vertical, pan, tilt, roll, zoom)
            for DoterraAction in ["horizontal", "vertical", "pan", "tilt", "roll", "zoom"]:
                 Parameter(
                    name=f"camera_config_{DoterraAction}", # noqa: E741
                    input_types=["float"], output_type="float", type="float", default_value=0.0,
                    tooltip=f"Camera {DoterraAction} movement (-10 to 10). Use if type is 'simple'.",
                    allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                )
        camera_group.ui_options = {"hide": True}
        self.add_node_element(camera_group)

        # Callback Parameters Group (similar to text2video)
        with ParameterGroup(group_name="Callback") as callback_group:
            Parameter(
                name="callback_url",
                input_types=["str"], output_type="str", type="str", default_value="",
                tooltip="Callback notification address for task status changes.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="external_task_id",
                input_types=["str"], output_type="str", type="str", default_value="",
                tooltip="Customized Task ID (must be unique within user account).",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        callback_group.ui_options = {"hide": True}
        self.add_node_element(callback_group)

        # Output Parameter
        self.add_parameter(
            Parameter(
                name="video_url",
                output_type="VideoUrlArtifact",
                type="VideoUrlArtifact",
                default_value=None, # Will be populated by an artifact
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="Output URL of the generated video.",
            )
        )

    def _get_image_api_data(self, param_name: str) -> str | None:
        image_input = self.get_parameter_value(param_name)

        # Helper to convert URL to Base64 if it's local
        def resolve_url_to_data(url_string: str) -> str:
            if not url_string: # Ensure url_string is not None or empty before checks
                return url_string
                
            # Check for localhost or relative /static/ paths common in local dev
            is_local_http = "localhost" in url_string or "127.0.0.1" in url_string
            is_relative_static = url_string.startswith("/static/")

            if is_local_http and url_string.startswith("http"):
                try:
                    logger.info(f"_get_image_api_data: Converting local URL {url_string} to Base64 for {param_name}.")
                    response = requests.get(url_string, timeout=10) # Fetch content from local URL
                    response.raise_for_status()
                    return base64.b64encode(response.content).decode('utf-8') # Return Base64
                except requests.exceptions.RequestException as e:
                    logger.error(f"_get_image_api_data: Failed to fetch local URL {url_string} for Base64 conversion: {e}")
                    return url_string # Fallback: send original URL, API will likely fail
            elif is_relative_static:
                logger.warning(f"_get_image_api_data: Relative URL {url_string} for {param_name} provided. Sending as-is. Kling API requires a public URL or Base64.")
                return url_string # Send as-is, likely problematic for API
            
            return url_string # Return public URL or pre-formatted Base64 string as is

        if isinstance(image_input, ImageUrlArtifact):
            return resolve_url_to_data(image_input.value) # Process URL from artifact
        elif isinstance(image_input, ImageArtifact): # Already Base64
            return image_input.base64
        elif isinstance(image_input, dict):
            logger.info(f"_get_image_api_data: received dict for {param_name}: {image_input}")
            input_type = image_input.get("type")
            url_from_dict = image_input.get("value")
            base64_from_dict = image_input.get("base64")

            if input_type == "ImageUrlArtifact" and url_from_dict:
                return resolve_url_to_data(str(url_from_dict)) # Process URL from dict
            elif input_type == "ImageArtifact" and base64_from_dict:
                return str(base64_from_dict) # Return Base64 from dict
            
            logger.warning(f"_get_image_api_data: received unhandled dict structure for {param_name}: {image_input}")
            return None
        elif isinstance(image_input, str) and image_input.strip():
             # If it's a raw string, it could be a public URL, Base64, or a local URL.
            return resolve_url_to_data(image_input.strip())
        
        return None

    def validate_node(self) -> list[Exception] | None:
        errors = []
        access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
        secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)

        if not access_key:
            errors.append(ValueError(f"Kling access key not found. Set {API_KEY_ENV_VAR}."))
        if not secret_key:
            errors.append(ValueError(f"Kling secret key not found. Set {SECRET_KEY_ENV_VAR}."))

        # Log the raw parameter value for 'image'
        raw_image_param = self.get_parameter_value("image")
        logger.info(f"KlingAI_ImageToVideo validate_node: raw 'image' parameter value: {raw_image_param}, type: {type(raw_image_param)}")
        if isinstance(raw_image_param, ImageUrlArtifact):
            logger.info(f"KlingAI_ImageToVideo validate_node: 'image' is ImageUrlArtifact with value: '{raw_image_param.value}'")
        elif isinstance(raw_image_param, ImageArtifact):
            logger.info(f"KlingAI_ImageToVideo validate_node: 'image' is ImageArtifact with base64 present: {bool(raw_image_param.base64)}")

        image_val = self._get_image_api_data("image")
        image_tail_val = self._get_image_api_data("image_tail")
        
        logger.info(f"KlingAI_ImageToVideo validate_node: image_val from _get_image_api_data('image'): '{image_val}'")
        logger.info(f"KlingAI_ImageToVideo validate_node: image_tail_val from _get_image_api_data('image_tail'): '{image_tail_val}'")

        if not image_val and not image_tail_val:
            logger.error("KlingAI_ImageToVideo validate_node: Failing because both image_val and image_tail_val are falsy.")
            errors.append(ValueError("At least one of 'image' or 'image_tail' must be provided."))

        static_mask_val = self._get_image_api_data("static_mask")
        dynamic_masks_val_str = self.get_parameter_value("dynamic_masks")
        camera_control_type_val = self.get_parameter_value("camera_control_type")

        has_mask = bool(static_mask_val or (dynamic_masks_val_str and dynamic_masks_val_str.strip()))
        has_camera_control = camera_control_type_val and camera_control_type_val != "(Auto)"

        if has_mask and has_camera_control:
            errors.append(ValueError("Masks (static_mask, dynamic_masks) and Camera Controls cannot be used simultaneously."))

        cfg_scale_val = self.get_parameter_value("cfg_scale")
        if not (0 <= cfg_scale_val <= 1): # type: ignore[operator]
            errors.append(ValueError("cfg_scale must be between 0.0 and 1.0."))
        
        if dynamic_masks_val_str and dynamic_masks_val_str.strip():
            try:
                json.loads(dynamic_masks_val_str)
            except json.JSONDecodeError:
                errors.append(ValueError("Dynamic Masks 'dynamic_masks' is not a valid JSON string."))

        return errors if errors else None

    def process(self) -> AsyncResult:
        # Validate before yielding to ensure errors are caught early if possible
        validation_errors = self.validate_node()
        if validation_errors:
            # Concatenate error messages for a single exception
            error_message = "; ".join(str(e) for e in validation_errors)
            raise ValueError(f"Validation failed: {error_message}")
            
        def generate_video() -> VideoUrlArtifact:
            access_key = self.get_config_value(service=SERVICE, value=API_KEY_ENV_VAR)
            secret_key = self.get_config_value(service=SERVICE, value=SECRET_KEY_ENV_VAR)
            jwt_token = encode_jwt_token(access_key, secret_key) # type: ignore[arg-type]
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

            payload: dict[str, any] = {
                "model_name": self.get_parameter_value("model_name"),
                "duration": str(self.get_parameter_value("duration")), # Ensure string
                "cfg_scale": self.get_parameter_value("cfg_scale"),
                "mode": self.get_parameter_value("mode"),
            }

            image_api = self._get_image_api_data("image")
            if image_api:
                payload["image"] = image_api
            
            image_tail_api = self._get_image_api_data("image_tail")
            if image_tail_api:
                payload["image_tail"] = image_tail_api

            prompt_val = self.get_parameter_value("prompt")
            if prompt_val and prompt_val.strip():
                payload["prompt"] = prompt_val.strip()
            
            neg_prompt_val = self.get_parameter_value("negative_prompt")
            if neg_prompt_val and neg_prompt_val.strip():
                payload["negative_prompt"] = neg_prompt_val.strip()

            # Masks - mutually exclusive with camera control (checked in validate_node)
            static_mask_api = self._get_image_api_data("static_mask")
            if static_mask_api:
                payload["static_mask"] = static_mask_api
            
            dynamic_masks_str = self.get_parameter_value("dynamic_masks")
            if dynamic_masks_str and dynamic_masks_str.strip():
                try:
                    payload["dynamic_masks"] = json.loads(dynamic_masks_str)
                except json.JSONDecodeError as e: # Should be caught by validate_node
                    raise ValueError(f"Invalid JSON in dynamic_masks: {e}") from e


            # Camera Control - mutually exclusive with masks (checked in validate_node)
            camera_control_type_val = self.get_parameter_value("camera_control_type")
            if camera_control_type_val and camera_control_type_val != "(Auto)":
                cc_payload: dict[str, any] = {"type": camera_control_type_val}
                if camera_control_type_val == "simple":
                    simple_config = {}
                    # Ensure only non-zero values are added for 'simple' config, as per Kling docs
                    # (Though their doc says "Choose one out of the following six parameters, meaning only one parameter should be non-zero")
                    # For now, we add any non-zero param. User needs to ensure only one if that's a strict API rule.
                    for DoterraAction in ["horizontal", "vertical", "pan", "tilt", "roll", "zoom"]:
                        val = self.get_parameter_value(f"camera_config_{DoterraAction}")
                        if val != 0.0: # type: ignore[comparison-overlap]
                            simple_config[DoterraAction] = val
                    if not simple_config: # API might require config if type is simple
                         logger.warning("Camera control type is 'simple' but no config values are set (all are 0.0).")
                    cc_payload["config"] = simple_config if simple_config else None # API may expect null if empty
                else: # For "down_back", "forward_up", etc. config must be None/not sent.
                    cc_payload["config"] = None # Explicitly None as per Kling text2video example
                payload["camera_control"] = cc_payload
            
            callback_url_val = self.get_parameter_value("callback_url")
            if callback_url_val and callback_url_val.strip():
                payload["callback_url"] = callback_url_val.strip()

            external_task_id_val = self.get_parameter_value("external_task_id")
            if external_task_id_val and external_task_id_val.strip():
                payload["external_task_id"] = external_task_id_val.strip()
            
            logger.info(f"Kling Image-to-Video API Request Payload: {json.dumps(payload, indent=2)}")
            response = requests.post(BASE_URL, headers=headers, json=payload, timeout=30) 
            response.raise_for_status() # Raise HTTPError for bad responses (4XX or 5XX)
            
            task_id = response.json()["data"]["task_id"]
            poll_url = f"{BASE_URL}/{task_id}" # Assuming polling uses the same base and task_id pattern
            video_url = None

            # Polling logic copied from KlingAI_TextToVideo
            max_retries = 60  # e.g., 60 retries * 5 seconds = 5 minutes timeout
            retry_delay = 5  # seconds
            for attempt in range(max_retries):
                try:
                    time.sleep(retry_delay)
                    result_response = requests.get(poll_url, headers=headers, timeout=30)
                    result_response.raise_for_status()
                    result = result_response.json()
                    
                    status = result["data"]["task_status"]
                    logger.info(f"Kling video generation status (Task ID: {task_id}): {status} (Attempt {attempt + 1}/{max_retries})")

                    if status == "succeed":
                        video_url = result["data"]["task_result"]["videos"][0]["url"]
                        logger.info(f"Kling video generation succeeded: {video_url}")
                        break
                    if status == "failed":
                        error_msg = result["data"].get("task_status_msg", "Unknown error")
                        logger.error(f"Kling video generation failed: {error_msg}")
                        raise RuntimeError(f"Kling video generation failed: {error_msg}")
                    # Other statuses like 'processing', 'pending' mean continue polling

                except requests.exceptions.RequestException as e:
                    logger.warning(f"Polling request failed (Attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise RuntimeError(f"Failed to get video status after multiple retries: {e}") from e

            if not video_url:
                raise RuntimeError("Kling video generation task finished but no video URL was found or task timed out.")

            video_artifact = VideoUrlArtifact(url=video_url)
            self.publish_update_to_parameter("video_url", video_artifact)
            return video_artifact

        yield generate_video 