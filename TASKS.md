# Work plan

Do the tasks in order. After each one run its check and report the result briefly.

## 1. Skeleton

Create the repository layout from `CLAUDE.md`. Backend: FastAPI with a `GET /api/health` endpoint, config through `.env`, SQLite connection. Frontend: Vite with React and TypeScript, proxy for `/api`. Add `.gitignore`, `.env.example` and a `README.md` with run commands. Check: both servers start and the frontend shows the health response.

## 2. Data and schemas

Story and Turn models, Pydantic request and response schemas, the turn contract schema with validation of the choice mode rules. Check: tests for contract validation (valid and invalid examples for each mode, the ending, empty fields).

## 3. AI layer

`services/llm.py` with a single function that calls the model. Support a mock mode: if `.env` has `MOCK_LLM=true`, return prepared valid responses of different modes. This lets the frontend be developed without cost and without a key. Check: a test using the mock.

## 4. Story engine

`services/story_engine.py`: context assembly, response parsing and validation, retry, player input validation, turn storage. Check: tests for all scenarios with the mock, including an invalid model response, rejection of custom text in `locked` mode, and story completion.

## 5. API

All endpoints from `ARCHITECTURE.md` with the listed error codes. Check: API tests through TestClient.

## 6. Frontend: home and setup

The story list page and the setup form, with form data taken from `GET /api/setup-options`. Check: a story can be created in mock mode and appears in the list.

## 7. Frontend: story screen

The turn feed, `ChoicePanel` with three modes, loading indicator, protection from double submit, the ending screen, error handling. Check: in mock mode a story can be played from start to ending, all three choice modes render correctly, and custom input is unavailable where it is not allowed.

## 8. Real model

Turn the mock off, connect the Anthropic API, write a working narrator system prompt and turn template in `backend/prompts/`. Check: play a short story with the real model, make sure responses are valid, choice modes vary, and the story ends at the chosen length. If the model often breaks the contract, strengthen the prompt instead of loosening validation.

## 9. Polish

Restoring an unfinished story after a page reload, story deletion, clean error messages, basic responsiveness. Update `README.md`. Check: a full manual pass through all screens and a run of all tests.
