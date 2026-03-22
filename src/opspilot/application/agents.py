import asyncio
import json
import logging
from typing import Any
from opspilot.core.llm import generate_completion

logger = logging.getLogger(__name__)

def run_chat_agent(query: str, company: dict[str, Any] | None, report_period: str | None) -> dict[str, Any]:
    """
    Main entry point for the Conversational Data Query Agent.
    Replaces the mock chat_turn with actual LLM generation grounded in BM25 RAG.
    """
    system_prompt = """
    You are an intelligent Financial Operations & Decision Support Agent.
    Your task is to analyze the user's query against the provided Context Evidence (which are excerpts from official financial reports), and provide a well-structured JSON response.
    Your answer must be grounded ONLY on the contextual evidence provided. If the evidence doesn't contain the answer, state that clearly in the summary.
    Do NOT output raw markdown text, ONLY valid JSON.
    The required JSON schema:
    {
      "query": "The original query",
      "query_type": "metric_query" | "company_scoring" | "risk_scan",
      "summary": "A comprehensive paragraph summarizing your analytical conclusion containing data citations.",
      "metrics": [
         {"name": "Metric Name", "value": "Metric Value", "unit": "Unit", "trend": "up|down|flat"}
      ],
      "actions": [
         {"priority": "high|medium|low", "title": "Action title", "action": "Action steps", "reason": "Why?"}
      ]
    }
    """
    
    context_text = ""
    company_name = company.get("company_name") if company else None
    
    if company and "company_id" in company:
        # Perform Local BM25 Retrieval
        try:
            from opspilot.infra.chunk_retriever import LocalChunkRetriever
            from pathlib import Path
            # hardcode the bronze directory path as we know it from docker-compose
            bronze_dir = Path("data/bronze/official/chunks")
            retriever = LocalChunkRetriever(bronze_dir)
            
            # The company_id is the security code (e.g. 600438)
            security_code = company["company_id"]
            
            # Execute Hybrid RAG (BM25 + Semantic PgVector)
            from opspilot.config import get_settings
            import asyncio
            chunks = asyncio.run(
                retriever.hybrid_search(
                    security_code=security_code,
                    query=query,
                    dsn=get_settings().postgres_dsn,
                    report_period=report_period,
                    top_k=6
                )
            )
            
            if chunks:
                context_text = "\n\n".join([f"Excerpt {i+1}:\n{c.get('text', '')}" for i, c in enumerate(chunks)])
            else:
                context_text = "No relevant official report excerpts found."
        except Exception as e:
            logger.error(f"Failed to retrieve chunks: {e}")
            context_text = "RAG Search Failed."
            
    prompt = f"User Query: {query}\n"
    if company_name:
        prompt += f"Target Company: {company_name}\n"
    if report_period:
        prompt += f"Report Period: {report_period}\n"
        
    prompt += f"\n--- Context Evidence ---\n{context_text}\n------------------------\n"
    prompt += "Now, respond strictly in JSON matching the schema."
    
    tools_schema = [
        {
            "type": "function",
            "function": {
                "name": "lookup_financial_metric",
                "description": "Lookup an exact financial metric from the enterprise data lake if Context Evidence lacks precision.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric_name": {
                            "type": "string", 
                            "description": "The target financial metric, e.g. '营业总收入', '净利润'"
                        },
                    },
                    "required": ["metric_name"]
                }
            }
        }
    ]
        
    try:
        response_text = asyncio.run(
            generate_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                model="gpt-4o-mini",
                temperature=0.2,
                tools=tools_schema
            )
        )
        
        # Strip markdown code blocks if the LLM wraps the json
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        payload = json.loads(response_text.strip())
        return payload
    except Exception as e:
        logger.error(f"Chat Agent execution failed: {e}")
        # Fallback payload matching the schema
        return {
            "query": query,
            "query_type": "metric_query",
            "summary": f"执行分析时发生错误(Agent Error): {e}",
            "metrics": [],
            "actions": []
        }

def run_stress_agent(company_name: str, scenario: str, report_period: str | None) -> dict[str, Any]:
    """
    Risk Agent for Stress Testing Propagation.
    """
    system_prompt = """
    You are a Systemic Risk & Stress Test Agent modeling supply chain impacts.
    You will return a JSON describing the propagation of extreme scenarios.
    JSON schema REQUIRED:
    {
      "severity": {"level": "CRITICAL|HIGH|MEDIUM|LOW", "label": "Short label", "color": "risk|warning|safe"},
      "propagation_steps": [
         {"step": 1, "title": "Node title", "detail": "Detailed disruption mechanics"}
      ],
      "transmission_matrix": [
         {"stage": "upstream", "headline": "Impact summary", "impact_score": "-10.5%", "impact_label": "Text metric"},
         {"stage": "midstream", "headline": "Impact summary", "impact_score": "-5.2%", "impact_label": "Text metric"},
         {"stage": "downstream", "headline": "Impact summary", "impact_score": "-2.1%", "impact_label": "Text metric"}
      ],
      "simulation_log": [
         {"step": 1, "title": "Event timestamp or sequence", "detail": "Log message of what occurred"}
      ]
    }
    """
    prompt = f"Target Company: {company_name}\nStress Scenario: {scenario}\nPeriod: {report_period}\n"
    try:
        response_text = asyncio.run(
            generate_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                model="gpt-4o",
                temperature=0.6
            )
        )
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        return json.loads(response_text.strip())
    except Exception as e:
        logger.error(f"Stress Agent execution failed: {e}")
        return {
            "severity": {"level": "ERROR", "label": "Failed Simulation", "color": "warning"},
            "propagation_steps": [],
            "transmission_matrix": [],
            "simulation_log": []
        }
