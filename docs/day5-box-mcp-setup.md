# Optional: Box MCP connection checklist

> Current MVP decision: Box MCP is not required for Agentic Cinema — IBM Track.
> Keep this document only as a future reference for optional media search or asset
> management. Do not delay Gemini, Google ADK, FFmpeg, or IBM Bob work for Box.

## Confirmed design

Use the hosted remote Box MCP server at `https://mcp.box.com` with the server name `box-remote-mcp`. Do not begin new work with the deprecated self-hosted Box MCP project.

Ride Storyteller will only use read-oriented tools. No delete, move, or write action is part of the prototype.

## Required user-controlled setup

1. In the Box Admin Console, enable Box MCP for the applicable account or enterprise.
2. Create Box Integration Credentials for the custom client.
3. Register the Ride Storyteller OAuth callback. Use HTTPS for a deployed web app;
   Box also permits HTTP only for a `localhost` or loopback URI during local development.
4. Configure the minimum scopes required by the Box setup, including Content Actions when required by the configured MCP tools.
5. Put the resulting client ID, client secret, redirect URI, and scopes in a local `.env` file. Never put them in `.env.example`, source code, test fixtures, or Notion.

## Local check before any connection

Run `python -m app.mcp.preflight`. It only reports field names that are missing or structurally invalid. It does not print secret values, open a browser, authenticate, or call Box.

## Remaining required verification

- The precise Box MCP tools enabled for this account and their read-only permission boundaries.
- OAuth consent and redirect completion with a real Box account.
- Whether this Developer environment can narrow the initially displayed application
  scopes to the minimum read-only access required by the selected Box MCP tools.
- A short test video can be discovered by the agent through Box MCP.
- The exact Agentic Cinema Google Cloud environment can host or connect an MCP client with this OAuth flow. This is not established by the local configuration check or an ADK-only proof.

## Official references

- [Box MCP Server](https://developer.box.com/guides/box-mcp/)
- [Box OAuth 2.0](https://developer.box.com/guides/authentication/oauth2/)
- [Box self-hosted MCP status](https://developer.box.com/guides/box-mcp/self-hosted/)
