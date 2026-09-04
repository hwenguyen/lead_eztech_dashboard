---
name: neon-postgres
description: >-
  Guides and best practices for working with Lakebase Postgres, the database
  behind Neon. Covers setup, connection methods and drivers, pooled vs direct
  connections, branching, schema migrations, autoscaling, scale-to-zero, instant
  restore, read replicas, connection pooling, IP allow lists, and logical
  replication. Also covers Lakebase Search: semantic vector search, full-text
  search with BM25 ranking, and hybrid search.
  Use when users ask about "Lakebase Postgres", "Neon setup", "connect to Neon",
  "Neon project", "DATABASE_URL", "serverless Postgres", "Neon CLI", "neon", "Neon MCP",
  "Neon Auth", "@neondatabase/serverless", "@neondatabase/neon-js",
  "scale to zero", "Neon autoscaling", "Neon read replica",
  "Neon connection pooling", "schema migrations", "semantic search", "vector
  search", "full-text search", "BM25", or "hybrid search".
metadata:
  parent: neon
  source: https://github.com/neondatabase/agent-skills/tree/main/skills/neon-postgres
---

**FIRST**: Use the parent `neon` skill for a Neon overview, getting started with Neon, Neon development best practices, and more.

# Lakebase Postgres

Lakebase Postgres is the database at the core of Neon. It runs on the lakebase architecture — OLTP built directly on cloud object storage — which decouples storage from compute to offer autoscaling, branching, instant restore, and scale-to-zero. It's fully compatible with Postgres and works with any language, framework, or ORM that supports Postgres.

It is the same database whether you reach it through Neon or through Databricks; this skill covers the Neon access path.

## Setup Flow

### 1. Select the organization and project

Use the CLI (default) or MCP server to list organizations and projects. Let the user select an existing project or create a new one. Check the `.neon` file for an existing linked project or branch.

### 2. Get the connection string

Use the CLI (default), `neon env pull`, or the MCP server to get the connection string. Store it in `.env` as `DATABASE_URL`. Read the file first before modifying it, to avoid overwriting existing values.

#### When to use pooled vs direct connections

| Use case                                 | Connection type  |
| ---------------------------------------- | ---------------- |
| Web applications, serverless functions   | Pooled (-pooler) |
| Schema migrations                        | Direct           |
| pg_dump / pg_restore                     | Direct           |
| Logical replication                      | Direct           |
| Long-running analytics with temp tables  | Direct           |
| Admin tasks needing SET or session state | Direct           |
| LISTEN / NOTIFY                          | Direct           |

### 3. Pick the connection method and driver

Always pair Neon with an ORM such as **Drizzle** or **SQLAlchemy** for easy schema management and migrations.

Recommendations:
- **Python / SQLAlchemy**: Use `psycopg2` or `asyncpg` with connection pooling.
- **Node.js**: Use `pg` (`node-postgres`) or `@neondatabase/serverless` with Drizzle/Prisma.
