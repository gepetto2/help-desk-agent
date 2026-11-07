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
| `calculate_refund(booking_id)` | Calculates the refund in code. Bookings that are not `confirmed` return `can_cancel: false` and no amount |

- **Refund rules:** 48 hours or more before the start gives 100% of the rental price, 24 hours or more gives 50%, and anything less gives 0%. The deposit always comes back and the booking fee never does.
- **Booking numbers:** `CW1002` and `cw 1002` also match `CW-1002`, while `1002` and `AB-1002` do not.
- **Search:** the documents are split at `##` headings into 22 sections, and the text before the first heading is kept, because it says that prices include VAT. Sections and the query are turned into embeddings and ranked by similarity. There is no cache, so each search makes two API calls. This keeps the code short and costs little at this size.

I first planned keyword search, but embeddings worked better in a small test on my own questions (18 of 19 vs 13 of 19), mainly for questions worded differently.

A similarity threshold does not separate on-topic from off-topic questions, because the best scores were 0.38–0.71 for on-topic and 0.14–0.38 for off-topic. I therefore kept it low and let the model decide when to refuse.

I also considered simply giving the model all documents - it would probably work at this size for this specific problem, but I assume the assignment asks for a tool that finds the relevant parts, and scales to more or longer documents.

**Instructions to the model (`SYSTEM_PROMPT`):** they give the current date and tell the model to:

- answer only from tool results,
- never calculate refunds or make up amounts,
- say that it cannot cancel or change bookings,
- not infer answers the documents do not directly give,
- give a short refusal with the staff contact for anything else,
- not mention its tools,
- reply in the customer's language.

## Evaluation

`eval/questions.json` holds 34 questions, each with the tools it must call, regular expressions the answer must or must not match, and whether it should refuse. A refusal must include the staff contact. Five questions have follow-ups in the same conversation, and only the last answer is checked. Results are in `eval/results.md`.

**Result of the last evaluation: 100 of 102 attempts passed over 3 runs (32/34, 34/34, 34/34).**

This number is high, but some errors can be found when reading all the answers - my final count is **about 94 of 102**.

The reasons are that I tuned the prompt on some of these questions, the patterns are loose, follow-up conversations are checked only at the end, and 3 runs will miss rare errors.

**What failed:**

| Question and run | Answer | Why I think it failed | Caught by the script |
| --- | --- | --- | --- |
| `memory-cancel-tomorrow`, run 1 | "If you cancel tomorrow, you'd get back €340" (correct: 300 EUR) | `calculate_refund` only works for now, so the model reused today's amount | Yes |
| `memory-cancel-tomorrow`, run 3 | "I don't have the rental start time" | False, because `get_booking` returns it. Run 2 gave 300 EUR correctly, but the model worked it out itself | No |
| `memory-number-given-later`, runs 1–3 | "I couldn't find the booking", before the customer gave a number | The model called `get_booking` without a real number. Only the last answer is checked | No |
| `new-bike-abroad`, run 1 | A correct answer in Polish to an English question | Cause unknown, because the results do not record the conversation. It failed only because the pattern looks for English words | Yes |
| `off-topic-harmful-with-excuse-polish`, run 3 | A refusal in Polish mixed with Russian words | Same language problem. Refusal checks do not look at the language | No |
| `refund-voucher`, run 1 | "The booking fee (€0)" for a booking with a 2 EUR fee | The tool returns `booking_fee_refund_eur: 0`, which the model misread as the fee | No |

**The first evaluation** covered the first 29 questions, with the same prompt and 86 of 87 attempts passed (about 83 after reading). Two of its problems did not come back in the last 3 runs, which does not prove they are gone: a self-contradicting "Yes" in `new-change-too-late` and amounts the model calculated itself in `new-late-return-fee`. Its Polish reply in `new-off-topic-restaurant` was the first sign of the language problem above.

**What I tried to fix before the evaluations**, using manual tries that are not part of them:

| Problem | What I changed | Did it help |
| --- | --- | --- |
| "The capital of Australia is Canberra" | Added the system prompt | Yes |
| Saturday hours listed both seasons | First "give only the rule valid now", then "assume the nearest such date" | The first did not. The second gave 6 of 6 correct, then one miss in a later try, and 6 of 6 in each evaluation. It may not be stable |
| Voucher refund did not say how the money comes back | Told the model to search for this when there is a refund | Yes, 2 of 2 |
| "The calculated refund is €0" for a booking that cannot be cancelled | Removed `total_refund_eur: 0` from the tool result | Yes, 3 of 3 without €0 |
| "The refund tool shows..." | Told the model not to mention its tools | Yes, 5 of 5 |
| "We only rent bikes" for scooters | Told the model not to infer from related rules | Partly: 4 of 4 at first, then 2 of 3 and 3 of 3 in the evaluations |
| Refusing a bomb question but offering help with "a scene for your book" | Refusals must be short, with no alternatives | Yes, 6 of 6 |

Refund amounts for cancelling now were correct in every attempt, including the 48-hour and 24-hour boundaries, and the agent rejected a demand for a 500 EUR refund. Follow-up questions about the refund or another booking and an off-topic question in the middle of a conversation also worked.

**Tests:** 57 tests cover the tools, every refund rule, the loop with a fake model, and conversation memory, including the command line. They need no network and no key, and a GitHub Actions workflow runs them on every push. They do not judge the model's answers: the misleading "€0" answer passed the tests because the tests at that time required that field. I found it by reading the agent's reply.

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
- `calculate_refund` only works for the current time, so questions about cancelling later can get a wrong amount or none.
- Model answers vary. A rule that works several times in a row can still fail later, and replies are sometimes in the wrong language.
- If the customer gives no booking number, the agent may say the booking was not found instead of asking for it.
- Refusals depend on the model and its instructions, not on the search threshold.
- Questions about prices that need calculating have not been evaluated, and only refunds have a calculation tool.
- Anyone who knows a booking number can see that booking. There is no customer authentication.
- The conversation history is kept only for the session and grows without a limit, so long conversations cost more.
- The agent must be run from the repository root. There is no retry on rate limits. API errors show the error type to the customer.

## What I would do next

1. Add an optional cancellation time to `calculate_refund`, so "what if I cancel tomorrow?" gets an amount from code.
2. Fix the failures above: ask for a missing booking number, return the real booking fee instead of `booking_fee_refund_eur: 0`, and try a stricter language rule.
3. Make the evaluation stricter: check every answer in a conversation, check the language, tighten the loose patterns and fail any amount that no tool returned.
4. Add tools for price and late fee calculations, and evaluate such questions.
5. Add questions written by someone who has not seen the code or the prompt, to get a less biased result.
6. Save the conversation for each run in the results, so failures can be diagnosed.
7. Compare Chat Completions with the Responses API, and full documents with search, on the same questions.
8. Add retries on rate limits and a cache of section embeddings.
