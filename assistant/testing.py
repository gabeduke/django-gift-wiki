"""A scripted stand-in for the model, used by the assistant's tests.

It lives beside the protocol it implements so the two change together. Tests
are deterministic and free: no network, no credentials, no token spend.
"""

from assistant.llm import ModelTurn


class FakeModelClient:
    """Returns pre-scripted turns and records every request it was given.

    Usage:

        settings.ASSISTANT_MODEL_CLIENT = FakeModelClient([
            ModelTurn(tool_calls=(ToolCall('list_wishlists'),), input_tokens=10),
            ModelTurn(text='You have three lists.', output_tokens=5),
        ])
    """

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def generate(self, *, system_instructions, contents, tool_declarations):
        self.calls.append(
            {
                'system_instructions': system_instructions,
                'contents': contents,
                'tool_declarations': tool_declarations,
            }
        )
        if not self.turns:
            raise AssertionError('FakeModelClient ran out of scripted turns')
        return self.turns.pop(0)


class FailingModelClient:
    """Raises on every call, for testing the refund path."""

    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        from assistant.llm import ModelUnavailable

        self.calls.append(kwargs)
        raise ModelUnavailable('scripted failure')
