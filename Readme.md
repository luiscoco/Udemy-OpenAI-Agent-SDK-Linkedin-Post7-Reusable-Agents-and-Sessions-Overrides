# Lesson 7 practical application: Reusable Support Tutor

This Python command-line lab demonstrates **Reusable Agents and Session Overrides**. A support team saves one technical tutor and reuses it for three separate conversations: a normal explanation, a concise support answer, and a bullet-point explanation created after updating the saved configuration.

Students can run the entire lab offline immediately. An optional live mode uses the OpenAI Agents API. Every run prints its mode prominently and saves a JSON report with identifiers, configuration snapshots, conversation histories, and verification results.

## Purpose and lesson concepts

The application helps students distinguish a reusable definition from a conversation. It also makes configuration changes visible: inspect the report to compare what was saved, what was overridden, and what the session actually received.

| Lesson slide | Exercise in this application |
| --- | --- |
| 7: Overview | Run the full save, reuse, customize, and verify workflow. |
| 7A: Save one reusable agent | Create one support tutor and retain its agent ID. |
| 7B: Independent sessions | A receives ticket ALPHA-17; B receives BRAVO-28. Continue A and verify B's stored history is unchanged. |
| 7C: Override instructions | B inherits the baseline accuracy instructions and adds a concise response requirement in its replacement instruction string. |
| 7D: Replacement rules | Compare complete replacement objects and lists in a separate local exercise. B also supplies a replacement reasoning object. |
| 7E: Task and environment | Keep input, agent overrides, and `environment: {"type": "none"}` separate in the session request. |
| 7F: Track and verify | Record IDs and labels; change the saved instructions and compare existing A/B with new session C. |

