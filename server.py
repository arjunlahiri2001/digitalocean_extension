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




app = FastAPI()
debugpy.listen(("0.0.0.0", 8888))


def prepare_messages(messages: list, code_context: str, doc_bot_response: str) -> list:
    """Append SYSTEM_MESSAGE to the extracted messages, including code context and doc_bot_response if available."""
    system_message = SYSTEM_MESSAGE.copy()  # Avoid modifying the original dict

    # Incorporate DigitalOcean documentation response if available
    if doc_bot_response:
        system_message["content"] += f"\n\n---\n\nDigitalOcean Documentation Insight:\n{doc_bot_response}"

    # Incorporate code context if available
    if code_context:
        system_message["content"] += f"\n\n---\n\nHere is the full content of the latest file:\n{code_context}"

    return messages + [system_message]


async def get_github_completion(messages: list, auth_token: str, code_context: str, doc_bot_response: str):
    """Prepare messages and send them to GitHub Copilot API."""
    formatted_messages = prepare_messages(messages, code_context, doc_bot_response)

    # 🔥 Debug: Print the JSON payload being sent to GitHub Copilot
    print("\nDEBUG - JSON Payload Sent to GitHub Copilot API:\n", json.dumps(formatted_messages, indent=4))

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

        # 🔥 Debug: Print GitHub Copilot's Response Status and Headers
        print("\nDEBUG - GitHub Copilot Response Status:", response.status_code)
        print("DEBUG - GitHub Copilot Response Headers:", response.headers)

        # 🔥 Debug: Print the response as JSON if it's not streaming
        try:
            json_response = await response.json()
            print("\nDEBUG - GitHub Copilot JSON Response:\n", json.dumps(json_response, indent=4))
        except Exception:
            print("\nDEBUG - Copilot Response is not JSON, Streaming...")

        return response


@app.post("/completion")
async def completion(request: Request):
    """Extract last 10 messages, process them, and send to GitHub Copilot."""
    req = await request.json()
    auth_token = request.headers.get("x-github-token")

    # Extract only the last 10 messages
    messages = req.get("messages", [])[-10:]

    if not auth_token:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # Extract code content from the latest message if references exist
    code_context = ""
    latest_message = messages[-1]
    if latest_message.get("copilot_references"):
        for ref in latest_message["copilot_references"]:
            if ref.get("type") == "client.file":
                file_name = ref["id"]
                code_content = ref["data"]["content"]
                code_context = f"\n\nFILENAME:\n{file_name}\n\nCODE CONTENT:\n{code_content}"

    # Get the DigitalOcean documentation agent's response
    doc_bot_response = product_documentation_agent(latest_message)

    print(doc_bot_response)

    # Call GitHub Copilot API with both code and documentation context
    # response = await get_github_completion(messages, auth_token, code_context, doc_bot_response)

    # return StreamingResponse(
    #     response.aiter_bytes(),
    #     media_type="text/event-stream",
    #     status_code=response.status_code,
    # )

    async def stream_doc_response(doc_response: str):
        """Stream response in raw bytes to mimic GitHub Copilot's original stream format."""
        for line in doc_response.split("\n"):
            chunk = (line + "\n").encode("utf-8")  # Convert to bytes
            yield chunk
            await asyncio.sleep(0.05)  # Simulate streaming behavior

    return StreamingResponse(
        stream_doc_response(doc_bot_response),
        media_type="text/event-stream",
        status_code=200
    )



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
