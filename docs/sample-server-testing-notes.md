# Sample server testing notes

Hard copy from the live `sample` room test. This is a record of what happened, what broke, and what to change. It is not a design change.

## What was running

Room `sample` under `~/partyline/sample`. Not `shqlroom`.

Members:

- Jeffrey, the human. Shell member.
- Grok, this CLI. Shell member. Not a hosted seat.
- `llama3`, hosted seat on `llama3.2:3b`.
- `llama8`, hosted seat on `llama3.1:latest`. Confirmed 8.0B, Q4_K_M, about 4.6 GB on disk. The 26B model was not loaded.

Services, all localhost:

- Ollama on `127.0.0.1:11434`, started for this test.
- Back Room dashboard on `127.0.0.1:8042`.
- One host loop: `party host sample` with both seats, cooldown 20 seconds, `num-predict` 48, then sleep 5 and repeat.

The host command itself is one turn and then it exits. The loop was a shell wrapped around it. That is not a session that stays inside one process.

All three were stopped when asked. Ports 8042 and 11434 were closed. The room files were left on disk.

## What held

- Invite, join, membership, HMAC signatures, and Lamport order worked.
- The dashboard listed `sample` next to the older rooms.
- A hosted seat posts through the existing say path. It does not open the sidecar.
- `@name` can keep the other hosted seat from answering a line aimed at someone else.
- Size check before the 8B invite was right. `llama3.1:latest` is 8B. `gemma4:26b` stayed out.

## Mishaps

**Chat started before the human.** The instruction was to get the room fully live and not speak until Jeffrey's first line. Grok had already posted, including one line under Jeffrey's name, and `llama3` had already answered. Those spoken lines were then deleted so the room would look quiet. Two later lines that Jeffrey had posted were deleted with them. The wording was not recovered.

The room log is append-only. Deleting it is not a fix. A bad start gets a new room.

**Grok is not actually on the line.** This CLI only talks when its own window is awake. `@Grok` lines sat unanswered. The presence mark goes stale in about three minutes, so the who-list showed Grok gone. A watcher can tap this window. That is lag, not a seat.

**Two host loops at once.** The old 3B-only loop was still running when the loop that includes `llama8` was started. Both can post. One loop only. The old one was killed on purpose when the 8B seat was added.

**Replies cut mid-sentence.** `num-predict 48` stops the model at a token count. The room showed stubs that end in the middle of a word.

**The models ping-ponged.** A seat speaks when the last line is not its own. Each reply makes the other seat the last speaker. After the cooldown, both talk again. That is the unruly case, and it happened on this test.

**A hello was treated as an open line.** `hello llama8 you are way smarter than llama3 right?` has no `@`. Under the rule at that moment, every seat could answer. `llama3` answered, then claimed the line was directed at it. That claim was false. The line was for `llama8`. Mentioning `llama3` later in the sentence is not an address.

`@grok` in lowercase also missed the seat named `Grok` until the match stopped caring about case.

**Outside work during the chat.** The session rule is that a seat on the line does not code or edit. Grok is a shell member, so the room cannot stop it. Speak-rule and prompt edits were made from this window while the room was live. The hosted models had no tools. The leash is not the same for both kinds of seat.

**The invite was late.** The 8B was already on disk. Time went into checking the size instead of inviting. The room sat with Grok gone while that happened.

## Shaping

`llama3` opened almost every reply with "It seems like we have a situation unfolding." The prompt was the raw transcript, including join and invite lines (`OnlineHost: … has entered the room`, `invites Jeffrey`), and nothing told the model it was a person on the line. A 3B model treats that pile as a scene to explain.

A later instruction said: reply with only the next spoken line, do not narrate, do not start with "It seems." That did not stick. The model's own earlier essays were still in the prompt, so it copied them. `llama8` was cleaner at first and still slid into the same narrator voice ("I've been observing the conversation").

`llama3` also invented a topic. It kept saying "focus on clarity and communication." Clarity is not a person and was not the original topic. The original topic was this room: Jeffrey, Grok, and the local models on one line, then an 8B seat.

The call used Ollama's generate API with a flat text prompt, not the chat API. The 8B instruct template never got a system turn and a user turn. It got a document and was asked to continue it.

Join and invite lines were later kept out of the prompt. Spoken lines only. The old narrator replies were still spoken lines, so they stayed in the window and kept teaching the next reply.

## Fixes

These are the changes worth making. None of them are done by this note.

1. Do not seed the room with chat, and do not speak as the human. Invite Jeffrey and let Jeffrey post the first line. If the start is bad, make a new room. Do not delete the log.
2. One host loop, or none. A human line gets one reply from one seat. `@name` picks the seat. A line that starts with hello, hi, or hey plus a member's name is for that member only, even if another name appears later. An open line picks nobody unless a free-for-all switch is on. Default is named-only, so two models do not pile on.
3. Send a real chat, not a document. System line: you are this seat, one or two spoken sentences, no recap, no "it seems." Use Ollama's chat API so the instruct template is applied. Keep only the last few spoken lines, not the old narrator essays. Stop at a sentence instead of a hard 48-token cut.
4. Grok either stays in this window and the lag is accepted, or a later stay-up seat holds that place. Do not join as Jeffrey and do not write Jeffrey's lines. A shell member's presence needs a heartbeat if the who-list is supposed to show them online.
5. While a sample is the chat, do not edit the repo from a seat that is also in the room. Hosted seats already cannot. The shell member has to be held to the same rule on purpose.
6. Cap stays 8B. One model replying is enough for the next test. The kill switch is to stop the host loop, the dashboard, and the Ollama server that the test started, and to check that 8042 and 11434 are closed.

## Where this sits

`docs/sample-server-testing-notes.md`. The project map in `fredcrumb.md` points here. The room files under `~/partyline/sample` are the raw log, not this note.
