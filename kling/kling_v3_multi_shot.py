from typing import Any

from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
from griptape_nodes.exe_types.node_types import DataNode
from griptape_nodes.traits.widget import Widget


class KlingV3MultiShot(DataNode):
    """Multi-shot video node with a custom shot list editor for sequencing video shots."""

    DEFAULT_SHOTS = [{"name": "Shot1", "duration": 2, "description": ""}]

    def __init__(self, name: str, metadata: dict[str, Any] | None = None, **kwargs) -> None:
        node_metadata = {
            "category": "video/kling ai",
            "description": "Kling v3 multi-shot video node with custom shot editor",
        }
        if metadata:
            node_metadata.update(metadata)
        super().__init__(name=name, metadata=node_metadata, **kwargs)

        self.add_parameter(
            Parameter(
                name="start_frame",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageArtifact",
                tooltip="Starting frame for the video sequence",
                allowed_modes={ParameterMode.INPUT},
            )
        )

        self.add_parameter(
            Parameter(
                name="end_frame",
                input_types=["ImageArtifact", "ImageUrlArtifact"],
                type="ImageArtifact",
                tooltip="Ending frame for the video sequence",
                allowed_modes={ParameterMode.INPUT},
            )
        )

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

    def process(self) -> None:
        start_frame = self.parameter_values.get("start_frame")
        end_frame = self.parameter_values.get("end_frame")
        shots = self.parameter_values.get("shots", self.DEFAULT_SHOTS)

        total_duration = sum(shot.get("duration", 2) for shot in shots)
        print(
            f"KlingV3MultiShot - {len(shots)} shots, "
            f"total duration: {total_duration}s, "
            f"start_frame: {'set' if start_frame else 'none'}, "
            f"end_frame: {'set' if end_frame else 'none'}"
        )

        self.parameter_output_values["shots"] = shots
