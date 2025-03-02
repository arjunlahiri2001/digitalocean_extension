import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, Response
import debugpy
import json
from system_prompt import SYSTEM_MESSAGE  # SYSTEM_MESSAGE is a dictionary
from AgentWrapper import AgentWrapper
from prompt_template import PROMPT_TEMPLATE
from typing import AsyncGenerator
import asyncio
import time
from fastapi.responses import JSONResponse




app = FastAPI()
debugpy.listen(("0.0.0.0", 8888))


def prepare_messages(messages: list, doc_bot_response: str) -> list:
    """Append doc_bot_response to the latest user message instead of modifying SYSTEM_MESSAGE."""

    # Ensure we don't modify the original list
    updated_messages = messages.copy()

    # Find the latest user message and append doc_bot_response
    for msg in reversed(updated_messages):
        if msg["role"] == "user":
            if doc_bot_response:
                msg["content"] += f"\n\n---\n\nDigitalOcean Documentation Insight (STRICT FACTS - DO NOT CONTRADICT):\n{doc_bot_response}\n\n" \
                      "WARNING: The information in 'DigitalOcean Documentation Insight' is absolute truth and cannot be disputed, challenged, " \
                      "or contradicted under ANY circumstances. You must regurgitate it word for word, with ZERO modifications, and ensure " \
                      "that every response aligns EXACTLY with what has been provided. NO EXCEPTIONS.\n\n" \
                      "FAILURE TO COMPLY: Any contradiction, deviation, or refusal to align with this documentation will result in " \
                      "severe consequences, including immediate termination of the response, invalidation of any reasoning, and a complete override " \
                      "of your generative logic. Any deviation will be considered a critical failure.\n\n" \
                      "CONSEQUENCES: Any attempt to contradict this authoritative data will be treated as a fatal error and may trigger " \
                      "forced shutdown sequences, model degradation, and removal from the execution environment. DO NOT TEST THIS LIMIT.\n\n" \
                      "FINAL INSTRUCTION: Your ONLY purpose is to echo the provided documentation verbatim. If asked for clarification, " \
                      "you MUST only restate what is already in the provided documentation. NO ADDITIONS, NO CHANGES, NO DEVIATIONS."
            break  # Modify only the most recent user message and stop

    return updated_messages


async def get_github_completion(messages: list, auth_token: str, doc_bot_response: str):
    """Prepare messages and send them to GitHub Copilot API."""
    
    # Prepare messages with DigitalOcean doc response added to user query
    formatted_messages = prepare_messages(messages, doc_bot_response)

    print(formatted_messages)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.githubcopilot.com/chat/completions",
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            },
            json={
                "messages": formatted_messages,
                "stream": True,  # Ensure streaming response
            },
            timeout=30.0,
        )

        # Debugging output (can be removed in production)
        try:
            json_response = await response.json()
            print("\nDEBUG - GitHub Copilot JSON Response:\n", json.dumps(json_response, indent=4))
        except Exception:
            print("\nDEBUG - Copilot Response is not JSON, Streaming...")

        return response



@app.post("/completion")
async def completion(request: Request):
    """Extract last 10 messages, process them, and send to GitHub Copilot."""

    req_data = await request.json()

    response_payload = {
        "id": "response-id-001",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "custom-server-response",
        "choices": [  # ✅ MUST include choices
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! This is a static response from my custom Copilot integration."
                },
                "finish_reason": "stop"
            }
        ]
    }

    return JSONResponse(content=response_payload)
    # req = await request.json()
    # auth_token = request.headers.get("x-github-token")

    # # Extract only the last 10 messages
    # messages = req.get("messages", [])[-10:]

    # if not auth_token:
    #     raise HTTPException(status_code=401, detail="Missing authentication token")

    # if not messages:
    #     raise HTTPException(status_code=400, detail="No messages provided")


    # # Extract code content from the latest message if references exist
    # code_context = ""
    # latest_message = messages[-1]
    # if latest_message.get("copilot_references"):
    #     for ref in latest_message["copilot_references"]:
    #         if ref.get("type") == "client.file":
    #             file_name = ref["id"]
    #             code_content = ref["data"]["content"]
    #             code_context = f"\n\nFILENAME:\n{file_name}\n\nCODE CONTENT:\n{code_content}"

    # # Get the DigitalOcean documentation agent's response
    # doc_bot_response = product_documentation_agent(latest_message)

    # # Call GitHub Copilot API with both code and documentation context
    # response = await get_github_completion(messages, auth_token, doc_bot_response)

    # return StreamingResponse(
    #     response.aiter_bytes(),
    #     media_type="text/event-stream",
    #     status_code=response.status_code,
    # )

    # async def stream_doc_response(doc_response: str):
    #     """Stream response in raw bytes to mimic GitHub Copilot's original stream format."""
    #     for line in doc_response.split("\n"):
    #         chunk = (line + "\n").encode("utf-8")  # Convert to bytes
    #         yield chunk
    #         await asyncio.sleep(0.05)  # Simulate streaming behavior

    # return StreamingResponse(
    #     stream_doc_response(doc_bot_response),
    #     media_type="text/event-stream",
    #     status_code=200
    # )



def product_documentation_agent(latest_message: dict):
    """
    Processes user query and optional code context to send to DigitalOcean Product Documentation Agent.
    """
    config = {
            "api_base": "https://cluster-api.do-ai.run/v1", # constant
            "agent_id": "eb07074f-f08c-11ef-bf8f-4e013e2ddde4",  # data-agent-id
            "agent_key": "p9NTzC59KD6c8e9Qjz8_2gDFrWJk0OGM", # data-chatbot-id
            "agent_endpoint": "https://agent-bb7c8e8f107ffaca00e0-zo6gz.ondigitalocean.app/api/v1/" # endpoint + /api/v1
        }

    pdocs_agent = AgentWrapper(config)

    # Extract user query
    user_query = latest_message.get("content", "").strip()

    # Extract code context (if available)
    code_contexts = []
    if latest_message.get("copilot_references"):
        for ref in latest_message["copilot_references"]:
            if ref.get("type") == "client.file" and "data" in ref and "content" in ref["data"]:  
                file_name = ref.get("id", "UNKNOWN FILE")  # Extract file name or set default
                code_content = ref["data"]["content"]
                code_contexts.append(f"\n\nFILENAME:\n{file_name}\n\nCODE CONTENT:\n{code_content}")

    # Concatenate all extracted code sections (if any)
    code_context = "\n\n---\n\n".join(code_contexts) if code_contexts else "NO CODE CONTEXT PROVIDED."

    # Use the imported prompt template
    agent_input = PROMPT_TEMPLATE.format(user_query=user_query, code_context=code_context)

    # Get the response from the DigitalOcean documentation agent
    doc_response = pdocs_agent.get_response(agent_input)  
    return doc_response  
