# agent.py
import json
import os
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("LLM_API_KEY")

client = OpenAI(api_key=api_key)
MODEL = "gpt-6-luna"
NOW = datetime.strptime("2026-06-10T09:00+02:00", "%Y-%m-%dT%H:%M%z")
REASONING_EFFORT = "none"

# finds the parts of the documents in data/policies/ that are relevant to a question.


def search_policies() -> str:
    return "test"


# returns the details of one booking from data/bookings.json, or a clear "not found" result when the booking does not exist.


def get_booking(booking_id: str) -> str:
    with open("data/bookings.json", "r") as file:
        data = json.load(file)
        return next(
            (item for item in data if item.get("id") == booking_id), "Booking not found"
        )


# calculates how much a customer gets back if they cancel a booking now, following the cancellation rules.


def calculate_refund(booking_id: str) -> str:
    with open("data/bookings.json", "r") as file:
        data = json.load(file)
        booking = next(
            (item for item in data if item.get("id") == booking_id), "Booking not found"
        )
        if booking.get("status") != "confirmed":
            return "Booking is not confirmed - refund is not applicable"

        start = datetime.strptime(booking.get("start"), "%Y-%m-%dT%H:%M:%S%z")
        deposit_fee = booking.get("deposit_eur")
        rental_price = booking.get("rental_price_eur")
        duration = start - NOW
        if duration.total_seconds() / 3600 >= 48:
            return f"100% refund. Full deposit fee refunded ({deposit_fee} EUR), Full rental price refunded ({rental_price} EUR)."
        elif duration.total_seconds() / 3600 >= 24:
            return f"50% refund. Full deposit fee refunded ({deposit_fee} EUR), 50% rental price refunded ({rental_price * 0.5} EUR)"
        else:
            return "No refund"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_policies",
            "description": "Search for company policies.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_booking",
            "description": "Retrieve booking information.",
            "parameters": {
                "type": "object",
                "properties": {"booking_id": {"type": "string"}},
                "required": ["booking_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_refund",
            "description": "Calculate a refund amount for a booking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                },
                "required": ["booking_id"],
            },
        },
    },
]

DISPATCH = {
    "search_policies": search_policies,
    "get_booking": get_booking,
    "calculate_refund": calculate_refund,
}


def run(user_msg: str, max_steps: int = 6) -> str:
    messages = [{"role": "user", "content": user_msg}]
    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            reasoning_effort=REASONING_EFFORT,
        )
        msg = resp.choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            try:
                result = DISPATCH[call.function.name](**args)
            except Exception as e:
                result = f"error: {e}"
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": str(result)}
            )
    return "stopped: step limit reached"


if __name__ == "__main__":
    while True:
        user_input = input("Enter your message: ")
        response = run(user_input)
        print(response)
    # print(calculate_refund("CW-1002"))
