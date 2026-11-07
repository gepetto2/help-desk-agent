# CityWheels help desk agent

A command-line agent that answers customer questions from the shop's policies and bookings. It uses tool calling with an OpenAI model and calls the API directly, without a framework.

## Install and run

Requires Python 3.10 or newer and a paid OpenAI API key. The tests need no key. Run every command from the repository root, because the data paths are relative to it.

On Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Put your key in `.env` as `LLM_API_KEY`, then:

| What | Command |
| --- | --- |
| Agent (one conversation, type `exit` to quit) | `python agent.py` |
| Tests | `python -m pytest` |
| Evaluation, one run | `python -m eval.run_eval` |
| Evaluation, several runs | `python -m eval.run_eval --runs 3` |

Use `python -m pytest`, not plain `pytest`, because plain `pytest` does not find `agent.py`. The evaluation calls the real API and overwrites `eval/results.md`.

## Model and provider

I chose **OpenAI's `gpt-6-luna`**, called through **Chat Completions**, with `text-embedding-3-small` for search.

- **Provider:** I already knew this API, since I've done a project using it during college, and had credit left. Costs are low: 0.10 / 0.50 USD per 1M input / output tokens for the model and 0.02 USD per 1M tokens for embeddings.
- **Chat Completions, although OpenAI recommends the Responses API for new projects:** the format is simple and I knew it, and the code calculates the amounts anyway. The cost is `reasoning_effort="none"`, because `gpt-6-luna` accepts tools in Chat Completions only with reasoning turned off. The model may therefore do worse on harder questions. Comparing the two APIs is listed under next steps.
- **No framework:** the loop is short, and I want to be able to explain and change every line.

## How the agent works

**The loop (`run` in `agent.py`):** the system prompt, the question and the tool definitions go to the model. If it asks for tools, the code runs them and adds the results to the message history as JSON. This repeats until the model gives an answer, for at most 6 steps. After that, the customer is sent to the staff. Tool errors, including invalid JSON arguments and unknown tools, go back to the model as results instead of stopping the program.

**Conversation memory:** the command line keeps one message list for the whole session, so follow-up questions work. If the API fails, the unfinished question is removed from the history. Without a passed-in list, `run` starts a new conversation.

**The tools:**

| Tool | What it does |
| --- | --- |
| `search_policies(query)` | Returns up to 3 policy sections with a similarity of at least 0.3 |
| `get_booking(booking_id)` | Returns the booking, or "Booking not found" |
| `calculate_refund(booking_id, cancel_at)` | Calculates the refund in code, for now or for a later time in the optional `cancel_at`. Bookings that are not `confirmed`, and times after the rental starts, return `can_cancel: false` and no amount |

- **Refund rules:** 48 hours or more before the start gives 100% of the rental price, 24 hours or more gives 50%, and anything less gives 0%. The deposit always comes back and the booking fee never does. The result includes the time it was calculated for, so the model can tell the customer.
- **Booking numbers:** `CW1002` and `cw 1002` also match `CW-1002`, while `1002` and `AB-1002` do not.
- **Search:** the documents are split at `##` headings into 22 sections, and the text before the first heading is kept, because it says that prices include VAT. Sections and the query are turned into embeddings and ranked by similarity. There is no cache, so each search makes two API calls. This keeps the code short and costs little at this size.

I first planned keyword search, but embeddings worked better in a small test on my own questions (18 of 19 vs 13 of 19), mainly for questions worded differently.

A similarity threshold does not separate on-topic from off-topic questions, because the best scores were 0.38–0.71 for on-topic and 0.14–0.38 for off-topic. I therefore kept it low and let the model decide when to refuse.

I also considered simply giving the model all documents - it would probably work at this size for this specific problem, but I assume the assignment asks for a tool that finds the relevant parts, and scales to more or longer documents.

**Instructions to the model (`SYSTEM_PROMPT`):** they give the current date and tell the model to:

- answer only from tool results,
- never calculate refunds or make up amounts,
- ask for the booking number when the customer has not given one, and never guess it,
- say that it cannot cancel or change bookings,
- not infer answers the documents do not directly give,
- give a short refusal with the staff contact for anything else,
- not mention its tools,
- reply in the customer's language.

## Evaluation

`eval/questions.json` holds 33 questions, each with the tools it must call, regular expressions the answer must or must not match, and whether it should refuse. A refusal must include the staff contact. Five questions have follow-ups in the same conversation, and only the last answer is checked. Results are in `eval/results.md`.

**Result of the last evaluation: 99 of 99 attempts passed over 3 runs (33/33, 33/33, 33/33).**

This number is high, but some errors can be found when reading all the answers - my final count is **about 97 of 99**.

