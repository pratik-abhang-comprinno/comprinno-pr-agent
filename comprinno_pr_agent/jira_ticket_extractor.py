"""
Jira Ticket Extractor - Extract ticket ID from PR name and fetch full details
"""
import re
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from jira_provider import JiraProvider

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.pr_context', 'jira_cache.json')
CACHE_TTL_HOURS = 1


class JiraTicketExtractor:
    def __init__(self):
        try:
            self.jira = JiraProvider()
        except Exception as e:
            print(f"⚠️  Jira initialization warning: {e}")
            self.jira = None
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_cache(self):
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(self._cache, f, indent=2)

    def _is_cache_valid(self, ticket_id: str) -> bool:
        entry = self._cache.get(ticket_id)
        if not entry:
            return False
        fetched_at = datetime.fromisoformat(entry['fetched_at'])
        return datetime.now() - fetched_at < timedelta(hours=CACHE_TTL_HOURS)
    
    def extract_ticket_id(self, pr_name: str) -> Optional[str]:
        """
        Extract Jira ticket ID from PR name
        
        Handles formats:
            "[AAS-29]" -> "AAS-29"
            "AAS-29-feature" -> "AAS-29"
            "AAS29-feature" -> "AAS29"
            "feature/AAS-29" -> "AAS-29"
            "AAS-29" -> "AAS-29"
        
        Args:
            pr_name: PR title or branch name
            
        Returns:
            Ticket ID or None if not found
        """
        if not pr_name:
            return None
        
        # Pattern 1: [AAS-29] or [AAS29]
        pattern1 = r'\[([A-Z]{2,10}-?\d+)\]'
        match = re.search(pattern1, pr_name)
        if match:
            return match.group(1).upper()
        
        # Pattern 2: AAS-29 or AAS29 (with or without dash)
        pattern2 = r'\b([A-Z]{2,10}-?\d+)\b'
        match = re.search(pattern2, pr_name, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        
        return None
    
    def get_ticket_info(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Fetch ticket info from cache or Jira"""
        if self._is_cache_valid(ticket_id):
            print(f"📦 Using cached Jira ticket: {ticket_id}")
            return self._cache[ticket_id]['data']

        if not self.jira:
            return None

        issue = self.jira.get_issue(ticket_id)
        if not issue:
            return None

        ticket_info = {
            'ticket_id': issue['key'],
            'title': issue['summary'],
            'description': issue['description'],
            'type': issue['issue_type'],
            'status': issue['status'],
            'priority': issue['priority'],
            'assignee': issue['assignee'],
            'created': issue['created'],
            'updated': issue['updated'],
            'url': issue['url'],
            'acceptance_criteria': self._extract_acceptance_criteria(issue['description'])
        }

        self._cache[ticket_id] = {
            'fetched_at': datetime.now().isoformat(),
            'data': ticket_info
        }
        self._save_cache()
        print(f"✅ Fetched and cached Jira ticket: {ticket_id}")
        return ticket_info
    
    def _extract_acceptance_criteria(self, description: Any) -> list:
        """Extract acceptance criteria from description"""
        if not description:
            return []
        
        desc_str = str(description)
        criteria = []
        
        # Look for AC- patterns or bullet points
        lines = desc_str.split('\n')
        for line in lines:
            if 'AC-' in line or 'acceptance' in line.lower():
                criteria.append(line.strip())
        
        return criteria
    
    def extract_and_fetch(self, pr_name: str) -> Optional[Dict[str, Any]]:
        """
        Extract ticket ID from PR name and fetch full ticket info
        
        Args:
            pr_name: PR title or branch name
            
        Returns:
            Complete ticket information or None
        """
        ticket_id = self.extract_ticket_id(pr_name)
        
        if not ticket_id:
            print(f"❌ No ticket ID found in: {pr_name}")
            return None
        
        print(f"✅ Extracted ticket ID: {ticket_id}")
        
        ticket_info = self.get_ticket_info(ticket_id)
        
        if not ticket_info:
            print(f"❌ Ticket not found in Jira: {ticket_id}")
            return None
        
        print(f"✅ Fetched ticket: {ticket_info['title']}")
        return ticket_info
    

