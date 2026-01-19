"""Entry point for Blok MCP server.

Run with: python -m blok_mcp

Environment variables for auto-authentication:
    BLOK_MCP_ACCESS_TOKEN: Pre-fetched JWT access token (skips login)
    BLOK_MCP_EMAIL: Email for auto-login on startup
    BLOK_MCP_PASSWORD: Password for auto-login on startup
"""

import asyncio
import logging
import sys

from blok_mcp.config import config
from blok_mcp.mcp_server import BlokMCPServer

# Ensure all logging goes to stderr for MCP stdio communication
logging.basicConfig(
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    try:
        # Check for pre-configured authentication
        pre_auth_token = config.access_token if config.access_token else None
        auto_auth_email = config.email if config.email and config.password else None
        auto_auth_password = config.password if config.email and config.password else None

        server = BlokMCPServer(
            pre_auth_token=pre_auth_token,
            auto_auth_email=auto_auth_email,
            auto_auth_password=auto_auth_password,
        )
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Shutting down Blok MCP server...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error starting server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