Session-creation overrides affect that session; saved-agent changes affect subsequent sessions. The overridden fields used here replace their saved values. See the [official configuration guide](https://developers.openai.com/api/docs/guides/agents-api/configuration) for field-specific behavior, including exceptions and update rules.

## Requirements

- Python **3.10 or later**.
- Offline mode: no packages, API key, or internet connection required.
- Live mode: an OpenAI project API key, billing/credits, network access, and access to the Agents API and configured model.

The live implementation uses Python's standard-library HTTP client, so there is no `pip install` step. Requests include the beta header explicitly. The [official quickstart](https://developers.openai.com/api/docs/guides/agents-api/quickstart) specifies `api.agents.read`, `api.agents.write`, and `api.responses.write` permissions and the `OpenAI-Beta: agents=v1` header.

## Run the application offline

Open a terminal in this subfolder:

```powershell
cd "Practical Application Example"
python --version
python app.py
```

On some macOS/Linux systems, use `python3` instead of `python`.

You should see `OFFLINE SIMULATION`, explanations for A, B, and C, and checks marked `PASS`. The follow-up answer in A is `ALPHA-17`. The last line points to the generated report.

Offline responses are **handwritten fixtures**, not model output. This mode demonstrates configuration copying, bookkeeping, and separate histories; it cannot validate model quality, instruction adherence, API availability, or remote authorization. The fixture engine only understands this lab's small set of tasks.

## Configure and run live mode

Use an **OpenAI** API key. The Inworld key used for the lesson video is for a different service and is not used by this application.

PowerShell, for the current terminal session:

```powershell
$env:OPENAI_API_KEY = "YOUR_OPENAI_PROJECT_API_KEY"
$env:OPENAI_MODEL = "gpt-6-astra"
python app.py --live
```

macOS/Linux:

```bash
export OPENAI_API_KEY="YOUR_OPENAI_PROJECT_API_KEY"
export OPENAI_MODEL="gpt-6-astra"
python3 app.py --live
```

The default model matches the lesson. Choose an accessible Agents API model if needed. Changing the name does not make incompatible reasoning settings valid; check model support and adjust `config.json` accordingly.

Model selection order is `--model`, then `OPENAI_MODEL`, then `config.json`:

```powershell
python app.py --live --model gpt-6-astra --timeout 300
```

The configuration file contains the initial saved definition:

```json
{
  "model": "gpt-6-astra",
  "instructions": "You are a technical support tutor. Answer accurately, explain uncertainty when relevant, and use clear English. Do not use external tools. Give a short explanation and one practical example.",
  "reasoning": {"effort": "low", "summary": "auto"},
  "tools": []
}
```

You can supply another file with `--config path/to/config.json`. Keep `tools` empty: this exercise answers text questions and does not implement function execution. `environment.type` is intentionally fixed to `none`. Add real tool handlers and choose an appropriate environment before extending it to code execution or external actions.

Set credentials through your shell or secret manager. The program does not read `.env` files. It never stores the key in the report.

Live mode makes four model turns: initial A, initial B, A's follow-up, and initial C. It creates one saved agent and three remote sessions. API usage is billed, and each invocation starts a new experiment. Resources remain in the OpenAI project so students can inspect them. Their IDs are saved in `resources.json`; use the documented [session management API](https://developers.openai.com/api/docs/guides/agents-api/sessions/manage) and [agent deletion endpoint](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/methods/delete) to remove those specific resources when finished.

## Read the results

Each run creates a distinct `runs/<UTC timestamp>-<suffix>/` folder:

| File | Contents |
| --- | --- |
| `report.json` | Experiment mode, saved agent ID, named session records, overrides, expected/observed configuration, histories, and checks. Written incrementally. |
| `offline_state.json` | Simulation's local saved definitions and histories; offline mode only. |
| `resources.json` | Remote agent/session IDs recorded as creation succeeds; live mode only. |
| `error.txt` | Failure details if the experiment stops. |

`support-v1` and `support-v2` are application labels. They are not remote API version pins. Expected configuration is a teaching projection of the submitted fields. Observed configuration comes from the backend; the live API may return additional defaults or normalized fields.

The checks compare explicit instruction strings, distinct IDs, persisted user inputs, unchanged B history, and configuration snapshots. They also require assistant text. Read the actual answers yourself to judge correctness and style; these checks do not prove semantic isolation or guarantee model compliance. Distinct histories do not replace permissions for shared tools or data.

## How the application was built

### 1. Separate the experiment from its backend

`app.py` describes the lesson workflow. `backends.py` supplies `OfflineBackend` and `LiveBackend` with the same small interface: save a definition, start a session, send a follow-up, retrieve state, and update the definition. This keeps students focused on the same sequence in both modes.

```python
backend = (LiveBackend if args.live else OfflineBackend)(directory, timeout=args.timeout)
run_demo(backend, config, directory)
```

### 2. Save the shared agent

Live mode posts the configured fields to `/v1/agents` and records the returned identifier:

```python
result = self.request('POST', '/agents', config)
self.remember('agents', result['id'])
return result['id']
```

`request()` attaches the authorization and beta headers. Credentials stay in the client process. A distinct idempotency key accompanies each mutation. The application does not automatically retry mutations after ambiguous network failures.

### 3. Create independent sessions

The live request references the saved agent and supplies the current question and execution environment separately:

```python
body = {
    'agent_id': agent_id,
    'environment': {'type': 'none'},
    'input': text,
    'metadata': {'lesson': '7', 'config_label': label},
}
if overrides:
    body['agent'] = overrides
```

A omits `agent` to use the saved configuration. B supplies selected settings. The session ID is stored before waiting for inference, so a later failure does not lose an already-created resource. The [create-session reference](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/methods/create) documents these request fields.

### 4. Preserve baseline instructions explicitly

```python
overrides = {
    'instructions': config['instructions'] + ' Use one concise paragraph of at most 45 words.',
    'reasoning': {'effort': 'low'},
}
```

The application constructs the full custom instruction string before sending it. This preserves its baseline accuracy rule. B's reasoning object intentionally omits the saved `summary`; inspect the observed settings without assuming omitted properties were merged back.

### 5. Demonstrate replacement locally

```python
result = deepcopy(saved)
for field, value in overrides.items():
    result[field] = deepcopy(value)
```

The deep copy prevents one simulation session from mutating another. `replacement_lab()` starts with two tool labels and keeps only one in the replacement list. Its labels are illustrative strings, not valid API tool definitions, and are never sent as live tools. This helper models only the fields in the exercise; it is not a universal configuration resolver, schema validator, or implementation of every API field's semantics.

### 6. Continue the correct conversation

```python
self.request('POST', path + '/events', {'events': [{
    'type': 'agent.session.input.message',
    'input': [{'role': 'user', 'content': [
        {'type': 'input_text', 'text': text}
    ]}],
}]})
```

Here `path` contains A's session ID. The application sends only the follow-up, letting the remote session retain its conversation. It records prior turn IDs and waits for a new completed root turn. See [running and continuing sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions).

### 7. Wait for an actual outcome and retrieve the history

Live mode polls session state and paginated turns. It rejects failed/cancelled turns and stops when required actions need handling. An idle session alone is not success. It then retrieves all pages of saved items and extracts message text. The [turns reference](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/subresources/turns/methods/list) defines terminal turn states; the [events and items guide](https://developers.openai.com/api/docs/guides/agents-api/sessions/events) explains retrieving saved output.

### 8. Change the saved definition and compare snapshots

```python
config_v2['instructions'] = (
    config['instructions'] + ' Present explanations as exactly three bullet points.'
)
backend.update_agent(agent_id, {'instructions': config_v2['instructions']})
```

C is created afterward. The experiment retrieves A and B again and compares their original instruction strings with C's new ones. This exercises a saved-definition update, not an update to an existing session. The [update-agent reference](https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/methods/update) documents the saved-resource operation.

## Files and validation

```text
Practical Application Example/
  app.py          Lesson workflow, CLI, report, configuration comparisons
  backends.py     Offline simulation and real Agents API REST client
  config.json     Initial agent settings
  test_app.py     Offline behavior and failure-handling checks
  Readme.md       Student guide
  .gitignore      Excludes credentials, caches, and generated runs
  runs/           Created when the lab runs
```

Run the tests from this folder:

```powershell
python -m unittest -v
```

Tests cover the full offline exercise, deep-copy isolation, object/list replacement, remote failed-turn handling, stale-turn handling, required actions, and paginated history. Remote cases use test doubles; no API calls or charges occur. Live execution requires your own authorized credentials and has not been verified with a live key in the authoring workspace.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `python` not found | Install Python 3.10+ and reopen the terminal, or use `py` on Windows / `python3` on macOS/Linux. |
| Missing key | Set `OPENAI_API_KEY` in the terminal that runs the app. Omit `--live` to use simulation. |
| HTTP 401/403 | Check the OpenAI project key, required permissions, and Agents API access. |
| Unknown model or HTTP 400 | Choose a supported accessible model and compatible reasoning fields. |
| Timeout or connection failure | Inspect recorded IDs and remote state before retrying. A remote turn may still run, and a lost creation response can leave an unrecorded resource. |
| Required action | This lab does not execute external functions or approvals. Inspect the action and keep the supplied text-only configuration. |
| An answer differs from the slides | Model output varies. Compare the saved/observed settings and review the answer's accuracy and format. |

## Student exercises

1. Change B's limit to 25 words. Compare the live answer with its instructions.
2. Give B a follow-up asking for its ticket reference; check that A is unchanged.
3. In the local replacement lab, supply the full reasoning object. Explain why `summary` now remains.
4. Change v2 to request a numbered checklist. Compare existing A/B with newly created C.
5. Add a `team` field to the local report records and explain why it does not automatically become an API parameter or permission rule.
