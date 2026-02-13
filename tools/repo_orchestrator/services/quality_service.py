from datetime import datetime
from typing import List
from tools.repo_orchestrator.models import AgentQuality

class QualityService:
    @staticmethod
    def get_agent_quality(agent_id: str) -> AgentQuality:
        """
        Analyzes the quality of an agent's reasoning and output.
        Currently uses heuristics and simulated analysis for Phase 4 demo.
        """
        # Simulated metrics based on agent_id
        # In a real implementation, this would query GICS or analyze logs
        if "bridge" in agent_id:
            return AgentQuality(
                score=65,
                alerts=["repetition"],
                lastCheck=datetime.now().isoformat()
            )
        
        # Default high quality for orchestrator
        return AgentQuality(
            score=98,
            alerts=[],
            lastCheck=datetime.now().isoformat()
        )

    @staticmethod
    def analyze_output(text: str) -> AgentQuality:
        """
        Heuristic analysis of text for degradation.
        Detects repetition, length anomalies, etc.
        """
        alerts = []
        
        # Very basic repetition detection
        words = text.lower().split()
        if len(words) > 20:
            # Check for repeated phrases of 3 words
            phrases = [" ".join(words[i:i+3]) for i in range(len(words)-3)]
            if len(phrases) > len(set(phrases)) + 2:
                alerts.append("repetition")
        
        # Length anomaly (too short for reasoning)
        if len(text) < 50:
            alerts.append("coherence")
            
        score = 100 - (len(alerts) * 25)
        
        return AgentQuality(
            score=max(0, score),
            alerts=alerts,
            lastCheck=datetime.now().isoformat()
        )
