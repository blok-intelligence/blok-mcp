"""Configuration for Blok MCP Server.

Environment Variables:
    BLOK_MCP_BLOK_API_URL: Backend API base URL (default: https://app.joinblok.co)
        - Local development: http://localhost:8000
        - Dev environment: https://dev.joinblok.co
        - Production: https://app.joinblok.co
        Note: The /api/v1 prefix is added automatically by the API client.

    BLOK_MCP_WEB_URL: Web dashboard URL for experiment links (optional)
        - If not set, derived from BLOK_API_URL
        - Local: http://localhost:3000
        - Dev: https://dev.joinblok.co
        - Production: https://app.joinblok.co

    BLOK_MCP_DEBUG: Enable debug logging (default: false)

Config Locations:
    - Claude Code: .claude/settings.json (in project root)
    - Claude Desktop: ~/Library/Application Support/Claude/claude_desktop_config.json
"""

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class MCPConfig(BaseSettings):
    """Configuration for MCP server with environment variable support."""

    # Backend API URL (e.g., https://app.joinblok.co)
    blok_api_url: str = "https://app.joinblok.co"

    # Web dashboard URL (optional - derived from blok_api_url if not set)
    web_url: str = ""

    # Enable debug logging
    debug: bool = False

    # Pre-configured access token (optional - skips authentication)
    # Get this by running: curl -s -X POST https://app.joinblok.co/api/v1/auth/signin \
    #   -H 'Content-Type: application/json' -d '{"email":"...","password":"..."}' | jq -r '.access_token'
    access_token: str = ""

    # Pre-configured credentials (optional - auto-authenticates on startup)
    email: str = ""
    password: str = ""

    class Config:
        env_prefix = "BLOK_MCP_"
        # Don't load from .env file to avoid conflicts with main backend .env
        env_file = None
        extra = "ignore"  # Ignore extra environment variables

    @field_validator('blok_api_url')
    @classmethod
    def validate_blok_api_url(cls, v: str) -> str:
        """Validate Blok API URL format."""
        if not v:
            raise ValueError("Blok API URL cannot be empty")

        v = v.strip().rstrip("/")

        # Basic URL validation
        if not (v.startswith('http://') or v.startswith('https://')):
            raise ValueError(
                f"Invalid Blok API URL: {v}. "
                "URL must start with http:// or https://"
            )

        return v

    @model_validator(mode='after')
    def set_web_url(self) -> 'MCPConfig':
        """Derive web_url from blok_api_url if not explicitly set."""
        if not self.web_url:
            # Remove /api/v1 suffix if present, otherwise use as-is
            base = self.blok_api_url.replace('/api/v1', '').rstrip('/')

            # For localhost backend, web is typically on port 3000
            if 'localhost:8000' in base:
                self.web_url = 'http://localhost:3000'
            else:
                self.web_url = base

        return self


# Global config instance
config = MCPConfig()
