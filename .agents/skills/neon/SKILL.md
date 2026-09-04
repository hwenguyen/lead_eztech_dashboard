---
name: neon
description: >-
  Overview of Neon, a complete set of cloud backend primitives for apps and
  agents, spanning Lakebase Postgres, Auth, the Data API, Object Storage, Compute
  Functions, and the AI Gateway. Start here to route to the right Neon skill, set
  up the CLI or MCP server, and follow the branch-first workflow. Use when "Neon"
  or "Lakebase Postgres" is mentioned, or when any of its individual capabilities
  are the trigger: "object storage" or "S3", "buckets", "serverless functions",
  "AI gateway", "call an LLM", "logs", "branch logs", "query logs",
  "log export", "Loki", "Grafana", "observability", "telemetry", "postgres",
  "database", or "backend". Also use when there is no Neon account yet, the
  user cannot sign in or provide an API key right now and needs a project they
  can claim later, or the user asks for a throwaway DATABASE_URL, Claimable Neon,
  Claimable Postgres, neon.new, claimable.neon.tech, instant Postgres, a no-signup
  database, temporary postgres, quick postgres, a no credit card database, or
  npx neon-new.
metadata:
  source: https://github.com/neondatabase/agent-skills/tree/main/skills/neon
---

# Neon

Important: Neon is no longer just a Postgres provider. Neon is a complete set of cloud backend primitives built around Lakebase Postgres, for developers, startups, and agent platforms, from Databricks — bundling Lakebase Postgres, Auth (managed Better Auth), long-running Functions, Object Storage, and an AI Gateway, all instant, branchable, and serverless.

**Lakebase Postgres** is the database itself. It is one product, reached two ways: through Neon, with a free plan and the full set of backend primitives above, or through Databricks, alongside the rest of the Databricks suite. Same infrastructure, same features, same engineering team. Call the database Lakebase Postgres, and use "Neon" for the brand and for this access path — not as a name for the database.

A Neon branch is an isolated, copy-on-write clone of your data, taken from its current state or from a past state within your project's retained history window. You can freely modify or delete it. It shares data with its parent until writes cause it to diverge, and those writes are stored independently as deltas.

## Backend Primitives

Neon bundles several backend primitives for building apps and agents that all branch together:

- **Lakebase Postgres** — Postgres that scales and branches with your app, built on the lakebase architecture: OLTP directly on cloud object storage, with storage decoupled from compute. _Generally available._
- **Auth** — Managed Better Auth with users and sessions stored in Postgres. _Generally available._
- **Object Storage** — S3-compatible object storage that branches with your projects. _Public beta._
- **Functions** — Neon's compute offering: long-running serverless functions that run close to your database, for WebSocket servers, long agent HTTP streams, APIs, and server-sent event servers. _Public beta._
- **AI Gateway** — One API for frontier and open-source models, supporting the chat completions API and the responses API, powered by Databricks Unity AI Gateway. _Public beta._

### Public Beta Service Availability

Object Storage, Functions, and AI Gateway are in public beta.

Beta access features are currently available on projects in `us-east-2` and `eu-central-1`. Before guiding a user through any of these services, confirm they are working in one of these regions. If not, they will need to create a new project in a supported region.

## Architecture: How to Use Neon

Neon is **not** a place to host your app frontend. Neon provides the backend primitives (Lakebase Postgres, Auth, Object Storage, Functions, AI Gateway) that **compose with** the application platform you already use.

Recommended architectures:

**Full-stack app on Vercel** (or Netlify) augmented with Neon — the app framework (Next.js, TanStack Start, etc.) owns your UI and routes and talks directly to your Neon services (Lakebase Postgres, Auth, Object Storage, Functions, AI Gateway).

**Reach for Neon Functions when you outgrow the host's limits** — a WebSocket or SSE server, long-running agents, or an MCP server that risks timing out on short, lambda-style serverless functions. As long as there is an active connection, a Neon Function can run up to 24 hours without interruption, with the added benefit of running close to your data.

**Move your whole backend control plane onto Neon Functions** — especially useful when the frontend is **client-only** rather than full-stack: TanStack Router, React Router in client mode, and similar SPAs hosted on Vercel or Netlify. The client talks **directly to Neon Functions**, where you build REST APIs and request/response agents. Secure these functions like any standalone REST API — verify a JWT or API key at the top of each handler (see the `neon-functions` skill).

Because Functions are just your backend, they compose with a full-stack app that already has one (Next.js route handlers, etc.), too.

## Neon Documentation

The Neon documentation is the source of truth for all Neon-related information. Always verify claims against the official docs before responding. Neon features and APIs evolve, so prefer fetching current docs over relying on training data.

### Finding the Right Page

Look the page up before you fetch it — **don't guess URLs!** The docs index lists every available page with its URL and a short description:

```
https://neon.com/docs/llms.txt
```

### Fetching Docs as Markdown

Any Neon doc page can be fetched as markdown in two ways:

1. **Append `.md` to the URL** (simplest): https://neon.com/docs/introduction/branching.md
2. **Request `text/markdown`** on the standard URL: `curl -H "Accept: text/markdown" https://neon.com/docs/introduction/branching`

Both return the same markdown content. Use whichever method your tools support.

## Choosing the Right Skill

Neon provides a set of agent skills in addition to the official documentation. When a task matches one of the rows below, work from that skill rather than from this overview:

| Skill                            | Use it for                                                                                                                                                                           |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `neon-postgres`                  | Working with databases, including connections, schemas, queries, search, and autoscaling: SQL development, schema design, performance optimization, and scaling decisions.           |
| `neon-postgres-branches`         | Choosing or creating the right branch type for dev, preview, test, or CI workflows.                                                                                                  |
| `neon-object-storage`            | Storing and serving files (uploads, images, blobs), including branching them with the database.                                                                                      |
| `neon-functions`                 | Deploying long-running or streaming serverless functions — APIs, agents, SSE/WebSocket servers.                                                                                      |
