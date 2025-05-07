import time
import jwt
import requests
from griptape.artifacts import TextArtifact, UrlArtifact
from griptape_nodes.traits.options import Options

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode, ParameterGroup
from griptape_nodes.exe_types.node_types import AsyncResult, ControlNode
from griptape_nodes.retained_mode.griptape_nodes import logger

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105
BASE_URL = "https://api.klingai.com/v1/videos/text2video"

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
                default_value="kling-v1",
                tooltip="Model Name",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["kling-v1", "kling-v1-6"])},
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
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="5",
                tooltip="Video Length, unit: s (seconds)",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["5", "10"])}
            )
        )
        # Callback Parameters Group
        with ParameterGroup(group_name="Callback") as callback_group:
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
        callback_group.ui_options = {"hide": True} # Collapse by default
        self.add_node_element(callback_group)
        # Camera Control Parameters Group
        with ParameterGroup(group_name="Camera Controls") as camera_group:
            Parameter(
                name="camera_control_type",
                input_types=["str"],
                output_type="str",
                type="str",
                default_value="(Auto)",
                tooltip="Predefined camera movement type. Select (Auto) for model default. If 'simple', ensure only one config value is non-zero.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                traits={Options(choices=["(Auto)", "simple", "down_back", "forward_up", "right_turn_forward", "left_turn_forward"])}
            )
            Parameter(
                name="camera_config_horizontal",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.0,
                tooltip="Horizontal movement (-10 to 10). Use if camera_control_type is 'simple'.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="camera_config_vertical",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.0,
                tooltip="Vertical movement (-10 to 10). Use if camera_control_type is 'simple'.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="camera_config_pan",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.0,
                tooltip="Pan (rotation around x-axis, -10 to 10). Use if camera_control_type is 'simple'.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="camera_config_tilt",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.0,
                tooltip="Tilt (rotation around y-axis, -10 to 10). Use if camera_control_type is 'simple'.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="camera_config_roll",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.0,
                tooltip="Roll (rotation around z-axis, -10 to 10). Use if camera_control_type is 'simple'.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
            Parameter(
                name="camera_config_zoom",
                input_types=["float"],
                output_type="float",
                type="float",
                default_value=0.0,
                tooltip="Zoom (-10 to 10). Use if camera_control_type is 'simple'.",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
            )
        camera_group.ui_options = {"hide": True} # Collapse by default
        self.add_node_element(camera_group)
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
        """Validates that the Kling API keys are configured.
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

        return errors if errors else None

    def process(self) -> AsyncResult:
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

            camera_control_type_val = self.get_parameter_value("camera_control_type")
            if camera_control_type_val and camera_control_type_val != "(Auto)":
                cc_payload = {"type": camera_control_type_val}
                if camera_control_type_val == "simple":
                    simple_config = {}
                    cam_h = self.get_parameter_value("camera_config_horizontal")
                    if cam_h != 0.0: simple_config["horizontal"] = cam_h
                    cam_v = self.get_parameter_value("camera_config_vertical")
                    if cam_v != 0.0: simple_config["vertical"] = cam_v
                    cam_p = self.get_parameter_value("camera_config_pan")
                    if cam_p != 0.0: simple_config["pan"] = cam_p
                    cam_t = self.get_parameter_value("camera_config_tilt")
                    if cam_t != 0.0: simple_config["tilt"] = cam_t
                    cam_r = self.get_parameter_value("camera_config_roll")
                    if cam_r != 0.0: simple_config["roll"] = cam_r
                    cam_z = self.get_parameter_value("camera_config_zoom")
                    if cam_z != 0.0: simple_config["zoom"] = cam_z
                    cc_payload["config"] = simple_config
                else:
                    cc_payload["config"] = None
                payload["camera_control"] = cc_payload
            
            response = requests.post(BASE_URL, headers=headers, json=payload)  # noqa: S113 Collin is this ok to ignore?
            response.raise_for_status()
            task_id = response.json()["data"]["task_id"]

            poll_url = f"{BASE_URL}/{task_id}"
            video_url = None
            actual_video_id = None # Initialize variable to store the actual video ID

            while True:
                time.sleep(3)
                result = requests.get(poll_url, headers=headers).json()  # noqa: S113 Collin is this ok to ignore?
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

            self.publish_update_to_parameter("video_url", VideoUrlArtifact(video_url))
            if actual_video_id: # Publish the correct video ID if found
                self.publish_update_to_parameter("video_id", actual_video_id)
            logger.info(f"Video URL: {video_url}")
            logger.info(f"Video ID: {actual_video_id}")
            return VideoUrlArtifact(video_url)

        yield generate_video 