import json
from types import SimpleNamespace

from agent import MODEL, TOOLS, run


def tool_call(name, arguments, call_id="call_1"):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def model_reply(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    """Stands in for the OpenAI client: returns scripted replies and records requests."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.replies.pop(0)


def tool_results(request):
    return [
        message
        for message in request["messages"]
        if isinstance(message, dict) and message["role"] == "tool"
    ]


def test_returns_answer_when_model_calls_no_tool():
    client = FakeClient([model_reply("We open at 08:00.")])

    assert run("When do you open?", client) == "We open at 08:00."
    assert len(client.requests) == 1
    messages = client.requests[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "When do you open?"}
    assert client.requests[0]["model"] == MODEL
    assert client.requests[0]["tools"] == TOOLS


def test_runs_tool_and_sends_result_back_to_model():
    client = FakeClient(
        [
            model_reply(
                tool_calls=[tool_call("calculate_refund", '{"booking_id": "CW-1002"}')]
            ),
            model_reply("You get 340 EUR back."),
        ]
    )

    assert run("How much do I get back?", client) == "You get 340 EUR back."
    assert len(client.requests) == 2

    result = tool_results(client.requests[1])[0]
    assert result["tool_call_id"] == "call_1"
    assert json.loads(result["content"])["total_refund_eur"] == 340


def test_runs_every_tool_call_from_one_reply():
    client = FakeClient(
        [
            model_reply(
                tool_calls=[
                    tool_call("get_booking", '{"booking_id": "CW-1001"}', "call_1"),
                    tool_call("calculate_refund", '{"booking_id": "CW-1001"}', "call_2"),
                ]
            ),
            model_reply("Done."),
        ]
    )

    run("Tell me about my booking.", client)

    results = tool_results(client.requests[1])
    assert [result["tool_call_id"] for result in results] == ["call_1", "call_2"]
    assert json.loads(results[0]["content"])["id"] == "CW-1001"
    assert json.loads(results[1]["content"])["total_refund_eur"] == 90


def test_records_called_tools():
    client = FakeClient(
        [
            model_reply(
                tool_calls=[tool_call("get_booking", '{"booking_id": "CW-1001"}')]
            ),
            model_reply("Done."),
        ]
    )
    tools_called = []

    run("Tell me about my booking.", client, tools_called=tools_called)

    assert tools_called == ["get_booking"]


def test_unknown_booking_reaches_model_without_crashing():
    client = FakeClient(
        [
            model_reply(
                tool_calls=[tool_call("calculate_refund", '{"booking_id": "CW-9999"}')]
            ),
            model_reply("I could not find that booking."),
        ]
    )

    assert run("Cancel CW-9999.", client) == "I could not find that booking."

    result = tool_results(client.requests[1])[0]
    assert json.loads(result["content"])["found"] is False


def test_unknown_tool_is_reported_to_model():
    client = FakeClient(
        [
            model_reply(tool_calls=[tool_call("get_weather", '{"city": "Warsaw"}')]),
            model_reply("I cannot check the weather."),
        ]
    )

    assert run("What is the weather?", client) == "I cannot check the weather."
    assert "error" in tool_results(client.requests[1])[0]["content"]


def test_invalid_tool_arguments_are_reported_to_model():
    client = FakeClient(
        [
            model_reply(tool_calls=[tool_call("get_booking", "{not json")]),
            model_reply("Please give me your booking number."),
        ]
    )

    assert run("Where is my booking?", client) == "Please give me your booking number."
    assert "error" in tool_results(client.requests[1])[0]["content"]


def test_stops_at_step_limit():
    repeated_call = tool_call("get_booking", '{"booking_id": "CW-1001"}')
    client = FakeClient([model_reply(tool_calls=[repeated_call]) for _ in range(5)])

    answer = run("Keep going.", client, max_steps=3)

    assert "help@citywheels.example" in answer
    assert len(client.requests) == 3