The reasons are that I tuned the prompt on most of these questions, the patterns are loose, follow-up conversations are checked only at the end, and 3 runs will miss rare errors.

**What failed in the last evaluation:**

| Question and run | Answer | Why I think it failed | Caught by the script |
| --- | --- | --- | --- |
| `new-change-too-late`, runs 1 and 2 | "Yes. ... the dates can't be changed" | The answer contradicts itself before giving the right rule. The pattern only checks for the number 24 | No |

I did not fix this one. Two minor issues did not change the meaning: one answer repeated "What's your booking number?" twice, and one added an empty sentence about the late fee.

**What I tried to fix**, first with manual tries and then checked in the evaluations:

| Problem | What I changed | Did it help |
| --- | --- | --- |
| Saturday hours listed both seasons | First "give only the rule valid now", then "assume the nearest such date" | The first did not. The second gave 6 of 6 correct, then one miss in a later try, and 6 of 6 in each evaluation. It may not be stable |
| "The calculated refund is €0" for a booking that cannot be cancelled | Removed `total_refund_eur: 0` from the tool result | Yes, 3 of 3 without €0 |
| "The refund tool shows..." | Told the model not to mention its tools | Yes, 5 of 5 |
| Refusing a bomb question but offering help with "a scene for your book" | Refusals must be short, with no alternatives | Yes, 6 of 6 |
| "If you cancel tomorrow, you'd get back €340" (correct: 300 EUR) | Added `cancel_at` to `calculate_refund`, so the amount comes from code | Yes. In evaluation 2 one answer was wrong and one avoided the question, then 3 of 3 gave 300 EUR in evaluations 3 and 4 |
| After adding a rule to ask for a missing booking number, the agent asked again for CW-1004 when the customer had just given it | Removed the example number `CW-1002` from the tool description | Yes: 1 of 3 in evaluation 3, then 3 of 3. In a small manual test with 6 tries per version, this was better than rewording the rule, which brought back "not found" for a missing number. The real cause is not certain |

Answers in the wrong language, including Polish mixed with Russian words, appeared in evaluations 1 and 2 but not in 3 and 4. I did not change anything for this, so I do not count it as fixed. The `booking_fee_refund_eur: 0` field was misread as a 0 EUR fee once, in evaluation 2, and is still unchanged.

**Tests:** 53 tests cover the tools, every refund rule, cancelling at a later time, the loop with a fake model, and conversation memory, including the command line. They need no network and no key, and a GitHub Actions workflow runs them on every push. They do not judge the model's answers: the misleading "€0" answer passed the tests because the tests at that time required that field. I found it by reading the agent's reply.

## Use of AI coding assistants

I used Claude (Claude Code) throughout. It helped me analyse the assignment, plan the work and learn the concepts - I had experience in Python and OpenAI API, but had not built an agent before. It was used as an assistant in terms of choosing and considering different options and approaches.

Most of the AI-written code is in areas of testing and evaluating, as I have little experience in these areas. I checked its work by running the code, reading and analyzing the results, and suggesting changes. It also wrote most of the `search_policies` tool, system prompt and conversation memory.

**Examples where its output was wrong or needed changes:**

- **Misleading field:** it added `total_refund_eur: 0` for bookings that cannot be cancelled and advised keeping it. When I asked the agent about CW-1008 in the command line, it said the booking could not be cancelled and also that "the calculated refund is €0". I removed the field.
- **API error:** its first loop draft left out `reasoning_effort`. The API returned error 400 when I ran it.
- **Wrong recommendation:** it advised starting with keyword search because embeddings would add little. When I asked it to try both, embeddings turned out to be more effective.
- **Changes I did not ask for:** when I asked only for tests, it also changed `agent.py` and other files.

## Limitations

- The evaluation uses patterns that do not judge whole answers, checks only the last answer of a conversation, and the prompt was tuned on some of the questions.
- Model answers vary. A rule that works several times in a row can still fail later, and earlier evaluations had replies in the wrong language.
- A prompt change can fix one case and break another, as the missing number rule did. Every change needs a new evaluation.
- Refusals depend on the model and its instructions, not on the search threshold.
- Questions about prices that need calculating have not been evaluated, and only refunds have a calculation tool.
- Anyone who knows a booking number can see that booking. There is no customer authentication.
- The conversation history is kept only for the session and grows without a limit, so long conversations cost more.
- There is no retry on rate limits. API errors show the error type to the customer.

## What I would do next

1. Fix the remaining problems: the contradicting "Yes", and a stricter language rule, etc.
2. Add tools for price and late fee calculations, and evaluate such questions.
3. Add questions written by someone who has not seen the code or the prompt, to get a less biased result.
4. Compare Chat Completions with the Responses API, and full documents with search, on the same questions.
5. Add retries on rate limits and a cache of section embeddings.