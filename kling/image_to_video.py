import time
import jwt
import requests
import json
import base64
from griptape.artifacts import ImageArtifact, ImageUrlArtifact, VideoUrlArtifact
from griptape_nodes.traits.options import Options

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger, GriptapeNodes

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api.klingai.com/v1/videos/image2video" # Global endpoint per latest docs


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

        # Model Selection (at top)
        self.add_parameter(
            Parameter(
                name="model_name",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="kling-v2-1",
                tooltip="Model Name for generation.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["kling-v1", "kling-v1-5", "kling-v2-master", "kling-v2-1", "kling-v2-1-master", "kling-v2-5-turbo"])},
                ui_options={"display_name": "Model"}
            )
        )

        # Image Inputs Group
        with ParameterGroup(name="Image Inputs") as image_group:
            Parameter(
                name="image",
                input_types=["ImageArtifact", "ImageUrlArtifact", "str"],
                type="ImageArtifact",
                tooltip="Reference Image (start frame) - required. Input ImageArtifact, ImageUrlArtifact, direct URL string, or Base64 string.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Start Frame"}
            )
            Parameter(
                name="image_tail",
                input_types=["ImageArtifact", "ImageUrlArtifact", "str"],
                type="ImageArtifact",
                tooltip="Tail/End Frame image (optional). Supported on kling-v2-1 with pro mode (5s/10s). Accepts ImageArtifact, ImageUrlArtifact, URL, or Base64.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "Tail Frame"}
            )
        self.add_node_element(image_group)
        


        # Prompts Group
        with ParameterGroup(name="Prompts") as prompts_group:
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
        with ParameterGroup(name="Generation Settings") as gen_settings_group:
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
                default_value="pro",
                tooltip="Video generation mode (std: Standard, pro: Professional). Start/End frame requires pro on kling-v2-1.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["std", "pro"])}
            )
            Parameter(
                name="duration",
                input_types=["int"],
                output_type="int",
                type="int",
                default_value=5,
                tooltip="Video Length in seconds.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=[5, 10])}
            )
        self.add_node_element(gen_settings_group)

        # Masks Group
        with ParameterGroup(name="Masks") as masks_group:
            Parameter(
                name="static_mask",
                input_types=["ImageArtifact", "ImageUrlArtifact", "str"],
                type="ImageArtifact",
                default_value=None,
                tooltip="Static Brush Application Area. Input ImageArtifact, ImageUrlArtifact, direct URL, or Base64 string.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="dynamic_masks",
                input_types=["str"],
                type="str",
                default_value=None,
                tooltip="JSON string for Dynamic Brush Configuration List. Masks within JSON must be URL/Base64.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True, "placeholder_text": "Enter JSON for dynamic masks..."},
            )
        masks_group.ui_options = {"hide": True}
        self.add_node_element(masks_group)
        # Callback Parameters Group (similar to text2video)
        with ParameterGroup(name="Callback") as callback_group:
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
                ui_options={"placeholder_text": ""}
            )
        )

    def _get_image_api_data_from_input(self, image_input) -> str | None:
        """Convert a single image input to API format"""

        # Helper to convert URL to Base64 if it's local
        def resolve_url_to_data(url_string: str) -> str:
            if not url_string: # Ensure url_string is not None or empty before checks
                return url_string
                
            # Check for localhost or relative /static/ paths common in local dev
            is_local_http = "localhost" in url_string or "127.0.0.1" in url_string
            is_relative_static = url_string.startswith("/static/")

            if is_local_http and url_string.startswith("http"):
                try:
                    logger.info(f"_get_image_api_data: Converting local URL {url_string} to Base64.")
                    response = requests.get(url_string, timeout=10) # Fetch content from local URL
                    response.raise_for_status()
                    return base64.b64encode(response.content).decode('utf-8') # Return Base64
                except requests.exceptions.RequestException as e:
                    logger.error(f"_get_image_api_data: Failed to fetch local URL {url_string} for Base64 conversion: {e}")
                    return url_string # Fallback: send original URL, API will likely fail
            elif is_relative_static:
                logger.warning(f"_get_image_api_data: Relative URL {url_string} provided. Sending as-is. Kling API requires a public URL or Base64.")
                return url_string # Send as-is, likely problematic for API
            
            return url_string # Return public URL or pre-formatted Base64 string as is

        if isinstance(image_input, ImageUrlArtifact):
            return resolve_url_to_data(image_input.value) # Process URL from artifact
        elif isinstance(image_input, ImageArtifact): # Already Base64
            return image_input.base64
        elif isinstance(image_input, dict):
            logger.info(f"_get_image_api_data: received dict: {image_input}")
            input_type = image_input.get("type")
            url_from_dict = image_input.get("value")
            base64_from_dict = image_input.get("base64")

            if input_type == "ImageUrlArtifact" and url_from_dict:
                return resolve_url_to_data(str(url_from_dict)) # Process URL from dict
            elif input_type == "ImageArtifact" and base64_from_dict:
                return str(base64_from_dict) # Return Base64 from dict
            
            logger.warning(f"_get_image_api_data: received unhandled dict structure: {image_input}")
            return None
        elif isinstance(image_input, str) and image_input.strip():
             # If it's a raw string, it could be a public URL, Base64, or a local URL.
            return resolve_url_to_data(image_input.strip())
        
        return None

    def _get_image_api_data(self, param_name: str) -> str | None:
        """Get image API data from parameter name"""
        image_input = self.get_parameter_value(param_name)
        return self._get_image_api_data_from_input(image_input)

    def validate_node(self) -> list[Exception] | None:
        errors = []
        access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)

        if not access_key:
            errors.append(ValueError(f"Kling access key not found. Set {API_KEY_ENV_VAR}."))
        if not secret_key:
            errors.append(ValueError(f"Kling secret key not found. Set {SECRET_KEY_ENV_VAR}."))

        # Validate images
        image_val = self._get_image_api_data("image")
        
        logger.info(f"KlingAI_ImageToVideo validate_node: image present: {bool(image_val)}")
        
        if not image_val:
            errors.append(ValueError("Start frame image must be provided."))

        # Minimal validation - UI should prevent most issues
        model = self.get_parameter_value("model_name")
        mode = self.get_parameter_value("mode")
        duration = self.get_parameter_value("duration")
        
        # Only validate if somehow invalid combinations slip through UI
        if model == "kling-v1" and duration != 5:
            errors.append(ValueError("kling-v1 only supports 5s duration"))
        if model in ["kling-v1-5"] and mode != "pro":
            errors.append(ValueError(f"{model} only supports pro mode"))
        if model == "kling-v2-5-turbo":
            if mode != "pro":
                errors.append(ValueError("kling-v2-5-turbo only supports pro mode"))
            if duration not in [5, 10]:
                errors.append(ValueError("kling-v2-5-turbo only supports durations 5 or 10 seconds"))

        cfg_scale_val = self.get_parameter_value("cfg_scale")
        if not (0 <= cfg_scale_val <= 1): # type: ignore[operator]
            errors.append(ValueError("cfg_scale must be between 0.0 and 1.0."))
        
        dynamic_masks_val_str = self.get_parameter_value("dynamic_masks")
        if dynamic_masks_val_str and dynamic_masks_val_str.strip():
            try:
                json.loads(dynamic_masks_val_str)
            except json.JSONDecodeError:
                errors.append(ValueError("Dynamic Masks 'dynamic_masks' is not a valid JSON string."))

        # Enforce end-frame support rules per v2.1 docs
        image_tail_val = self._get_image_api_data("image_tail")
        if image_tail_val:
            if model != "kling-v2-1" or mode != "pro" or duration not in [5, 10]:
                errors.append(
                    ValueError(
                        "image_tail is only supported on model kling-v2-1 with mode=pro and duration 5 or 10."
                    )
                )

        return errors if errors else None

    def process(self) -> AsyncResult[None]:
        yield lambda: self._process()
    
    def _process(self):
        # Validate before processing
        validation_errors = self.validate_node()
        if validation_errors:
            # Concatenate error messages for a single exception
            error_message = "; ".join(str(e) for e in validation_errors)
            raise ValueError(f"Validation failed: {error_message}")
            
        def generate_video() -> VideoUrlArtifact:
            access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
            secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)
            jwt_token = encode_jwt_token(access_key, secret_key) # type: ignore[arg-type]
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

            # Log all parameter values for debugging
            model_name = self.get_parameter_value("model_name")
            duration = self.get_parameter_value("duration")
            cfg_scale = self.get_parameter_value("cfg_scale")
            mode = self.get_parameter_value("mode")
            
            logger.info(f"DEBUG: Parameter values - model_name: {model_name}, duration: {duration}, cfg_scale: {cfg_scale}, mode: {mode}")

            payload: dict[str, any] = {
                "model_name": model_name,
                "duration": duration,
                "cfg_scale": cfg_scale,
                "mode": mode,
            }

            image_api = self._get_image_api_data("image")
            
            logger.info(f"DEBUG: Image data - image_api present: {bool(image_api)}")
            if image_api:
                logger.info(f"DEBUG: image_api length: {len(image_api) if image_api else 0}")
                # Check if it's a URL or Base64
                if image_api.startswith(('http://', 'https://')):
                    logger.info(f"DEBUG: image_api is URL: {image_api}")
                else:
                    logger.info(f"DEBUG: image_api is Base64 data (length: {len(image_api)})")
                payload["image"] = image_api

            image_tail_api = self._get_image_api_data("image_tail")
            logger.info(f"DEBUG: Image data - image_tail_api present: {bool(image_tail_api)}")
            if image_tail_api:
                logger.info(f"DEBUG: image_tail_api length: {len(image_tail_api) if image_tail_api else 0}")
                if image_tail_api.startswith(('http://', 'https://')):
                    logger.info(f"DEBUG: image_tail_api is URL: {image_tail_api}")
                else:
                    logger.info(f"DEBUG: image_tail_api is Base64 data (length: {len(image_tail_api)})")
                payload["image_tail"] = image_tail_api

            prompt_val = self.get_parameter_value("prompt")
            neg_prompt_val = self.get_parameter_value("negative_prompt")
            
            logger.info(f"DEBUG: Prompts - prompt: '{prompt_val}', negative_prompt: '{neg_prompt_val}'")
            
            if prompt_val and prompt_val.strip():
                payload["prompt"] = prompt_val.strip()
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
            
            callback_url_val = self.get_parameter_value("callback_url")
            if callback_url_val and callback_url_val.strip():
                payload["callback_url"] = callback_url_val.strip()

            external_task_id_val = self.get_parameter_value("external_task_id")
            if external_task_id_val and external_task_id_val.strip():
                payload["external_task_id"] = external_task_id_val.strip()
            
            # Log payload without Base64 data to avoid terminal spam
            log_payload = payload.copy()
            if "image" in log_payload and not log_payload["image"].startswith(('http://', 'https://')):
                log_payload["image"] = f"<BASE64_DATA_LENGTH:{len(log_payload['image'])}>"
            if "static_mask" in log_payload and not log_payload["static_mask"].startswith(('http://', 'https://')):
                log_payload["static_mask"] = f"<BASE64_DATA_LENGTH:{len(log_payload['static_mask'])}>"
            if "image_tail" in log_payload and not log_payload["image_tail"].startswith(('http://', 'https://')):
                log_payload["image_tail"] = f"<BASE64_DATA_LENGTH:{len(log_payload['image_tail'])}>"
            
            logger.info(f"Kling Image-to-Video API Request Payload: {json.dumps(log_payload, indent=2)}")
            response = requests.post(BASE_URL, headers=headers, json=payload, timeout=30)
            # Enhanced debugging for API errors
            logger.info(f"Initial response status: {response.status_code}")
            logger.info(f"Initial response headers: {dict(response.headers)}")
            logger.info(f"Initial response text: {response.text}")
            try:
                response.raise_for_status() # Raise HTTPError for bad responses (4XX or 5XX)
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP Error {response.status_code}: {response.text}")
                if response.status_code == 400:
                    try:
                        error_data = response.json()
                        logger.error(f"API Error Details: {json.dumps(error_data, indent=2)}")
                    except json.JSONDecodeError:
                        logger.error("Could not parse error response as JSON")
                raise

            task_id = response.json()["data"]["task_id"]

            poll_url = f"{BASE_URL}/{task_id}" # Assuming polling uses the same base and task_id pattern
            video_url = None
            actual_video_id = None # Initialize variable to store the actual video ID

            # Polling logic copied from KlingAI_TextToVideo
            max_retries = 120  # e.g., 120 retries * 5 seconds = 10 minutes timeout
            retry_delay = 5  # seconds
            for attempt in range(max_retries):
                try:
                    time.sleep(retry_delay)
                    result_response = requests.get(poll_url, headers=headers, timeout=30)
                    result_response.raise_for_status()
                    result = result_response.json()
                    
                    status = result["data"]["task_status"]
                    logger.info(f"Kling video generation status (Task ID: {task_id}): {status} (Attempt {attempt + 1}/{max_retries})")
                    
                    # Log full response for debugging on first few attempts
                    if attempt < 3:
                        logger.debug(f"Full API response (attempt {attempt + 1}): {json.dumps(result, indent=2)}")

                    if status == "succeed":
                        logger.info(f"Kling video generation succeeded. Full response: {json.dumps(result, indent=2)}")
                        try:
                            video_url = result["data"]["task_result"]["videos"][0]["url"]
                            actual_video_id = result["data"]["task_result"]["videos"][0]["id"] # Extract the correct video ID
                            logger.info(f"Extracted video URL: {video_url}, video ID: {actual_video_id}")
                        except (KeyError, IndexError, TypeError) as e:
                            logger.error(f"Failed to extract video URL from response: {e}")
                            logger.error(f"Response structure: {json.dumps(result, indent=2)}")
                            raise RuntimeError(f"Failed to extract video URL from API response: {e}") from e
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
                logger.error(f"Polling completed but no video URL found. Final status may not have been 'succeed'. Task ID: {task_id}")
                raise RuntimeError("Kling video generation task finished but no video URL was found or task timed out.")

            # Download the generated video and save to static storage
            try:
                download_response = requests.get(video_url, timeout=60)
                download_response.raise_for_status()
                video_bytes = download_response.content
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"Failed to download generated video: {e}") from e

            filename = f"kling_image_to_video_{int(time.time())}.mp4"
            static_files_manager = GriptapeNodes.StaticFilesManager()
            saved_url = static_files_manager.save_static_file(video_bytes, filename)

            # Create VideoUrlArtifact from the saved URL
            video_artifact = VideoUrlArtifact(saved_url)
            self.publish_update_to_parameter("video_url", video_artifact)
            if actual_video_id: # Publish the correct video ID if found
                self.publish_update_to_parameter("video_id", actual_video_id)
            logger.info(f"Saved video to static storage as {filename}. URL: {saved_url}")
            logger.info(f"Video ID: {actual_video_id}") # Added logging for actual_video_id
            return video_artifact

        return generate_video()

    def after_value_set(self, parameter: Parameter, value: any, modified_parameters_set: set[str] | None = None) -> None:
        """Update parameter visibility based on model selection."""
        if parameter.name == "model_name":
            # Show mask features for all models
            self.show_parameter_by_name(["static_mask", "dynamic_masks"])
            
            # Model-specific UI restrictions
            if value == "kling-v1":
                # kling-v1: only 5s duration, std or pro mode
                self.show_parameter_by_name("mode")
                self.hide_parameter_by_name("duration")
                current_duration = self.get_parameter_value("duration")
                if current_duration != 5:
                    self.set_parameter_value("duration", 5)
            elif value in ["kling-v1-5"]:
                # kling-v1-5: only pro mode, either duration
                self.hide_parameter_by_name("mode")
                self.show_parameter_by_name("duration")
                current_mode = self.get_parameter_value("mode")
                if current_mode != "pro":
                    self.set_parameter_value("mode", "pro")
            elif value == "kling-v2-5-turbo":
                # v2.5 turbo: pro-only, durations 5 or 10
                self.hide_parameter_by_name("mode")
                self.show_parameter_by_name("duration")
                current_mode = self.get_parameter_value("mode")
                if current_mode != "pro":
                    self.set_parameter_value("mode", "pro")
            else:
                # kling-v2+: all modes and durations available
                self.show_parameter_by_name(["mode", "duration"])
                
            # Add all potentially modified parameters to the set if provided
            if modified_parameters_set is not None:
                modified_parameters_set.update(["static_mask", "dynamic_masks", "mode", "duration"]) 