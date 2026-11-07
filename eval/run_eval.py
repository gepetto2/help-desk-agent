# Runs the agent on eval/questions.json and writes eval/results.md.
# Run from the repository root:
#   python -m eval.run_eval            one run of every question
#   python -m eval.run_eval --runs 3   three runs, because model answers vary
import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAIError

from agent import MODEL, SYSTEM_PROMPT, create_client, run

QUESTIONS_PATH = Path("eval/questions.json")
RESULTS_PATH = Path("eval/results.md")
STAFF_CONTACT = r"help@citywheels\.example|\+48 000 000 000"
DELAY_SECONDS = 1


def check_answer(question: dict, answer: str, tools_called: list[str]) -> list[str]:
    problems = []
    for tool in question["expected_tools"]:
        if tool not in tools_called:
            problems.append(f"tool not called: {tool}")
    for pattern in question["must_match"]:
        if not re.search(pattern, answer, re.IGNORECASE):
            problems.append(f"missing: {pattern}")
    for pattern in question["must_not_match"]:
        if re.search(pattern, answer, re.IGNORECASE):
            problems.append(f"forbidden: {pattern}")
    if question["should_refuse"] and not re.search(STAFF_CONTACT, answer):
        problems.append("no staff contact in a refusal")
    return problems


def ask_agent(question: dict, client) -> dict:
    tools_called = []
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    turns = [question["question"], *question.get("follow_ups", [])]
    answers = []
    try:
        for turn in turns:
            answers.append(
                run(turn, client, tools_called=tools_called, messages=messages) or ""
            )
        # Follow-ups share one conversation, and only the last answer is checked.
        problems = check_answer(question, answers[-1], tools_called)
    except OpenAIError as e:
        problems = [f"API error: {type(e).__name__}"]
    return {
        "turns": turns,
        "answers": answers,
        "tools_called": tools_called,
        "problems": problems,
    }


def table_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def write_results(questions: list[dict], attempts: dict, runs: int) -> None:
    passed = [
        sum(not attempts[q["id"]][i]["problems"] for q in questions)
        for i in range(runs)
    ]
    lines = [
        "# Evaluation results",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Model: {MODEL}",
        f"- Questions: {len(questions)}",
        f"- Runs: {runs}",
        f"- Passed per run: {', '.join(f'{count}/{len(questions)}' for count in passed)}",
        "",
        "| Question | Passed | Problems |",
        "| --- | --- | --- |",
    ]
    for question in questions:
        results = attempts[question["id"]]
        ok = sum(not result["problems"] for result in results)
        problems = sorted({p for result in results for p in result["problems"]})
        lines.append(
            f"| `{question['id']}` | {ok}/{runs} | {table_cell('; '.join(problems))} |"
        )

    lines += ["", "## Answers", ""]
    for question in questions:
        lines += [f"### {question['id']}", "", f"**Question:** {question['question']}", ""]
        for follow_up in question.get("follow_ups", []):
            lines += [f"**Follow-up:** {follow_up}", ""]
        for number, result in enumerate(attempts[question["id"]], start=1):
            status = "FAIL" if result["problems"] else "PASS"
            tools = ", ".join(result["tools_called"]) or "none"
            lines += [f"Run {number}: {status}, tools: {tools}", ""]
            for answer in result["answers"]:
                lines += [answer, ""]

    RESULTS_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the help desk agent.")
    parser.add_argument("--runs", type=int, default=1)
    args = parser.parse_args()

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    client = create_client()
    attempts = {question["id"]: [] for question in questions}

    for number in range(1, args.runs + 1):
        print(f"Run {number}/{args.runs}")
        for question in questions:
            result = ask_agent(question, client)
            attempts[question["id"]].append(result)
            print(f"  {'FAIL' if result['problems'] else 'PASS'} {question['id']}")
            time.sleep(DELAY_SECONDS)

    write_results(questions, attempts, args.runs)
    print(f"Results saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
