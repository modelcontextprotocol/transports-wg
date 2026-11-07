# Tool Streaming Brief

## Goal

Improve observability and steerability of Tools that produce content during execution.

## Core Principle

Tools invoked by LLMs commonly emit partial results during execution. This can include:
 - Agentic Tools streaming results as text chunks as they become available
 - Image, Video or Audio generating tools producing partial results or streams 
 - Database Queries streaming large volumes of data at variable rates
 - Computer Use or Sandbox tools emitting output and error streams.

MCP is currently limited to sending updates via `notification/progress`[^1], or using undocumented `resource/subscribe` side-channel approaches to share progress.

This limits the use of MCP for tasks that would benefit from early information sharing e.g. error conditions from delegated tasks, or content generation that does not meet requirements. It also allows Users to interact with the information  

## Key Requirements:

The requirements for MCP Tools are to:
 - Provide a common way for MCP Servers to efficiently deliver partial results Hosts.
 - Signal whether updates are intended to be supervised by Model or User to allow monitoring or other interventions (steer/cancel) during the execution. 
 - Handle supported modalities and data types cleanly (e.g. Text, Image, Audio, Structured) 
 - Consider conventions for handover and connectivity to live streaming models (realtime voice or video models for example).

## Key Design Decisions:

 - When to use MCP Apps vs. new built-ins for delivering interactive content.

[^1] MCP Apps uses this mechanism to stream content.