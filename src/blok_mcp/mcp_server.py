"""MCP server with Blok authentication via Supabase."""

import logging
import sys
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pyngrok import ngrok
from pyngrok.conf import PyngrokConfig

from blok_mcp.config import config
from blok_mcp.auth.session import SessionManager
from blok_mcp.auth.authenticator import AuthenticationError


# Set up logging - MUST use stderr for MCP stdio communication
logging.basicConfig(
    level=logging.INFO if config.debug else logging.WARNING,
    stream=sys.stderr,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BlokMCPServer:
    """MCP server for Blok experiments."""

    def __init__(
        self,
        pre_auth_token: Optional[str] = None,
        auto_auth_email: Optional[str] = None,
        auto_auth_password: Optional[str] = None,
    ):
        """Initialize the MCP server.

        Args:
            pre_auth_token: Optional pre-supplied access token to skip authentication
            auto_auth_email: Optional email for auto-authentication on startup
            auto_auth_password: Optional password for auto-authentication on startup
        """
        # Initialize server with explicit name
        self.server = Server("blok-experiments")

        self.session_manager = SessionManager(
            blok_api_url=config.blok_api_url,
        )

        # Store credentials for auto-auth (will authenticate on first API call)
        self._auto_auth_email = auto_auth_email
        self._auto_auth_password = auto_auth_password

        # If pre-auth token provided, set it up immediately
        if pre_auth_token:
            logger.info("Using pre-configured access token")
            self.session_manager.set_token(pre_auth_token)
        elif auto_auth_email and auto_auth_password:
            logger.info(f"Auto-authentication configured for {auto_auth_email}")

        # Store active ngrok tunnels
        self.ngrok_tunnels: dict[str, Any] = {}  # port -> tunnel object

        # Register handlers
        # The SDK will automatically expose tool capabilities based on registered handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register MCP protocol handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools."""
            return [
                Tool(
                    name="whoami",
                    description=(
                        "Authenticate with Blok and return user information. "
                        "This tool establishes a session that persists across subsequent tool calls."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "email": {
                                "type": "string",
                                "description": "User email address for authentication",
                            },
                            "password": {
                                "type": "string",
                                "description": "User password for authentication",
                            },
                        },
                        "required": ["email", "password"],
                    },
                ),
                Tool(
                    name="list_personas",
                    description=(
                        "List all available user personas for experiments. "
                        "Personas represent different user types with unique traits and behaviors. "
                        "Use this to discover persona IDs before creating experiments."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "email": {
                                "type": "string",
                                "description": "User email (only if not already authenticated)",
                            },
                            "password": {
                                "type": "string",
                                "description": "User password (only if not already authenticated)",
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="list_experiment_types",
                    description=(
                        "List all available experiment type templates. "
                        "Each type provides context for different testing scenarios like Onboarding, "
                        "Task Completion, Churn Analysis, etc. Use this to discover experiment type IDs."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "email": {
                                "type": "string",
                                "description": "User email (only if not already authenticated)",
                            },
                            "password": {
                                "type": "string",
                                "description": "User password (only if not already authenticated)",
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="start_experiment",
                    description=(
                        "Create and run a new Blok experiment with AI agents testing your interface. "
                        "The experiment will run multiple persona simulations to test your hypothesis. "
                        "Returns experiment ID and estimated runtime."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "hypothesis": {
                                "type": "string",
                                "description": "Test objective - what you want to understand about user interactions (e.g., 'Determine whether users can complete signup without getting stuck')",
                            },
                            "goal": {
                                "type": "string",
                                "description": "User goal - what outcome should agents work toward (e.g., 'Sign up for an account')",
                            },
                            "url": {
                                "type": "string",
                                "description": "Interface URL to test (e.g., 'https://example.com' or 'example.com')",
                            },
                            "persona_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Array of persona UUIDs to run simulations with. Use list_personas to discover IDs.",
                            },
                            "title": {
                                "type": "string",
                                "description": "Experiment title (optional - will be auto-generated if not provided)",
                            },
                            "experiment_type_id": {
                                "type": "string",
                                "description": "Experiment type UUID (optional - will be auto-suggested if not provided). Use list_experiment_types to discover IDs.",
                            },
                            "frame_type": {
                                "type": "string",
                                "enum": ["Desktop", "Mobile"],
                                "description": "Device type for simulation (default: Desktop)",
                            },
                            "credential_username": {
                                "type": "string",
                                "description": "Username for protected content (optional)",
                            },
                            "credential_password": {
                                "type": "string",
                                "description": "Password for protected content (optional)",
                            },
                            "email": {
                                "type": "string",
                                "description": "User email (only if not already authenticated)",
                            },
                            "password": {
                                "type": "string",
                                "description": "User password (only if not already authenticated)",
                            },
                        },
                        "required": ["hypothesis", "goal", "url", "persona_ids"],
                    },
                ),
                Tool(
                    name="create_experiment_from_description",
                    description=(
                        "Create and run a Blok experiment from natural language. "
                        "Automatically generates hypothesis, goal, and title from test description. "
                        "Example: test_description='successfully complete checkout', url='shopify.com', persona_ids=[...]"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "test_description": {
                                "type": "string",
                                "description": "What to test in natural language (e.g., 'successfully complete checkout', 'find pricing page')",
                            },
                            "url": {
                                "type": "string",
                                "description": "Website URL to test",
                            },
                            "persona_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Persona UUIDs to test with (use list_personas to find IDs)",
                            },
                            "frame_type": {
                                "type": "string",
                                "enum": ["Desktop", "Mobile"],
                                "description": "Device type (default: Desktop)",
                            },
                            "credentials": {
                                "type": "string",
                                "description": "Login credentials if needed (format: username:password)",
                            },
                            "email": {
                                "type": "string",
                                "description": "User email (only if not already authenticated)",
                            },
                            "password": {
                                "type": "string",
                                "description": "User password (only if not already authenticated)",
                            },
                        },
                        "required": ["test_description", "url", "persona_ids"],
                    },
                ),
                Tool(
                    name="list_experiments",
                    description=(
                        "List all past experiments for the authenticated user. "
                        "Optionally filter by name to find specific experiments. "
                        "Returns experiment IDs, names, status, and creation dates. "
                        "Use this to find experiment IDs before calling get_experiment_results."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "name_filter": {
                                "type": "string",
                                "description": "Optional filter to search experiments by name (case-insensitive partial match)",
                            },
                            "status_filter": {
                                "type": "string",
                                "enum": ["Draft", "Running", "Completed", "Failed"],
                                "description": "Optional filter by experiment status",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of experiments to return (default: 20, max: 100)",
                            },
                            "email": {
                                "type": "string",
                                "description": "User email (only if not already authenticated)",
                            },
                            "password": {
                                "type": "string",
                                "description": "User password (only if not already authenticated)",
                            },
                        },
                        "required": [],
                    },
                ),
                Tool(
                    name="get_experiment_results",
                    description=(
                        "Get the results of a running or completed experiment. "
                        "Returns the results of the experiment in a human-readable format."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "experiment_id": {
                                "type": "string",
                                "description": "The experiment UUID to get results for",
                            },
                            "email": {
                                "type": "string",
                                "description": "User email (only if not already authenticated)",
                            },
                            "password": {
                                "type": "string",
                                "description": "User password (only if not already authenticated)",
                            },
                        },
                        "required": ["experiment_id"],
                    },
                ),
                Tool(
                    name="start_ngrok",
                    description=(
                        "Start an ngrok tunnel to expose a localhost port publicly. "
                        "Returns a public HTTPS URL that can be used in experiments. "
                        "The tunnel persists until explicitly stopped with stop_ngrok."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "port": {
                                "type": "integer",
                                "description": "Local port number to expose (e.g., 3000, 8000)",
                            },
                            "protocol": {
                                "type": "string",
                                "enum": ["http", "tcp"],
                                "description": "Protocol to use (default: http)",
                            },
                        },
                        "required": ["port"],
                    },
                ),
                Tool(
                    name="get_ngrok_status",
                    description=(
                        "Check the status of active ngrok tunnels. "
                        "Returns information about running tunnels including public URLs and ports."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
                Tool(
                    name="stop_ngrok",
                    description=(
                        "Stop an active ngrok tunnel for a specific port. "
                        "If no port is specified, stops all active tunnels."
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "port": {
                                "type": "integer",
                                "description": "Port number of the tunnel to stop (optional - if not provided, stops all tunnels)",
                            },
                        },
                        "required": [],
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent]:
            """Execute a tool."""
            if name == "whoami":
                return await self._whoami(arguments)
            elif name == "list_personas":
                return await self._list_personas(arguments)
            elif name == "list_experiment_types":
                return await self._list_experiment_types(arguments)
            elif name == "start_experiment":
                return await self._start_experiment(arguments)
            elif name == "create_experiment_from_description":
                return await self._create_experiment_from_description(arguments)
            elif name == "list_experiments":
                return await self._list_experiments(arguments)
            elif name == "get_experiment_results":
                return await self._get_experiment_results(arguments)
            elif name == "start_ngrok":
                return await self._start_ngrok(arguments)
            elif name == "get_ngrok_status":
                return await self._get_ngrok_status(arguments)
            elif name == "stop_ngrok":
                return await self._stop_ngrok(arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

    async def _whoami(self, arguments: dict) -> list[TextContent]:
        """Authenticate user and return session info.

        Args:
            arguments: Dictionary with email and password

        Returns:
            List containing formatted user information
        """
        email = arguments.get("email")
        password = arguments.get("password")

        if not email or not password:
            return [
                TextContent(
                    type="text",
                    text="Error: Both email and password are required",
                )
            ]

        try:
            # Authenticate user
            logger.info(f"Authenticating user: {email}")
            session = await self.session_manager.authenticate_async(email, password)

            # Format success response
            response = f"""Authentication successful!

Email: {session.email}
User ID: {session.user_id}
Tenant ID: {session.tenant_id}

Session active. Future tool calls will use this session automatically."""

            logger.info(f"Authentication successful for {email}")

            return [TextContent(type="text", text=response)]

        except AuthenticationError as e:
            error_msg = f"Authentication failed: {str(e)}"
            logger.error(error_msg)
            return [TextContent(type="text", text=error_msg)]

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.exception("Unexpected error during authentication")
            return [TextContent(type="text", text=error_msg)]

    async def _ensure_authenticated(self, arguments: dict) -> bool:
        """Ensure user is authenticated, optionally authenticating with provided credentials.

        Args:
            arguments: Dictionary that may contain email and password

        Returns:
            True if authenticated, False otherwise
        """
        if self.session_manager.is_authenticated:
            return True

        # Try credentials from arguments first
        email = arguments.get("email")
        password = arguments.get("password")

        # Fall back to auto-auth credentials from config
        if not email or not password:
            email = self._auto_auth_email
            password = self._auto_auth_password

        if email and password:
            try:
                logger.info(f"Authenticating as {email}...")
                await self.session_manager.authenticate_async(email, password)
                return True
            except AuthenticationError as e:
                logger.error(f"Authentication failed: {e}")
                return False

        return False

    async def _list_personas(self, arguments: dict) -> list[TextContent]:
        """List all available personas.

        Args:
            arguments: Dictionary with optional email/password

        Returns:
            List containing formatted persona information
        """
        try:
            # Ensure authenticated
            if not await self._ensure_authenticated(arguments):
                return [TextContent(
                    type="text",
                    text="Error: Not authenticated. Please provide email and password, or call whoami first."
                )]

            # Get authenticated client
            client = self.session_manager.get_client()

            # Fetch personas
            logger.info("Fetching personas...")
            response = await client.get("/personas", params={"limit": 100})

            # Handle response format (may be {personas: [...]} or [...])
            personas_list = response.get("personas", response) if isinstance(response, dict) else response

            if not personas_list:
                return [TextContent(type="text", text="No personas found for your tenant.")]

            # Format response
            result = "Available Personas:\n" + "=" * 50 + "\n\n"

            for persona in personas_list:
                name = persona.get("name", "Unnamed")
                persona_id = persona.get("id", "")
                description = persona.get("description", "No description")

                result += f"* {name}\n"
                result += f"  ID: {persona_id}\n"
                result += f"  Description: {description}\n\n"

            result += f"Total: {len(personas_list)} persona(s)"

            logger.info(f"Successfully retrieved {len(personas_list)} personas")
            return [TextContent(type="text", text=result)]

        except Exception as e:
            error_msg = f"Error fetching personas: {str(e)}"
            logger.exception("Error in list_personas")
            return [TextContent(type="text", text=error_msg)]

    async def _list_experiment_types(self, arguments: dict) -> list[TextContent]:
        """List all available experiment types.

        Args:
            arguments: Dictionary with optional email/password

        Returns:
            List containing formatted experiment type information
        """
        try:
            # Ensure authenticated
            if not await self._ensure_authenticated(arguments):
                return [TextContent(
                    type="text",
                    text="Error: Not authenticated. Please provide email and password, or call whoami first."
                )]

            # Get authenticated client
            client = self.session_manager.get_client()

            # Fetch experiment types
            logger.info("Fetching experiment types...")
            exp_types = await client.get("/experiments/types")

            if not exp_types:
                return [TextContent(type="text", text="No experiment types found.")]

            # Format response
            result = "Available Experiment Types:\n" + "=" * 50 + "\n\n"

            for exp_type in exp_types:
                name = exp_type.get("name", "Unnamed")
                type_id = exp_type.get("id", "")
                description = exp_type.get("description", "No description")
                instructions = exp_type.get("instructions", "")

                result += f"* {name}\n"
                result += f"  ID: {type_id}\n"
                result += f"  Description: {description}\n"
                if instructions:
                    result += f"  Instructions: {instructions[:100]}...\n"
                result += "\n"

            result += f"Total: {len(exp_types)} type(s)"

            logger.info(f"Successfully retrieved {len(exp_types)} experiment types")
            return [TextContent(type="text", text=result)]

        except Exception as e:
            error_msg = f"Error fetching experiment types: {str(e)}"
            logger.exception("Error in list_experiment_types")
            return [TextContent(type="text", text=error_msg)]

    async def _start_experiment(self, arguments: dict) -> list[TextContent]:
        """Create and run a new experiment.

        Args:
            arguments: Dictionary with experiment parameters

        Returns:
            List containing experiment creation result
        """
        try:
            # Ensure authenticated
            if not await self._ensure_authenticated(arguments):
                return [TextContent(
                    type="text",
                    text="Error: Not authenticated. Please provide email and password, or call whoami first."
                )]

            # Get authenticated client
            client = self.session_manager.get_client()

            # Extract and validate required parameters
            hypothesis = arguments.get("hypothesis", "").strip()
            goal = arguments.get("goal", "").strip()
            url = arguments.get("url", "").strip()
            persona_ids = arguments.get("persona_ids", [])

            if not hypothesis:
                return [TextContent(type="text", text="Error: hypothesis is required")]
            if not goal:
                return [TextContent(type="text", text="Error: goal is required")]
            if not url:
                return [TextContent(type="text", text="Error: url is required")]
            if not persona_ids or len(persona_ids) == 0:
                return [TextContent(type="text", text="Error: At least one persona_id is required")]

            # Normalize URL
            if not url.startswith("http://") and not url.startswith("https://"):
                url = f"https://{url}"

            # Extract optional parameters
            title = arguments.get("title", "").strip() or None
            experiment_type_id = arguments.get("experiment_type_id", "").strip() or None
            frame_type = arguments.get("frame_type", "Desktop")
            credential_username = arguments.get("credential_username", "").strip()
            credential_password = arguments.get("credential_password", "").strip()

            # Build credentials string if provided
            credentials = None
            if credential_username or credential_password:
                credentials = f"username: {credential_username}, password: {credential_password}"

            logger.info(f"Starting experiment: {title or 'Untitled'}")

            # If no type or title provided, call LLM suggestion endpoint
            if not experiment_type_id or not title:
                logger.info("Fetching LLM suggestions for type/title...")

                # Fetch full persona details for LLM payload
                personas_response = await client.get("/personas", params={"limit": 100})
                all_personas = personas_response.get("personas", personas_response) if isinstance(personas_response, dict) else personas_response
                selected_personas_full = [p for p in all_personas if p.get("id") in persona_ids]

                # Fetch experiment types for LLM payload
                exp_types_response = await client.get("/experiments/types")

                suggestion_payload = {
                    "experimentTitle": title,
                    "hypothesis": hypothesis,
                    "goal": goal,
                    "url": url,
                    "frame_type": frame_type,
                    "personas": [
                        {
                            "id": p.get("id"),
                            "name": p.get("name", ""),
                            "description": p.get("description", ""),
                            "traits": p.get("traits", {}),
                            "tendencies": p.get("tendencies", []),
                            "participants": p.get("participants", 0),
                        }
                        for p in selected_personas_full
                    ],
                    "availableExperimentTypes": [
                        {
                            "id": et.get("id"),
                            "name": et.get("name"),
                            "instructions": et.get("instructions"),
                            "success_indicators": None,
                            "prompt_specifics": None,
                        }
                        for et in exp_types_response
                    ],
                }

                suggestion_result = await client.post("/experiments/types/suggest", json=suggestion_payload)

                if not experiment_type_id:
                    experiment_type_id = suggestion_result.get("suggested_experiment_type_id")
                    if not experiment_type_id:
                        return [TextContent(type="text", text="Error: Failed to auto-suggest experiment type")]

                if not title:
                    title = suggestion_result.get("suggested_title")
                    if not title:
                        return [TextContent(type="text", text="Error: Failed to auto-generate title")]

            # Create experiment payload
            experiment_payload = {
                "title": title,
                "hypothesis": hypothesis,
                "goal": goal,
                "url": url,
                "experiment_type_id": experiment_type_id,
                "persona_ids": persona_ids,
                "frame_type": frame_type,
                "status": "Draft",
                "credentials": credentials,
            }

            # Create experiment
            logger.info("Creating experiment...")
            create_response = await client.post("/experiments", json=experiment_payload)

            experiment_id = create_response.get("data", [{}])[0].get("experiment_id")
            if not experiment_id:
                return [TextContent(type="text", text="Error: Failed to get experiment ID from response")]

            # Run experiment
            logger.info(f"Running experiment {experiment_id}...")
            run_response = await client.post(f"/experiments/{experiment_id}/run")

            if run_response.get("status") == "success":
                # Calculate estimated runtime
                num_personas = len(persona_ids)
                estimated_minutes = round(5 + 7.2 * (0.5 + num_personas))

                result = f"""Experiment created and started successfully!

Experiment ID: {experiment_id}
Title: {title}
URL: {url}
Personas: {num_personas}
Estimated Runtime: {estimated_minutes} minutes

Status: Running

The experiment is now running in the background. You can check results later using:
get_experiment_results(experiment_id="{experiment_id}")

Or view it in the web interface at:
{config.web_url}/experiments/{experiment_id}"""

                logger.info(f"Experiment {experiment_id} started successfully")
                return [TextContent(type="text", text=result)]
            else:
                error_msg = run_response.get("message", "Unknown error")
                return [TextContent(type="text", text=f"Experiment created but failed to start: {error_msg}")]

        except Exception as e:
            error_msg = f"Error creating experiment: {str(e)}"
            logger.exception("Error in start_experiment")
            return [TextContent(type="text", text=error_msg)]

    async def _create_experiment_from_description(self, arguments: dict) -> list[TextContent]:
        """Create and run experiment from natural language description.

        This method:
        1. Generates hypothesis and goal from test_description
        2. Creates a title from first few words
        3. Calls /experiments/types/suggest to pick experiment type
        4. Creates experiment
        5. Runs experiment
        6. Returns experiment ID and status
        """
        try:
            # Ensure authenticated
            if not await self._ensure_authenticated(arguments):
                return [TextContent(
                    type="text",
                    text="Error: Not authenticated. Provide email/password or call whoami first."
                )]

            client = self.session_manager.get_client()

            # Extract and validate parameters
            test_description = arguments.get("test_description", "").strip()
            url = arguments.get("url", "").strip()
            persona_ids = arguments.get("persona_ids", [])
            frame_type = arguments.get("frame_type", "Desktop")
            credentials = arguments.get("credentials", "").strip()

            if not test_description:
                return [TextContent(type="text", text="Error: test_description required")]
            if not url:
                return [TextContent(type="text", text="Error: url required")]
            if not persona_ids or len(persona_ids) == 0:
                return [TextContent(type="text", text="Error: At least one persona_id required")]

            # Normalize URL
            if not url.startswith("http://") and not url.startswith("https://"):
                url = f"https://{url}"

            logger.info(f"Creating experiment for: '{test_description}' at {url}")

            # Generate structured fields from test description
            hypothesis = f"Can users {test_description}?"
            goal = f"Users should {test_description}"

            # Generate title: capitalize first 4-6 words
            title_words = test_description.split()[:5]
            title = " ".join(title_words).title()

            # Fetch personas and experiment types
            personas_response = await client.get("/personas", params={"limit": 100})
            all_personas = personas_response.get("personas", personas_response) if isinstance(personas_response, dict) else personas_response
            selected_personas = [p for p in all_personas if p.get("id") in persona_ids]

            exp_types_response = await client.get("/experiments/types")

            # Build credentials string if provided
            creds = None
            if credentials:
                if ":" not in credentials:
                    return [TextContent(type="text", text="Error: credentials must be in format 'username:password'")]
                creds = f"username: {credentials.split(':')[0]}, password: {credentials.split(':')[1]}"

            # Call /experiments/types/suggest to get experiment_type_id
            suggest_payload = {
                "experimentTitle": title,
                "hypothesis": hypothesis,
                "goal": goal,
                "url": url,
                "frame_type": frame_type,
                "personas": [
                    {
                        "id": p.get("id"),
                        "name": p.get("name", ""),
                        "description": p.get("description", ""),
                        "traits": p.get("traits", {}),
                        "tendencies": p.get("tendencies", []),
                        "participants": p.get("participants", 0),
                    }
                    for p in selected_personas
                ],
                "availableExperimentTypes": [
                    {
                        "id": et.get("id"),
                        "name": et.get("name"),
                        "instructions": et.get("instructions"),
                        "success_indicators": None,
                        "prompt_specifics": None,
                    }
                    for et in exp_types_response
                ],
            }

            suggest_result = await client.post("/experiments/types/suggest", json=suggest_payload)
            experiment_type_id = suggest_result.get("suggested_experiment_type_id")

            if not experiment_type_id:
                return [TextContent(type="text", text="Error: Failed to determine experiment type")]

            # Create experiment
            experiment_payload = {
                "title": title,
                "hypothesis": hypothesis,
                "goal": goal,
                "url": url,
                "experiment_type_id": experiment_type_id,
                "persona_ids": persona_ids,
                "frame_type": frame_type,
                "status": "Draft",
                "credentials": creds,
            }

            logger.info(f"Creating experiment: {title}")
            create_response = await client.post("/experiments", json=experiment_payload)

            experiment_id = create_response.get("data", [{}])[0].get("experiment_id")
            if not experiment_id:
                return [TextContent(type="text", text="Error: Failed to get experiment ID")]

            # Run experiment
            logger.info(f"Running experiment {experiment_id}")
            run_response = await client.post(f"/experiments/{experiment_id}/run")

            if run_response.get("status") == "success":
                num_personas = len(persona_ids)
                estimated_minutes = round(5 + 7.2 * (0.5 + num_personas))

                result = f"""Experiment created and started!

Experiment ID: {experiment_id}
Title: {title}
Hypothesis: {hypothesis}
Goal: {goal}
URL: {url}
Personas: {num_personas}
Estimated Runtime: {estimated_minutes} minutes

Status: Running

View experiment at: {config.web_url}/experiments/{experiment_id}"""

                logger.info(f"Experiment {experiment_id} started successfully")
                return [TextContent(type="text", text=result)]
            else:
                error_msg = run_response.get("message", "Unknown error")
                return [TextContent(type="text", text=f"Experiment created but failed to start: {error_msg}")]

        except Exception as e:
            error_msg = f"Error creating experiment: {str(e)}"
            logger.exception("Error in create_experiment_from_description")
            return [TextContent(type="text", text=error_msg)]

    async def _list_experiments(self, arguments: dict) -> list[TextContent]:
        """List all past experiments for the user.

        Args:
            arguments: Dictionary with optional name_filter, status_filter, limit, email/password

        Returns:
            List containing formatted experiment list
        """
        try:
            # Ensure authenticated
            if not await self._ensure_authenticated(arguments):
                return [TextContent(
                    type="text",
                    text="Error: Not authenticated. Please provide email and password, or call whoami first."
                )]

            # Get authenticated client
            client = self.session_manager.get_client()

            # Extract optional parameters
            name_filter = arguments.get("name_filter", "").strip().lower()
            status_filter = arguments.get("status_filter", "").strip()
            limit = min(arguments.get("limit", 20), 100)  # Cap at 100

            # Fetch experiments
            logger.info("Fetching experiments...")
            params = {"limit": limit}
            if status_filter:
                params["status"] = status_filter

            response = await client.get("/experiments", params=params)

            # Handle response format (may be {experiments: [...]} or [...])
            experiments_list = response.get("experiments", response) if isinstance(response, dict) else response

            if not experiments_list:
                return [TextContent(type="text", text="No experiments found.")]

            # Apply name filter if provided (client-side filtering)
            if name_filter:
                experiments_list = [
                    exp for exp in experiments_list
                    if name_filter in exp.get("title", "").lower()
                ]

            if not experiments_list:
                return [TextContent(type="text", text=f"No experiments found matching '{name_filter}'.")]

            # Format response
            result = "Your Experiments:\n" + "=" * 50 + "\n\n"

            for exp in experiments_list:
                title = exp.get("title") or exp.get("name", "Untitled")
                # API may return 'id' or 'experiment_id'
                exp_id = exp.get("id") or exp.get("experiment_id") or exp.get("uuid", "")
                status = exp.get("status", "Unknown")
                url = exp.get("url", "")
                created_at = exp.get("created_at") or exp.get("createdAt", "")

                # Log if ID is missing for debugging
                if not exp_id:
                    logger.warning(f"Experiment missing ID. Available keys: {list(exp.keys())}")

                # Format date if available
                if created_at:
                    # Truncate to just date portion if it's a full timestamp
                    created_at = created_at[:10] if len(created_at) > 10 else created_at

                # Status indicator
                status_indicator = {
                    "Draft": "[Draft]",
                    "Running": "[Running]",
                    "Completed": "[Done]",
                    "Failed": "[Failed]"
                }.get(status, "[?]")

                result += f"{status_indicator} {title}\n"
                result += f"   ID: {exp_id if exp_id else '(not available)'}\n"
                result += f"   Status: {status}\n"
                if url:
                    result += f"   URL: {url}\n"
                if created_at:
                    result += f"   Created: {created_at}\n"
                result += "\n"

            result += f"Total: {len(experiments_list)} experiment(s)"

            if name_filter:
                result += f" (filtered by '{name_filter}')"

            result += "\n\nTo get detailed results, use:\nget_experiment_results(experiment_id=\"<id>\")"

            logger.info(f"Successfully retrieved {len(experiments_list)} experiments")
            return [TextContent(type="text", text=result)]

        except Exception as e:
            error_msg = f"Error fetching experiments: {str(e)}"
            logger.exception("Error in list_experiments")
            return [TextContent(type="text", text=error_msg)]

    async def _get_experiment_results(self, arguments: dict) -> list[TextContent]:
        """Get results of a running or completed experiment.

        Args:
            arguments: Dictionary with experiment_id and optional email/password

        Returns:
            List containing formatted experiment results
        """
        try:
            # Ensure authenticated
            if not await self._ensure_authenticated(arguments):
                return [TextContent(
                    type="text",
                    text="Error: Not authenticated. Please provide email and password, or call whoami first."
                )]

            experiment_id = arguments.get("experiment_id", "").strip()
            if not experiment_id:
                return [TextContent(type="text", text="Error: experiment_id is required")]

            # Get authenticated client
            client = self.session_manager.get_client()

            # Fetch full experiment results (includes personas, results, experiment_type)
            logger.info(f"Fetching results for experiment {experiment_id}...")
            response = await client.get(f"/experiments/{experiment_id}/results")

            if not response:
                return [TextContent(type="text", text=f"Error: Experiment {experiment_id} not found")]

            # Parse response structure
            experiment = response.get("experiment", {})
            personas = response.get("personas", [])
            experiment_type = response.get("experiment_type", {})
            results = response.get("results", [])

            # Build persona lookup for name resolution
            persona_lookup = {p.get("id"): p.get("name", "Unknown") for p in personas}

            # Extract experiment info
            title = experiment.get("title", "Untitled")
            status = experiment.get("status", "Unknown")
            hypothesis = experiment.get("hypothesis", "")
            goal = experiment.get("goal", "")
            url = experiment.get("url", "")
            summary = experiment.get("summary", "")
            exp_type_name = experiment_type.get("name", "")

            # Status indicator
            status_indicator = {
                "Draft": "[Draft]",
                "Running": "[Running]",
                "Completed": "[Done]",
                "Failed": "[Failed]",
                "Cancelled": "[Cancelled]",
                "Archived": "[Archived]"
            }.get(status, "[?]")

            # Build result string
            output = f"Experiment Results: {title}\n" + "=" * 50 + "\n\n"
            output += f"ID: {experiment_id}\n"
            output += f"Status: {status_indicator} {status}\n"
            if exp_type_name:
                output += f"Type: {exp_type_name}\n"
            output += f"URL: {url}\n"
            if hypothesis:
                output += f"Hypothesis: {hypothesis}\n"
            if goal:
                output += f"Goal: {goal}\n"

            # Experiment summary (global analysis)
            if summary:
                output += f"\nSummary:\n{summary}\n"

            # Persona results
            if results:
                output += "\n" + "-" * 50 + "\n"
                output += f"Persona Results ({len(results)}):\n"
                output += "-" * 50 + "\n"

                for i, res in enumerate(results, 1):
                    persona_id = res.get("persona_id", "")
                    persona_name = persona_lookup.get(persona_id, "Unknown Persona")
                    confidence = res.get("confidence")
                    journey_summary = res.get("summary", "")
                    metrics = res.get("metrics", {})
                    recommendations = res.get("recommendations", [])

                    # Extract metrics
                    completion_rate = metrics.get("completion_rate")
                    time_spent = metrics.get("time")
                    min_interactions = metrics.get("min_num_interactions")
                    max_interactions = metrics.get("max_num_interactions")

                    output += f"\n{i}. {persona_name}\n"

                    # Metrics line
                    metrics_parts = []
                    if completion_rate is not None:
                        metrics_parts.append(f"Completion: {completion_rate:.0f}%")
                    if time_spent is not None:
                        metrics_parts.append(f"Time: {time_spent:.1f}s")
                    if confidence is not None:
                        metrics_parts.append(f"Confidence: {confidence}%")
                    if min_interactions is not None and max_interactions is not None:
                        if min_interactions == max_interactions:
                            metrics_parts.append(f"Steps: {min_interactions}")
                        else:
                            metrics_parts.append(f"Steps: {min_interactions}-{max_interactions}")

                    if metrics_parts:
                        output += f"   {' | '.join(metrics_parts)}\n"

                    # Journey summary
                    if journey_summary:
                        # Truncate long summaries
                        if len(journey_summary) > 300:
                            journey_summary = journey_summary[:300] + "..."
                        output += f"\n   Journey: {journey_summary}\n"

                    # Recommendations
                    if recommendations:
                        output += "\n   Recommendations:\n"
                        for rec in recommendations[:5]:  # Limit to 5 recommendations
                            rec_text = rec.get("recommendation", "") if isinstance(rec, dict) else str(rec)
                            if rec_text:
                                # Truncate long recommendations
                                if len(rec_text) > 150:
                                    rec_text = rec_text[:150] + "..."
                                output += f"   * {rec_text}\n"
            else:
                if status == "Running":
                    output += "\nExperiment is still running. Results will be available when complete.\n"
                elif status == "Draft":
                    output += "\nExperiment has not been started yet.\n"
                else:
                    output += "\nNo persona results found.\n"

            # Add link to web interface
            output += f"\nView full details at:\n{config.web_url}/experiments/{experiment_id}"

            logger.info(f"Successfully retrieved results for experiment {experiment_id}")
            return [TextContent(type="text", text=output)]

        except Exception as e:
            error_msg = f"Error fetching experiment results: {str(e)}"
            logger.exception("Error in get_experiment_results")
            return [TextContent(type="text", text=error_msg)]

    async def _start_ngrok(self, arguments: dict) -> list[TextContent]:
        """Start an ngrok tunnel for a local port.

        Args:
            arguments: Dictionary with port and optional protocol

        Returns:
            List containing tunnel information with public URL
        """
        try:
            port = arguments.get("port")
            protocol = arguments.get("protocol", "http")

            if not port:
                return [TextContent(type="text", text="Error: port is required")]

            if not isinstance(port, int) or port < 1 or port > 65535:
                return [TextContent(type="text", text="Error: port must be between 1 and 65535")]

            # Check if tunnel already exists for this port
            if str(port) in self.ngrok_tunnels:
                existing_tunnel = self.ngrok_tunnels[str(port)]
                return [TextContent(
                    type="text",
                    text=f"Tunnel already exists for port {port}\n\nPublic URL: {existing_tunnel.public_url}\n\nUse stop_ngrok to close it first if you want to restart."
                )]

            logger.info(f"Starting ngrok tunnel for port {port} with protocol {protocol}")

            # Start ngrok tunnel
            tunnel = ngrok.connect(port, proto=protocol)
            public_url = tunnel.public_url

            # Store tunnel reference
            self.ngrok_tunnels[str(port)] = tunnel

            result = f"""ngrok tunnel started successfully!

Port: {port}
Protocol: {protocol}
Public URL: {public_url}

Use this URL in your experiments. The tunnel will remain active until you call stop_ngrok.

Example usage:
start_experiment(url="{public_url}", ...)"""

            logger.info(f"ngrok tunnel active: {public_url} -> localhost:{port}")
            return [TextContent(type="text", text=result)]

        except Exception as e:
            error_msg = f"Error starting ngrok: {str(e)}\n\nMake sure:\n1. ngrok is installed (pip install pyngrok)\n2. You have an ngrok account (sign up at ngrok.com)\n3. Your port is not already in use"
            logger.exception("Error in start_ngrok")
            return [TextContent(type="text", text=error_msg)]

    async def _get_ngrok_status(self, arguments: dict) -> list[TextContent]:
        """Check status of active ngrok tunnels.

        Args:
            arguments: Empty dictionary (no arguments needed)

        Returns:
            List containing status of all active tunnels
        """
        try:
            if not self.ngrok_tunnels:
                return [TextContent(type="text", text="No active ngrok tunnels.\n\nUse start_ngrok to create one.")]

            result = "Active ngrok tunnels:\n" + "=" * 50 + "\n\n"

            for port, tunnel in self.ngrok_tunnels.items():
                try:
                    # Get tunnel information
                    result += f"Port: {port}\n"
                    result += f"Public URL: {tunnel.public_url}\n"
                    result += f"Protocol: {tunnel.proto}\n"
                    result += f"Status: Active\n\n"
                except Exception as e:
                    result += f"Port: {port}\n"
                    result += f"Status: Error - {str(e)}\n\n"

            result += f"Total: {len(self.ngrok_tunnels)} tunnel(s)"

            logger.info(f"Retrieved status for {len(self.ngrok_tunnels)} tunnels")
            return [TextContent(type="text", text=result)]

        except Exception as e:
            error_msg = f"Error getting ngrok status: {str(e)}"
            logger.exception("Error in get_ngrok_status")
            return [TextContent(type="text", text=error_msg)]

    async def _stop_ngrok(self, arguments: dict) -> list[TextContent]:
        """Stop ngrok tunnel(s).

        Args:
            arguments: Dictionary with optional port

        Returns:
            List containing stop operation result
        """
        try:
            port = arguments.get("port")

            if port is not None:
                # Stop specific tunnel
                port_str = str(port)
                if port_str not in self.ngrok_tunnels:
                    return [TextContent(
                        type="text",
                        text=f"No active tunnel found for port {port}\n\nUse get_ngrok_status to see active tunnels."
                    )]

                tunnel = self.ngrok_tunnels[port_str]
                ngrok.disconnect(tunnel.public_url)
                del self.ngrok_tunnels[port_str]

                result = f"ngrok tunnel stopped for port {port}"
                logger.info(f"Stopped ngrok tunnel for port {port}")
                return [TextContent(type="text", text=result)]

            else:
                # Stop all tunnels
                if not self.ngrok_tunnels:
                    return [TextContent(type="text", text="No active tunnels to stop.")]

                count = len(self.ngrok_tunnels)
                ngrok.kill()
                self.ngrok_tunnels.clear()

                result = f"Stopped all ngrok tunnels ({count} tunnel(s))"
                logger.info(f"Stopped all {count} ngrok tunnels")
                return [TextContent(type="text", text=result)]

        except Exception as e:
            error_msg = f"Error stopping ngrok: {str(e)}"
            logger.exception("Error in stop_ngrok")
            return [TextContent(type="text", text=error_msg)]

    async def run(self):
        """Run the MCP server."""
        logger.info("Starting Blok MCP server...")
        logger.info(f"Blok API URL: {config.blok_api_url}")
        logger.info(f"Debug mode: {config.debug}")

        async with stdio_server() as (read_stream, write_stream):
            # Create initialization options with explicit capabilities declaration
            init_options = self.server.create_initialization_options()

            await self.server.run(
                read_stream,
                write_stream,
                init_options,
            )
