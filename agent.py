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


def find_booking(booking_id: str) -> dict | None:
    normalized = booking_id.strip().upper()
    with open("data/bookings.json", "r", encoding="utf-8") as file:
        data = json.load(file)
    return next((item for item in data if item["id"] == normalized), None)


# finds the parts of the documents in data/policies/ that are relevant to a question.


def search_policies() -> str:
    return "test"


# returns the details of one booking from data/bookings.json, or a clear "not found" result when the booking does not exist.


def get_booking(booking_id: str) -> str:
    booking = find_booking(booking_id)
    return booking if booking else "Booking not found"


# calculates how much a customer gets back if they cancel a booking now, following the cancellation rules.


def calculate_refund(booking_id: str) -> dict:
    booking = find_booking(booking_id)
    if not booking:
        return {"found": False, "booking_id": booking_id}
    if booking["status"] != "confirmed":
        return {
            "found": True,
            "can_cancel": False,
            "status": booking["status"],
        }

    hours = (datetime.fromisoformat(booking["start"]) - NOW).total_seconds() / 3600

    if hours >= 48:
        percent = 100
    elif hours >= 24:
        percent = 50
    else:
        percent = 0

    rental_refund = booking["rental_price_eur"] * percent / 100
    deposit = booking["deposit_eur"]
    return {
        "found": True,
        "can_cancel": True,
        "refund_percent": percent,
        "rental_refund_eur": rental_refund,
        "deposit_refund_eur": deposit,
        "booking_fee_refund_eur": 0,
        "total_refund_eur": rental_refund + deposit,
        "paid_with": booking["paid_with"],
    }


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
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )
    return "stopped: step limit reached"


if __name__ == "__main__":
    while True:
        user_input = input("Enter your message: ")
        response = run(user_input)
        print(response)
    # print(calculate_refund("CW-1002"))
