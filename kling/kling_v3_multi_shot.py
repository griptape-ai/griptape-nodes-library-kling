import base64
import json
import time
from typing import Any

import jwt
import requests
from griptape.artifacts import ImageArtifact, ImageUrlArtifact, VideoUrlArtifact
from griptape_nodes.traits.options import Options
from griptape_nodes.traits.slider import Slider
from griptape_nodes.traits.widget import Widget

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.exe_types.param_types.parameter_image import ParameterImage
from griptape_nodes.retained_mode.griptape_nodes import logger, GriptapeNodes
from griptape_nodes.retained_mode.events.os_events import ExistingFilePolicy

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
IMAGE2VIDEO_URL = "https://api.klingai.com/v1/videos/image2video"
TEXT2VIDEO_URL = "https://api.klingai.com/v1/videos/text2video"


def encode_jwt_token(ak: str, sk: str) -> str:
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ak,
        "exp": int(time.time()) + 1800,
        "nbf": int(time.time()) - 5,
    }
    token = jwt.encode(payload, sk, algorithm="HS256", headers=headers)
    return token


class KlingV3MultiShot(ControlNode):
    """Multi-shot video node for Kling v3 with a custom shot list editor.

    Uses the multi_prompt API parameter to generate multi-shot video sequences
    where each shot has its own prompt and duration.
    """

    DEFAULT_SHOTS = [{"name": "Shot1", "duration": 3, "description": ""}]

    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {
            "category": "video/kling ai",
            "description": "Kling v3 multi-shot video generation with per-shot prompts and durations",
        }
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        # Image Inputs
        with ParameterGroup(name="Image Inputs") as image_group:
            ParameterImage(
                name="start_frame",
                tooltip="Starting frame image for the video sequence (required)",
                allow_output=False,
            )
            ParameterImage(
                name="end_frame",
                tooltip="Ending frame image (optional, not compatible with multi-prompt on some API versions)",
                allow_output=False,
            )
        self.add_node_element(image_group)

        # Shot List (custom widget)
        self.add_parameter(
            Parameter(
                name="shots",
                input_types=["list"],
                type="list",
                output_type="list",
                default_value=self.DEFAULT_SHOTS,
                tooltip="List of shots with name, duration, and description",
                allowed_modes={ParameterMode.PROPERTY, ParameterMode.OUTPUT},
                traits={Widget(name="MultiShotEditor", library="Kling AI Library")},
            )
        )

        # Generation Settings
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
                default_value="std",
                tooltip="Video generation mode (std: Standard, pro: Professional)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["std", "pro"])},
            )
            Parameter(
                name="aspect_ratio",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="16:9",
                tooltip="Aspect ratio of the generated video",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["16:9", "9:16", "1:1"])},
            )
            Parameter(
                name="negative_prompt",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="",
                tooltip="Negative text prompt — elements to avoid (max 2500 chars)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline": True},
            )
            Parameter(
                name="sound",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="off",
                tooltip="Generate native audio with the video",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["on", "off"])},
            )
            Parameter(
                name="polling_delay",
                input_types=["int"],
                output_type="int",
                type="int",
                default_value=10,
                tooltip="Delay in seconds between polling the Kling API for job completion.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Slider(min_val=5, max_val=30)},
                hide=True,
            )
        self.add_node_element(gen_settings_group)

        # Output
        self.add_parameter(
            Parameter(
                name="video_url",
                output_type="VideoUrlArtifact",
                type="VideoUrlArtifact",
                default_value=None,
                allowed_modes={ParameterMode.OUTPUT},
                tooltip="Output URL of the generated multi-shot video.",
                ui_options={"placeholder_text": "", "is_full_width": True},
            )
        )

    def _get_image_api_data(self, param_name: str) -> str | None:
        """Convert an image parameter to API-compatible format (URL or base64)."""
        image_input = self.parameter_values.get(param_name)
        if image_input is None:
            return None

        if isinstance(image_input, ImageUrlArtifact):
            return self._resolve_url(image_input.value)
        if isinstance(image_input, ImageArtifact):
            return image_input.base64
        if isinstance(image_input, dict):
            input_type = image_input.get("type")
            if input_type == "ImageUrlArtifact" and image_input.get("value"):
                return self._resolve_url(str(image_input["value"]))
            if input_type == "ImageArtifact" and image_input.get("base64"):
                return str(image_input["base64"])
            return None
        if isinstance(image_input, str) and image_input.strip():
            return self._resolve_url(image_input.strip())

        return None

    def _resolve_url(self, url_string: str) -> str:
        """Convert local URLs to base64, pass public URLs through."""
        if not url_string:
            return url_string

        if url_string.startswith("data:image"):
            try:
                return url_string.split(",", 1)[1]
            except Exception:
                return url_string

        is_local = "localhost" in url_string or "127.0.0.1" in url_string
        if is_local and url_string.startswith("http"):
            try:
                response = requests.get(url_string, timeout=10)
                response.raise_for_status()
                return base64.b64encode(response.content).decode("utf-8")
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch local URL for base64 conversion: {e}")
                return url_string

        return url_string

    def validate_node(self) -> list[Exception] | None:
        errors = []

        access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)
        if not access_key:
            errors.append(ValueError(f"Kling access key not found. Set {API_KEY_ENV_VAR}."))
        if not secret_key:
            errors.append(ValueError(f"Kling secret key not found. Set {SECRET_KEY_ENV_VAR}."))

        shots = self.parameter_values.get("shots", self.DEFAULT_SHOTS)
        if not shots:
            errors.append(ValueError("At least one shot is required."))
        else:
            total_duration = sum(shot.get("duration", 1) for shot in shots)
            if total_duration < 3:
                errors.append(ValueError(f"Total duration must be at least 3 seconds (currently {total_duration}s)."))
            if total_duration > 15:
                errors.append(ValueError(f"Total duration cannot exceed 15 seconds (currently {total_duration}s)."))

            has_any_description = any(shot.get("description", "").strip() for shot in shots)
            if not has_any_description:
                errors.append(ValueError("At least one shot must have a description."))

        cfg_scale = self.parameter_values.get("cfg_scale", 0.5)
        if not (0 <= cfg_scale <= 1):
            errors.append(ValueError("cfg_scale must be between 0.0 and 1.0."))

        return errors if errors else None

    def process(self) -> AsyncResult[None]:
        yield lambda: self._process()

    def _process(self):
        validation_errors = self.validate_node()
        if validation_errors:
            error_message = "; ".join(str(e) for e in validation_errors)
            raise ValueError(f"Validation failed: {error_message}")

        access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)
        jwt_token = encode_jwt_token(access_key, secret_key)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {jwt_token}"}

        # Build multi_prompt from shots (1-based index per API spec)
        shots = self.parameter_values.get("shots", self.DEFAULT_SHOTS)
        multi_prompt = []
        for i, shot in enumerate(shots):
            description = shot.get("description", "").strip()
            duration = shot.get("duration", 2)
            multi_prompt.append({
                "index": i + 1,
                "prompt": description,
                "duration": str(duration),
            })

        total_duration = sum(shot.get("duration", 1) for shot in shots)

        # Determine endpoint based on whether images are provided
        image_api = self._get_image_api_data("start_frame")
        image_tail_api = self._get_image_api_data("end_frame")
        has_images = image_api is not None

        if has_images:
            api_url = IMAGE2VIDEO_URL
        else:
            api_url = TEXT2VIDEO_URL

        logger.info(f"Using {'image2video' if has_images else 'text2video'} endpoint")

        # Build payload
        payload: dict[str, Any] = {
            "model_name": "kling-v3",
            "prompt": "",
            "multi_prompt": multi_prompt,
            "multi_shot": True,
            "shot_type": "customize",
            "duration": str(total_duration),
            "cfg_scale": self.parameter_values.get("cfg_scale", 0.5),
            "mode": self.parameter_values.get("mode", "std"),
        }

        # Image inputs (only for image2video)
        if image_api:
            payload["image"] = image_api
        if image_tail_api:
            payload["image_tail"] = image_tail_api

        # Optional parameters
        neg_prompt = self.parameter_values.get("negative_prompt", "")
        if neg_prompt and neg_prompt.strip():
            payload["negative_prompt"] = neg_prompt.strip()

        sound_val = self.parameter_values.get("sound", "off")
        if sound_val:
            payload["sound"] = sound_val

        aspect_ratio = self.parameter_values.get("aspect_ratio", "16:9")
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio

        # Log payload (redact base64 data)
        log_payload = payload.copy()
        for key in ["image", "image_tail"]:
            if key in log_payload and not log_payload[key].startswith(("http://", "https://")):
                log_payload[key] = f"<BASE64_DATA_LENGTH:{len(log_payload[key])}>"
        logger.info(f"Kling V3 Multi-Shot API Request Payload: {json.dumps(log_payload, indent=2)}")

        # Submit generation request
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        logger.info(f"Initial response status: {response.status_code}")
        logger.info(f"Initial response text: {response.text[:500]}")

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            logger.error(f"HTTP Error {response.status_code}: {response.text}")
            raise

        task_id = response.json()["data"]["task_id"]
        logger.info(f"Task created with ID: {task_id}")

        # Poll for completion
        poll_url = f"{api_url}/{task_id}"
        poll_delay = self.parameter_values.get("polling_delay", 10)
        max_retries = 120
        video_url = None

        for attempt in range(max_retries):
            time.sleep(poll_delay)

            try:
                result_response = requests.get(poll_url, headers=headers, timeout=30)
                result_response.raise_for_status()
                result = result_response.json()

                status = result["data"]["task_status"]
                logger.info(
                    f"Kling multi-shot generation status (Task {task_id}): "
                    f"{status} (attempt {attempt + 1}/{max_retries})"
                )

                if status == "succeed":
                    video_url = result["data"]["task_result"]["videos"][0]["url"]
                    logger.info(f"Video generation succeeded. URL: {video_url}")
                    break
                if status == "failed":
                    error_msg = result["data"].get("task_status_msg", "Unknown error")
                    raise RuntimeError(f"Kling multi-shot generation failed: {error_msg}")

            except requests.exceptions.RequestException as e:
                logger.warning(f"Polling request failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise RuntimeError(f"Failed to get video status after {max_retries} attempts: {e}") from e

        if not video_url:
            raise RuntimeError("Video generation timed out — no video URL received.")

        # Download and save to static storage
        try:
            download_response = requests.get(video_url, timeout=60)
            download_response.raise_for_status()
            video_bytes = download_response.content
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to download generated video: {e}") from e

        timestamp = int(time.time() * 1000)
        filename = f"kling_v3_multi_shot_{timestamp}.mp4"
        static_files_manager = GriptapeNodes.StaticFilesManager()
        saved_url = static_files_manager.save_static_file(video_bytes, filename, ExistingFilePolicy.CREATE_NEW)

        video_artifact = VideoUrlArtifact(saved_url)
        logger.info(f"Saved multi-shot video as {filename}. URL: {saved_url}")

        self.publish_update_to_parameter("video_url", video_artifact)

        return video_artifact
