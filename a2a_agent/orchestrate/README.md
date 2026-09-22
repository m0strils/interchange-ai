# Orchestrate registration

What this is: a registration file (`interchange-knowledge.yaml`) that lets IBM
watsonx Orchestrate add the Interchange knowledge agent as an external A2A
agent, plus this short note.

The two commands, once the server is deployed to Render and `<render-host>`
in the YAML is replaced with the real host:

```bash
orchestrate agents import -f a2a_agent/orchestrate/interchange-knowledge.yaml
orchestrate agents discover -u https://<render-host>
```

What is and is not claimed: this registers against a personal, 30-day
watsonx Orchestrate trial tenant, to demonstrate that a third-party
enterprise orchestration platform can discover and call the Interchange
agent over A2A. It is not a production integration, not a paid tenant, and
not a claim that watsonx Orchestrate is used anywhere beyond this demo.
