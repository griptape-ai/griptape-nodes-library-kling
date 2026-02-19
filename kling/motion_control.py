import base64
import time
from typing import Any

import jwt
import requests
from griptape.artifacts import ImageArtifact, ImageUrlArtifact, VideoUrlArtifact
from griptape_nodes.exe_types.core_types import Parameter, ParameterGroup, ParameterMode
from griptape_nodes.exe_types.node_types import SuccessFailureNode
from griptape_nodes.exe_types.param_types.parameter_bool import ParameterBool
from griptape_nodes.exe_types.param_types.parameter_dict import ParameterDict
from griptape_nodes.exe_types.param_types.parameter_string import ParameterString
from griptape_nodes.files.file import File, FileLoadError
from griptape_nodes.retained_mode.events.os_events import ExistingFilePolicy
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes, logger
from griptape_nodes.traits.options import Options

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api.klingai.com/v1/videos/motion-control"

MAX_PROMPT_LENGTH = 2500
POLL_INTERVAL_SECONDS = 5
POLL_TIMEOUT_SECONDS = 1200


def encode_jwt_token(access_key: str, secret_key: str) -> str:
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": access_key,
        "exp": int(time.time()) + 1800,  # valid for 30 minutes
        "nbf": int(time.time()) - 5,  # valid 5 seconds ago
    }
    token = jwt.encode(payload, secret_key, algorithm="HS256", headers=headers)
    return token


