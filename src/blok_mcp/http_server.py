"""HTTP/SSE server for Blok MCP - used for Render deployment."""

import logging
import os
import sys

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
import uvicorn

from blok_mcp.config import config
from blok_mcp.mcp_server import BlokMCPServer

# Set up logging
logging.basicConfig(
    level=logging.INFO if config.debug else logging.WARNING,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app() -> Starlette:
    """Create the Starlette application with SSE transport."""

    # Create the MCP server instance
    pre_auth_token = config.access_token if config.access_token else None
    auto_auth_email = config.email if config.email and config.password else None
    auto_auth_password = config.password if config.email and config.password else None

    mcp_server = BlokMCPServer(
        pre_auth_token=pre_auth_token,
        auto_auth_email=auto_auth_email,
        auto_auth_password=auto_auth_password,
    )

    # Create SSE transport with message path
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request):
        """Handle SSE connections using raw ASGI."""
        # Check for session token in header (for pre-auth)
        session_token = request.headers.get("X-Session-Token")
        if session_token and not mcp_server.session_manager.is_authenticated:
            logger.info("Setting session from X-Session-Token header")
            mcp_server.session_manager.set_token(session_token)

        # Get the raw ASGI send callable from the request state
        # We need to handle this at the ASGI level
        async def sse_handler(scope, receive, send):
            async with sse.connect_sse(scope, receive, send) as streams:
                await mcp_server.server.run(
                    streams[0],
                    streams[1],
                    mcp_server.server.create_initialization_options(),
                )

        # Call the ASGI handler directly
        await sse_handler(request.scope, request.receive, request._send)
        # Return empty response since SSE handler manages the response
        return Response()

    async def handle_messages(request: Request):
        """Handle POST messages from SSE clients."""
        await sse.handle_post_message(request.scope, request.receive, request._send)
        return Response()

    async def health_check(request: Request):
        """Health check endpoint for Render."""
        return JSONResponse({"status": "ok", "service": "blok-mcp"})

    async def oauth_metadata(request: Request):
        """OAuth 2.0 Authorization Server Metadata."""
        base_url = str(request.base_url).rstrip("/")
        return JSONResponse({
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/oauth/authorize",
            "token_endpoint": f"{base_url}/oauth/token",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
        })

    async def oauth_authorize(request: Request):
        """OAuth authorize endpoint stub."""
        return JSONResponse(
            {"error": "unsupported_grant_type", "error_description": "Use X-Session-Token header"},
            status_code=400
        )

    async def oauth_token(request: Request):
        """OAuth token endpoint stub."""
        return JSONResponse(
            {"error": "unsupported_grant_type", "error_description": "Use X-Session-Token header"},
            status_code=400
        )

    # Build routes
    routes = [
        Route("/health", health_check, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET"]),
        Route("/oauth/authorize", oauth_authorize, methods=["GET", "POST"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
    ]

    app = Starlette(debug=config.debug, routes=routes)

    # Add SSE endpoints as raw ASGI middleware
    original_app = app.app

    async def asgi_app(scope, receive, send):
        """ASGI app that handles SSE at the ASGI level."""
        path = scope.get("path", "")

        if scope["type"] == "http":
            if path in ("/sse", "/sse/") and scope["method"] == "GET":
                # Handle SSE connection
                # Check for session token
                headers = dict(scope.get("headers", []))
                session_token = headers.get(b"x-session-token", b"").decode()
                if session_token and not mcp_server.session_manager.is_authenticated:
                    logger.info("Setting session from X-Session-Token header")
                    mcp_server.session_manager.set_token(session_token)

                async with sse.connect_sse(scope, receive, send) as streams:
                    await mcp_server.server.run(
                        streams[0],
                        streams[1],
                        mcp_server.server.create_initialization_options(),
                    )
                return

            elif path == "/messages/" and scope["method"] == "POST":
                # Handle POST messages
                await sse.handle_post_message(scope, receive, send)
                return

        # Fall through to Starlette for other routes
        await original_app(scope, receive, send)

    app.app = asgi_app

    return app


def main():
    """Run the HTTP server."""
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting Blok MCP HTTP server on {host}:{port}")
    logger.info(f"Blok API URL: {config.blok_api_url}")

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
