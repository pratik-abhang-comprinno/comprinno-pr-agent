"""
Jira Provider - Integration with Atlassian Jira
Provides methods to query and interact with Jira issues
"""
import os
import requests
from typing import Dict, List, Any, Optional
from requests.auth import HTTPBasicAuth
import json


class JiraProvider:
    def __init__(self, jira_url: str = None, email: str = None, api_token: str = None):
        """
        Initialize Jira provider
        
        Args:
            jira_url: Jira instance URL (e.g., https://yourcompany.atlassian.net)
            email: User email for authentication
            api_token: Jira API token
        """
        self.jira_url = (jira_url or os.getenv('JIRA_URL', '')).rstrip('/')
        self.email = email or os.getenv('JIRA_EMAIL')
        self.api_token = api_token or os.getenv('JIRA_API_TOKEN')
        
        if not self.jira_url:
            raise ValueError("JIRA_URL not provided")
        if not self.email:
            raise ValueError("JIRA_EMAIL not provided")
        if not self.api_token:
            raise ValueError("JIRA_API_TOKEN not provided")
        
        self.auth = HTTPBasicAuth(self.email, self.api_token)
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        
        # Test connection
        self._test_connection()
    
    def _test_connection(self):
        """Test Jira connection"""
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/myself",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            user_info = response.json()
            print(f"✅ Connected to Jira as: {user_info.get('displayName', 'Unknown')}")
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to connect to Jira: {e}")
    
    def get_issue(self, issue_key: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a Jira issue
        
        Args:
            issue_key: Jira issue key (e.g., PROJ-123)
            
        Returns:
            Dictionary with issue details or None if not found
        """
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/issue/{issue_key}",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            issue = response.json()
            
            return self._format_issue(issue)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return None
            raise
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching issue {issue_key}: {e}")
            return None
    
    def search_issues(self, jql: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """
        Search Jira issues using JQL
        
        Args:
            jql: JQL query string
            max_results: Maximum number of results to return
            
        Returns:
            List of issues matching the query
        """
        try:
            response = requests.post(
                f"{self.jira_url}/rest/api/3/search/jql",
                auth=self.auth,
                headers=self.headers,
                json={
                    'jql': jql,
                    'maxResults': max_results,
                    'fields': ['summary', 'status', 'assignee', 'priority', 'issuetype', 'created', 'updated', 'description']
                },
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            
            return [self._format_issue(issue) for issue in data.get('issues', [])]
        except requests.exceptions.RequestException as e:
            print(f"❌ Error searching issues: {e}")
            return []
    
    def get_projects(self) -> List[Dict[str, Any]]:
        """
        Get all accessible Jira projects
        
        Returns:
            List of projects with key, name, and type
        """
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/project",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            projects = response.json()
            
            return [{
                'key': p.get('key'),
                'name': p.get('name'),
                'type': p.get('projectTypeKey'),
                'id': p.get('id')
            } for p in projects]
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching projects: {e}")
            return []
    
    def get_issue_types(self, project_key: str = None) -> List[Dict[str, Any]]:
        """
        Get available issue types
        
        Args:
            project_key: Optional project key to get project-specific types
            
        Returns:
            List of issue types
        """
        try:
            if project_key:
                response = requests.get(
                    f"{self.jira_url}/rest/api/3/project/{project_key}",
                    auth=self.auth,
                    headers=self.headers,
                    timeout=10
                )
                response.raise_for_status()
                project = response.json()
                issue_types = project.get('issueTypes', [])
            else:
                response = requests.get(
                    f"{self.jira_url}/rest/api/3/issuetype",
                    auth=self.auth,
                    headers=self.headers,
                    timeout=10
                )
                response.raise_for_status()
                issue_types = response.json()
            
            return [{
                'id': it.get('id'),
                'name': it.get('name'),
                'description': it.get('description', ''),
                'subtask': it.get('subtask', False)
            } for it in issue_types]
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching issue types: {e}")
            return []
    
    def get_statuses(self, project_key: str = None) -> List[Dict[str, Any]]:
        """
        Get available statuses
        
        Args:
            project_key: Optional project key to get project-specific statuses
            
        Returns:
            List of statuses
        """
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/status",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            statuses = response.json()
            
            return [{
                'id': s.get('id'),
                'name': s.get('name'),
                'category': s.get('statusCategory', {}).get('name', '')
            } for s in statuses]
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching statuses: {e}")
            return []
    
    def get_custom_fields(self) -> List[Dict[str, Any]]:
        """
        Get all custom fields in Jira
        
        Returns:
            List of custom fields with their IDs and names
        """
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/field",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            fields = response.json()
            
            custom_fields = [f for f in fields if f.get('custom', False)]
            
            return [{
                'id': f.get('id'),
                'name': f.get('name'),
                'type': f.get('schema', {}).get('type', 'unknown'),
                'custom': f.get('custom', False)
            } for f in custom_fields]
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching custom fields: {e}")
            return []
    
    def find_issue_by_branch(self, branch_name: str, project_keys: List[str] = None) -> Optional[Dict[str, Any]]:
        """
        Find Jira issue by extracting key from branch name
        
        Args:
            branch_name: Git branch name (e.g., feature/PROJ-123-add-feature)
            project_keys: Optional list of project keys to search in
            
        Returns:
            Issue details if found, None otherwise
        """
        import re
        
        # Extract issue key pattern (e.g., PROJ-123)
        if project_keys:
            pattern = r'\b(' + '|'.join(project_keys) + r')-\d+\b'
        else:
            pattern = r'\b([A-Z]{2,10})-\d+\b'
        
        match = re.search(pattern, branch_name, re.IGNORECASE)
        if match:
            issue_key = match.group(0).upper()
            return self.get_issue(issue_key)
        
        return None
    
    def find_issue_by_pr_title(self, pr_title: str, project_keys: List[str] = None) -> Optional[Dict[str, Any]]:
        """
        Find Jira issue by extracting key from PR title
        
        Args:
            pr_title: Pull request title
            project_keys: Optional list of project keys to search in
            
        Returns:
            Issue details if found, None otherwise
        """
        import re
        
        # Extract issue key pattern
        if project_keys:
            pattern = r'\b(' + '|'.join(project_keys) + r')-\d+\b'
        else:
            pattern = r'\b([A-Z]{2,10})-\d+\b'
        
        match = re.search(pattern, pr_title, re.IGNORECASE)
        if match:
            issue_key = match.group(0).upper()
            return self.get_issue(issue_key)
        
        return None
    
    def _extract_text_from_adf(self, adf) -> str:
        """Extract plain text from Atlassian Document Format (ADF)"""
        if not adf:
            return ''
        if isinstance(adf, str):
            return adf
        if not isinstance(adf, dict):
            return str(adf)

        text_parts = []
        content = adf.get('content', [])
        for block in content:
            block_type = block.get('type', '')
            if block_type in ('paragraph', 'heading', 'bulletList', 'orderedList', 'listItem', 'blockquote'):
                for inline in block.get('content', []):
                    if inline.get('type') == 'text':
                        text_parts.append(inline.get('text', ''))
                    elif inline.get('type') in ('listItem', 'bulletList', 'orderedList'):
                        text_parts.append(self._extract_text_from_adf(inline))
                text_parts.append('\n')
        return ''.join(text_parts).strip()

    def _format_issue(self, issue: Dict) -> Dict[str, Any]:
        """Format raw Jira issue data into simplified structure"""
        fields = issue.get('fields', {})
        raw_description = fields.get('description', '')

        return {
            'key': issue.get('key'),
            'id': issue.get('id'),
            'summary': fields.get('summary', ''),
            'description': self._extract_text_from_adf(raw_description),
            'status': fields.get('status', {}).get('name', ''),
            'status_category': fields.get('status', {}).get('statusCategory', {}).get('name', ''),
            'issue_type': fields.get('issuetype', {}).get('name', ''),
            'priority': fields.get('priority', {}).get('name', '') if fields.get('priority') else 'None',
            'assignee': fields.get('assignee', {}).get('displayName', 'Unassigned') if fields.get('assignee') else 'Unassigned',
            'reporter': fields.get('reporter', {}).get('displayName', 'Unknown') if fields.get('reporter') else 'Unknown',
            'created': fields.get('created', ''),
            'updated': fields.get('updated', ''),
            'url': f"{self.jira_url}/browse/{issue.get('key')}",
            'custom_fields': {k: v for k, v in fields.items() if k.startswith('customfield_')}
        }
    
    def get_issue_transitions(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Get available transitions for an issue
        
        Args:
            issue_key: Jira issue key
            
        Returns:
            List of available transitions
        """
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/issue/{issue_key}/transitions",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            return [{
                'id': t.get('id'),
                'name': t.get('name'),
                'to_status': t.get('to', {}).get('name', '')
            } for t in data.get('transitions', [])]
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching transitions: {e}")
            return []
    
    def add_comment(self, issue_key: str, comment: str) -> bool:
        """
        Add a comment to a Jira issue
        
        Args:
            issue_key: Jira issue key
            comment: Comment text
            
        Returns:
            True if successful, False otherwise
        """
        try:
            response = requests.post(
                f"{self.jira_url}/rest/api/3/issue/{issue_key}/comment",
                auth=self.auth,
                headers=self.headers,
                json={
                    "body": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": comment
                                    }
                                ]
                            }
                        ]
                    }
                },
                timeout=10
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"❌ Error adding comment: {e}")
            return False
    
    def get_issue_comments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get all comments for an issue"""
        try:
            response = requests.get(
                f"{self.jira_url}/rest/api/3/issue/{issue_key}/comments",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            comments = []
            for comment in data.get('comments', []):
                comments.append({
                    'author': comment.get('author', {}).get('displayName', 'Unknown'),
                    'created': comment.get('created', ''),
                    'body': comment.get('body', ''),
                    'updated': comment.get('updated', '')
                })
            return comments
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching comments: {e}")
            return []
    
    def get_issue_attachments(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get all attachments for an issue"""
        try:
            issue = self.get_issue(issue_key)
            if not issue:
                return []
            
            # Attachments are in custom_fields, need to fetch full issue
            response = requests.get(
                f"{self.jira_url}/rest/api/3/issue/{issue_key}",
                auth=self.auth,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            attachments = []
            for attachment in data.get('fields', {}).get('attachment', []):
                attachments.append({
                    'filename': attachment.get('filename', ''),
                    'size': attachment.get('size', 0),
                    'created': attachment.get('created', ''),
                    'author': attachment.get('author', {}).get('displayName', 'Unknown'),
                    'url': attachment.get('content', '')
                })
            return attachments
        except requests.exceptions.RequestException as e:
            print(f"❌ Error fetching attachments: {e}")
            return []