class KlingAI_MotionControl(SuccessFailureNode):
    """Generate a video using Kling Motion Control.

    The Motion Control model transfers character actions from a reference video to a reference image,
    creating a new video where the character in the image performs the actions from the video.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.category = "AI/Kling"
        self.description = "Generates a video using Kling Motion Control (image + motion reference)."

        self.add_parameter(
            ParameterString(
                name="prompt",
                default_value="",
                tooltip="Optional text prompt for additional motion guidance (max 2500 chars)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={
                    "multiline": True,
                    "placeholder_text": "Optional: Add additional control with a text prompt...",
                    "display_name": "prompt",
                },
            )
        )

        # Image Input Group
        with ParameterGroup(name="Image Input") as image_group:
            Parameter(
                name="reference_image",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageUrlArtifact",
                tooltip="Reference image with character (required). Supports .jpg/.jpeg/.png, max 10MB.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        self.add_node_element(image_group)

        # Video Input Group
        with ParameterGroup(name="Video Input") as video_group:
            Parameter(
                name="reference_video",
                input_types=["VideoUrlArtifact"],
                type="VideoUrlArtifact",
                tooltip="Reference video with actions to transfer (required). Supports .mp4/.mov, max 100MB.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        self.add_node_element(video_group)

        # Generation Settings Group
        with ParameterGroup(name="Generation Settings") as gen_settings_group:
            ParameterBool(
                name="keep_original_sound",
                default_value=True,
                tooltip="Keep original video sound",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"display_name": "keep original sound"},
            )
            ParameterString(
                name="character_orientation",
                default_value="video",
                tooltip=(
                    "Character orientation: 'image' matches image orientation (max 10s video), "
                    "'video' matches video orientation (max 30s video)"
                ),
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["image", "video"])},
                ui_options={"display_name": "character orientation"},
            )
            ParameterString(
                name="mode",
                default_value="pro",
                tooltip="Video generation mode: 'std' (Standard - cost-effective), 'pro' (Professional - higher quality)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["std", "pro"])},
            )
        self.add_node_element(gen_settings_group)

        # Outputs
        self.add_parameter(
            ParameterString(
                name="generation_id",
                tooltip="Kling task id",
                allowed_modes={ParameterMode.OUTPUT},
                hide=True,
            )
        )
        self.add_parameter(
            ParameterDict(
                name="provider_response",
                tooltip="Verbatim response from API (latest polling response)",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"hide_property": True},
                hide=True,
            )
        )
        self.add_parameter(
            Parameter(
                name="video_url",
                output_type="VideoUrlArtifact",
                type="VideoUrlArtifact",
                tooltip="Saved video as URL artifact for downstream display",
                allowed_modes={ParameterMode.OUTPUT, ParameterMode.PROPERTY},
                settable=False,
                ui_options={"pulse_on_run": True},
            )
        )
        self.add_parameter(
            ParameterString(
                name="kling_video_id",
                tooltip="The video ID from Kling AI",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"placeholder_text": "The Kling AI video ID"},
            )
        )

        self._create_status_parameters(
            result_details_tooltip="Details about the video generation result or any errors",
            result_details_placeholder="Generation status and details will appear here.",
            parameter_group_initially_collapsed=True,
        )

    def process(self) -> None:
        self._clear_execution_status()
        try:
            self._process()
        except Exception as exc:
            self._set_safe_defaults()
            self._set_status_results(was_successful=False, result_details=str(exc))
            self._handle_failure_exception(exc)

    def _process(self) -> None:
        api_token = self._get_api_token()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_token}"}

        params = self._get_parameters()
        prompt = params["prompt"]
        if len(prompt) > MAX_PROMPT_LENGTH:
            self._set_safe_defaults()
            error_msg = f"{self.name} prompt exceeds {MAX_PROMPT_LENGTH} characters (got: {len(prompt)})."
            self._set_status_results(was_successful=False, result_details=error_msg)
            logger.error("%s validation failed: prompt too long", self.name)
            return

        if not params["image_url"]:
            self._set_safe_defaults()
            error_msg = f"{self.name} requires a reference image."
            self._set_status_results(was_successful=False, result_details=error_msg)
            logger.error("%s validation failed: missing reference image", self.name)
            return

        if not params["video_url"]:
            self._set_safe_defaults()
            error_msg = f"{self.name} requires a reference video."
            self._set_status_results(was_successful=False, result_details=error_msg)
            logger.error("%s validation failed: missing reference video", self.name)
            return

        payload = self._build_payload(params)
        task_id = self._submit_request(payload, headers)
        if not task_id:
            self._set_safe_defaults()
            self._set_status_results(
                was_successful=False,
                result_details="No task_id returned from API. Cannot proceed with generation.",
            )
            return

        self._poll_for_result(task_id, headers)

    def _get_api_token(self) -> str:
        access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)
        if not access_key:
            raise ValueError(f"{self.name} is missing {API_KEY_ENV_VAR}. Ensure it's set in the environment/config.")
        if not secret_key:
            raise ValueError(f"{self.name} is missing {SECRET_KEY_ENV_VAR}. Ensure it's set in the environment/config.")
        return encode_jwt_token(access_key, secret_key)

    def _get_parameters(self) -> dict[str, Any]:
        prompt = self.get_parameter_value("prompt")
        if prompt is None:
            prompt = ""

        image_url = self._get_image_payload("reference_image")
        video_url = self._get_video_payload("reference_video")

        keep_sound = self.get_parameter_value("keep_original_sound")
        if keep_sound is None:
            keep_sound = True

        character_orientation = self.get_parameter_value("character_orientation")
        if not character_orientation:
            character_orientation = "video"

        mode = self.get_parameter_value("mode")
        if not mode:
            mode = "pro"

        keep_sound_value = "yes"
        if not keep_sound:
            keep_sound_value = "no"

        return {
            "prompt": str(prompt).strip(),
            "image_url": image_url,
            "video_url": video_url,
            "keep_original_sound": keep_sound_value,
            "character_orientation": character_orientation,
            "mode": mode,
        }

    def _get_image_payload(self, param_name: str) -> str | None:
        image_input = self.get_parameter_value(param_name)
        if not image_input:
            return None

        if isinstance(image_input, ImageArtifact):
            return image_input.base64
        if isinstance(image_input, ImageUrlArtifact):
            return self._resolve_image_url(image_input.value)
        if isinstance(image_input, dict):
            input_type = image_input.get("type")
            input_value = image_input.get("value")
            input_base64 = image_input.get("base64")
            if input_type == "ImageArtifact" and input_base64:
                return str(input_base64)
            if input_value:
                return self._resolve_image_url(str(input_value))
            return None
        if isinstance(image_input, str):
            return self._resolve_image_url(image_input.strip())

        return None

    def _resolve_image_url(self, url_string: str) -> str:
        if not url_string:
            return url_string

        if url_string.startswith("data:image"):
            try:
                return url_string.split(",", 1)[1]
            except ValueError:
                return url_string

        is_local_http = "localhost" in url_string or "127.0.0.1" in url_string
        is_relative_static = url_string.startswith("/static/")
        if is_local_http or is_relative_static:
            try:
                response = requests.get(url_string, timeout=10)
                response.raise_for_status()
                return base64.b64encode(response.content).decode("utf-8")
            except requests.exceptions.RequestException as exc:
                logger.warning("Failed to load local image URL %s: %s", url_string, exc)
                return url_string

        return url_string

    def _get_video_payload(self, param_name: str) -> str | None:
        video_input = self.get_parameter_value(param_name)
        if not video_input:
            return None

        if isinstance(video_input, VideoUrlArtifact):
            return video_input.value
        if isinstance(video_input, dict):
            value = video_input.get("value")
            if value:
                return str(value)
            return None
        if isinstance(video_input, str):
            stripped_value = video_input.strip()
            if stripped_value:
                return stripped_value
            return None

        return None

    def _build_payload(self, params: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "image_url": params["image_url"],
            "video_url": params["video_url"],
            "keep_original_sound": params["keep_original_sound"],
            "character_orientation": params["character_orientation"],
            "mode": params["mode"],
        }

        if params["prompt"]:
            payload["prompt"] = params["prompt"]

        return payload

    def _submit_request(self, payload: dict[str, Any], headers: dict[str, str]) -> str:
        logger.info("Submitting Kling Motion Control request")
        response = requests.post(BASE_URL, headers=headers, json=payload, timeout=30)

        logger.info("Kling Motion Control response status: %s", response.status_code)
        logger.debug("Kling Motion Control response headers: %s", dict(response.headers))

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            error_msg = f"{self.name} request failed: HTTP {response.status_code} - {response.text}"
            raise RuntimeError(error_msg) from exc

        try:
            response_json = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{self.name} received invalid JSON response: {exc}") from exc

        task_id = str(response_json.get("data", {}).get("task_id") or "")
        if not task_id:
            logger.error("No task_id returned from POST response: %s", response_json)
            return ""

        self.parameter_output_values["generation_id"] = task_id
        return task_id

    def _poll_for_result(self, task_id: str, headers: dict[str, str]) -> None:
        poll_url = f"{BASE_URL}/{task_id}"
        start_time = time.monotonic()
        attempt = 0

        while True:
            if time.monotonic() - start_time > POLL_TIMEOUT_SECONDS:
                self._handle_polling_timeout()
                return

            time.sleep(POLL_INTERVAL_SECONDS)
            attempt += 1

            try:
                status_resp = requests.get(poll_url, headers=headers, timeout=30)
                status_resp.raise_for_status()
            except requests.exceptions.RequestException as exc:
                self._handle_polling_error(exc)
                return

            try:
                status_json = status_resp.json()
            except ValueError as exc:
                error_msg = f"Invalid JSON response during polling: {exc}"
                self._set_status_results(was_successful=False, result_details=error_msg)
                self._handle_failure_exception(RuntimeError(error_msg))
                return

            self.parameter_output_values["provider_response"] = status_json
            logger.info("%s polling attempt #%d", self.name, attempt)

            status = status_json.get("data", {}).get("task_status", "")
            if status == "succeed":
                self._handle_completion(status_json, task_id)
                return
            if status == "failed":
                error_msg = status_json.get("data", {}).get("task_status_msg", "Kling motion control failed.")
                self.parameter_output_values["video_url"] = None
                self._set_status_results(was_successful=False, result_details=error_msg)
                return

    def _handle_completion(self, response_json: dict[str, Any], task_id: str) -> None:
        videos = response_json.get("data", {}).get("task_result", {}).get("videos", [])
        if not videos or not isinstance(videos, list):
            self.parameter_output_values["video_url"] = None
            self._set_status_results(
                was_successful=False,
                result_details=f"{self.name} generation completed but no videos found in response.",
            )
            return

        video_info = videos[0]
        download_url = video_info.get("url")
        video_id = video_info.get("id")

        if not download_url:
            self.parameter_output_values["video_url"] = None
            self._set_status_results(
                was_successful=False,
                result_details=f"{self.name} generation completed but no download URL found in response.",
            )
            return

        if video_id:
            self.parameter_output_values["kling_video_id"] = video_id

        try:
            video_bytes = File(download_url).read_bytes()
        except FileLoadError as exc:
            logger.warning("%s failed to download video: %s", self.name, exc)
            self.parameter_output_values["video_url"] = VideoUrlArtifact(download_url)
            self._set_status_results(
                was_successful=True,
                result_details="Video generated successfully. Using provider URL (could not download video bytes).",
            )
            return

        filename = f"kling_motion_control_{task_id}.mp4"
        static_files_manager = GriptapeNodes.StaticFilesManager()
        try:
            saved_url = static_files_manager.save_static_file(video_bytes, filename, ExistingFilePolicy.CREATE_NEW)
        except (OSError, PermissionError) as exc:
            logger.warning("%s failed to save to static storage: %s", self.name, exc)
            self.parameter_output_values["video_url"] = VideoUrlArtifact(download_url)
            self._set_status_results(
                was_successful=True,
                result_details=(
                    "Video generated successfully. Using provider URL (could not save to static storage)."
                ),
            )
            return

        self.parameter_output_values["video_url"] = VideoUrlArtifact(saved_url)
        self._set_status_results(
            was_successful=True,
            result_details=f"Video generated successfully and saved as {filename}.",
        )

    def _handle_polling_timeout(self) -> None:
        self.parameter_output_values["video_url"] = None
        self._set_status_results(
            was_successful=False,
            result_details="Video generation timed out after 1200 seconds waiting for result.",
        )

    def _handle_polling_error(self, exc: Exception) -> None:
        error_msg = f"Failed to poll generation status: {exc}"
        self._set_status_results(was_successful=False, result_details=error_msg)
        self._handle_failure_exception(RuntimeError(error_msg))

    def _set_safe_defaults(self) -> None:
        self.parameter_output_values["generation_id"] = ""
        self.parameter_output_values["provider_response"] = None
        self.parameter_output_values["video_url"] = None
        self.parameter_output_values["kling_video_id"] = ""

    def validate_before_workflow_run(self) -> list[Exception] | None:
        exceptions = []
        access_key = GriptapeNodes.SecretsManager().get_secret(API_KEY_ENV_VAR)
        secret_key = GriptapeNodes.SecretsManager().get_secret(SECRET_KEY_ENV_VAR)
        if not access_key:
            exceptions.append(KeyError(f"{self.name}: {API_KEY_ENV_VAR} is not configured"))
        if not secret_key:
            exceptions.append(KeyError(f"{self.name}: {SECRET_KEY_ENV_VAR} is not configured"))
        return exceptions if exceptions else None
