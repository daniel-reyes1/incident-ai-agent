# Incident AI Agent

## Overview

This project is a prototype AI-powered incident analysis agent designed to assist Site Reliability Engineering (SRE) workflows. It simulates how an AI system can interpret infrastructure incidents and generate structured operational recommendations.

The current version uses Google’s Gemini model to analyze synthetic incident data and produce structured diagnostic outputs.

---

## Problem Statement

Incident response in infrastructure environments is often:

* Slow due to manual log interpretation
* Fragmented across multiple tools and dashboards
* Dependent on individual expertise

This project explores how an AI agent can accelerate early-stage incident understanding by:

* Summarizing incident context
* Generating ranked hypotheses
* Suggesting investigation steps
* Proposing mitigation actions

---

## System Design (Current Prototype)

The system currently consists of:

* A simulated incident input (JSON structure)
* A prompt engineering layer
* Google Gemini (via `google-genai`)
* A simple execution script

### Flow

Incident (structured JSON)
→ Prompt builder
→ Gemini model
→ Structured SRE-style output

---

## Tech Stack

* Python 3.12+
* Google Gemini API (`google-genai`)
* Python-dotenv
* Git / GitHub
* VS Code

---

## Project Structure

```
incident-ai-agent/
│
├── src/
│   └── agent.py            # Main AI agent logic
│
├── test_connection.py      # API connectivity test
├── requirements.txt        # Dependencies
├── .env                    # API key (not committed)
├── .gitignore             # Ignored files
└── README.md              # Project documentation
```

---

## Setup Instructions

### 1. Clone repository

```
git clone https://github.com/daniel-reyes1/incident-ai-agent.git
cd incident-ai-agent
```

### 2. Create virtual environment

```
py -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```
py -m pip install -r requirements.txt
```

### 4. Configure API key

Create a `.env` file:

```
GOOGLE_API_KEY=your_api_key_here
```

---

## Run the Agent

Test API connection:

```
py test_connection.py
```

Run incident agent:

```
py src\agent.py
```

---

## Example Output

The agent produces structured responses such as:

* Possible root causes (ranked)
* Investigation steps
* Mitigation actions
* Required diagnostic data

---

## Current Limitations

* Uses simulated incident inputs only
* No real-time monitoring integration
* No retrieval (RAG) layer yet
* Dependent on Gemini API quota/billing status

---

## Roadmap

### Phase 1 (Current)

* Basic Gemini-powered incident reasoning

### Phase 2

* Structured prompt system
* JSON schema enforcement
* Modular agent architecture

### Phase 3

* Retrieval-Augmented Generation (runbooks, logs, past incidents)
* Incident memory layer

### Phase 4

* Multi-agent system (triage + diagnostics + resolution planning)
* Integration with observability tools

---

## Objective

The goal of this project is to explore how agentic AI systems can improve:

* Incident response speed
* Decision-making quality
* Operational clarity in SRE environments

---

## Author

Daniel Reyes
GitHub: https://github.com/daniel-reyes1
