from griptape_nodes.exe_types.node_types import ControlNode
from griptape_nodes.exe_types.core_types import Parameter, ParameterMode
import openai
from griptape.structures import Agent
from griptape.utils import Stream
from griptape.events import TextChunkEvent

class OpenAIChat(ControlNode):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self.category = "ControlNodes"
        self.description = "An example node with dependencies"
        self.add_parameter(
            Parameter(
                name="prompt",
                input_types=["str"],
                type="str",
                default_value = "Hey! What's up?",
                tooltip="The prompt to call an agent",
                allowed_modes={ParameterMode.INPUT, ParameterMode.PROPERTY},
                ui_options={"multiline":True}
            )
        )
        self.add_parameter(
            Parameter(
                name="output",
                output_type="str",
                tooltip="The output from the agent",
                allowed_modes={ParameterMode.OUTPUT},
                ui_options={"multiline":True,"placeholder_text":"The agent response"}
            )
        )

    # This node makes a call to OpenAI, so it has a dependency. We have to define that method to properly catch it.
    def validate_node(self) -> list[Exception] | None:
        # All env values are stored in the SecretsManager. Check if they exist using this method.
        exceptions = []
        try:
            api_key = self.get_config_value(service="OpenAI", value="OPENAI_API_KEY")
        except Exception as e:
            # Add any exceptions to your list to return
            exceptions.append(e)
            return exceptions
        try:
            client = openai.OpenAI(api_key=api_key)
            client.models.list()
        except Exception as e:
            exceptions.append(e)
        # if there are exceptions, they will display when the user tries to run the flow with the node.
        return exceptions if exceptions else None


    def process(self) -> None:
        # All of the current values of a parameter are stored on self.parameter_values
        prompt = self.parameter_values["prompt"]
        # Use a griptape agent to run the structure! 
        agent = Agent(stream=True)
        full_output = ""
        # Running with the Stream Util allows you to stream your responses to the node!
        for artifact in Stream(agent, event_types=[TextChunkEvent]).run(prompt):
            full_output += artifact.value
        self.parameter_output_values["output"] = full_output
       
        
